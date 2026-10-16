"""Restartable AIS and CSV synchronization for manual and scheduled reads."""

from __future__ import annotations

import argparse
from datetime import date, datetime, timedelta, timezone
import hashlib
import ipaddress
import subprocess
from pathlib import Path
import sys
from uuid import UUID

from sqlalchemy import create_engine, func, select
from sqlalchemy.engine import make_url
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from .config import Settings
from .ledger import prune_pending_transactions, save_balances, save_transactions
from .mock_import import _transaction, read_statement
from .models import Account, BankConnection, Household, SyncCheckpoint, SyncRun, Transaction, now
from .provider import EnableBankingClient
from .secrets import FinanceError, read_private, uuid_text
from .session_store import session_ids


def database_engine(path: Path) -> Engine:
    raw_url = read_private(path).decode("utf-8").strip()
    if not raw_url.startswith("postgresql+psycopg://"):
        raise FinanceError("Database URL must use PostgreSQL and psycopg")
    url = make_url(raw_url)
    if path.name == "production_database_url_host":
        try:
            result = subprocess.run(
                ["docker", "inspect", "family-finance-db-1", "--format",
                 "{{(index .NetworkSettings.Networks \"family-finance_finance_private\").IPAddress}}"],
                capture_output=True, text=True, check=True, timeout=5)
            address = str(ipaddress.ip_address(result.stdout.strip()))
        except (OSError, subprocess.CalledProcessError, subprocess.TimeoutExpired, ValueError):
            raise FinanceError("Could not resolve local finance database") from None
        url = url.set(host=address, port=5432)
    return create_engine(url, pool_pre_ping=True)


def _household(db: Session) -> Household:
    existing = db.scalars(select(Household).limit(2)).all()
    if len(existing) > 1:
        raise FinanceError("Multiple households require explicit selection")
    if existing:
        return existing[0]
    household = Household(name="Family")
    db.add(household)
    db.flush()
    return household


def _connection(db: Session, settings: Settings) -> BankConnection:
    household = _household(db)
    connection = db.scalar(select(BankConnection).where(
        BankConnection.household_id == household.id,
        BankConnection.environment == settings.environment,
        BankConnection.application_id == settings.application_id))
    if connection is None:
        connection = BankConnection(household_id=household.id,
                                    environment=settings.environment,
                                    application_id=settings.application_id)
        db.add(connection)
        db.flush()
    return connection


def _account(db: Session, connection: BankConnection, uid: str,
             details: dict) -> Account:
    identity = details.get("identification_hash")
    currency = details.get("currency")
    if not isinstance(identity, str) or not identity or len(identity) > 255:
        raise FinanceError("Account identification hash is missing")
    if not isinstance(currency, str) or len(currency) != 3 or not currency.isalpha():
        raise FinanceError("Invalid account currency")
    bank_account = details.get("account_id")
    iban = bank_account.get("iban") if isinstance(bank_account, dict) else None
    digest = hashlib.sha256(iban.replace(" ", "").upper().encode()).hexdigest() if isinstance(iban, str) and iban else None
    account = db.scalar(select(Account).where(
        Account.connection_id == connection.id, Account.identification_hash == identity))
    if account is None:
        account = Account(connection_id=connection.id, identification_hash=identity,
                          provider_uid=uid, currency=currency, identifier_digest=digest,
                          name=details.get("name") if isinstance(details.get("name"), str) else None)
        db.add(account)
        db.flush()
    else:
        if account.currency != currency:
            raise FinanceError("Existing account currency changed")
        account.provider_uid = uid
        account.identifier_digest = digest or account.identifier_digest
        account.last_seen_at = now()
        account.active = True
    return account


def _fetch_pages(client: EnableBankingClient, uid: str,
                 start: date | None, end: date) -> list[dict]:
    rows: list[dict] = []
    continuation = None
    seen: set[str] = set()
    for _ in range(500):
        params = ({"strategy": "longest"} if start is None else
                  {"date_from": start.isoformat(), "date_to": end.isoformat()})
        if continuation:
            params["continuation_key"] = continuation
        result = client.request("GET", f"/accounts/{uid}/transactions", params=params)
        page = result.get("transactions")
        if not isinstance(page, list) or not all(isinstance(row, dict) for row in page):
            raise FinanceError("Invalid transaction page")
        rows.extend(page)
        continuation = result.get("continuation_key")
        if not continuation:
            return rows
        if not isinstance(continuation, str) or continuation in seen:
            raise FinanceError("Invalid transaction pagination")
        seen.add(continuation)
    raise FinanceError("Transaction pagination exceeded safety limit")


def _consent_until(raw: object) -> datetime | None:
    if not isinstance(raw, str):
        return None
    try:
        parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def sync_ais(engine: Engine, settings: Settings, *, from_date: date | None = None,
             full: bool = False,
             overlap_days: int = 7,
             initial_from_date: date | None = None,
             psu_headers: dict[str, str] | None = None,
             known_accounts_only: bool = False) -> tuple[int, int]:
    if not 1 <= overlap_days <= 30:
        raise FinanceError("Overlap must be between 1 and 30 days")
    client = (EnableBankingClient(settings, psu_headers=psu_headers) if psu_headers
              else EnableBankingClient(settings))
    run_id = None
    try:
        sessions = [client.request("GET", f"/sessions/{session_id}")
                    for session_id in session_ids(settings)]
        uids = []
        for provider_session in sessions:
            if provider_session.get("status") != "AUTHORIZED":
                raise FinanceError("AIS consent is not authorized")
            accounts = provider_session.get("accounts")
            if not isinstance(accounts, list):
                raise FinanceError("Session account list is invalid")
            for raw_uid in accounts:
                uid = uuid_text(raw_uid)
                if uid not in uids:
                    uids.append(uid)
        with Session(engine) as db, db.begin():
            connection = _connection(db, settings)
            connection.consent_status = "AUTHORIZED"
            valid_until = [_consent_until(item.get("valid_until")) for item in sessions]
            connection.consent_valid_until = min((value for value in valid_until if value), default=None)
            connection.last_checked_at = now()
            run = SyncRun(connection_id=connection.id, source="ais")
            db.add(run)
            db.flush()
            run_id = run.id
        total = 0
        for uid in uids:
            if known_accounts_only:
                with Session(engine) as db:
                    connection = _connection(db, settings)
                    existing_account = db.scalar(select(Account).where(
                        Account.connection_id == connection.id, Account.provider_uid == uid))
                    if existing_account is None:
                        continue
                    checkpoint = db.get(SyncCheckpoint, existing_account.id)
                    start = None if full else from_date or (
                        checkpoint.last_successful_to - timedelta(days=overlap_days)
                        if checkpoint and checkpoint.last_successful_to else initial_from_date)
                    account_id = existing_account.id
                end = datetime.now(timezone.utc).date()
                balances = client.request("GET", f"/accounts/{uid}/balances").get("balances")
                if not isinstance(balances, list):
                    raise FinanceError("Invalid account balances")
                rows = _fetch_pages(client, uid, start, end)
                with Session(engine) as db, db.begin():
                    account = db.get(Account, account_id)
                    run = db.get(SyncRun, run_id)
                    save_transactions(db, account, rows)
                    prune_pending_transactions(db, account, rows)
                    save_balances(db, account, run, balances)
                    checkpoint = db.get(SyncCheckpoint, account.id)
                    if checkpoint is None:
                        checkpoint = SyncCheckpoint(account_id=account.id)
                        db.add(checkpoint)
                    checkpoint.last_successful_to = end
                    checkpoint.last_successful_at = now()
                    checkpoint.last_run_id = run_id
                    run.account_count += 1
                    run.transaction_count += len(rows)
                    total += len(rows)
                continue
            details = client.request("GET", f"/accounts/{uid}/details")
            balances = client.request("GET", f"/accounts/{uid}/balances").get("balances")
            if not isinstance(balances, list):
                raise FinanceError("Invalid account balances")
            with Session(engine) as db, db.begin():
                connection = _connection(db, settings)
                account = _account(db, connection, uid, details)
                checkpoint = db.get(SyncCheckpoint, account.id)
                start = None if full else from_date or (checkpoint.last_successful_to - timedelta(days=overlap_days)
                                      if checkpoint and checkpoint.last_successful_to else initial_from_date)
            end = datetime.now(timezone.utc).date()
            rows = _fetch_pages(client, uid, start, end)
            with Session(engine) as db, db.begin():
                connection = _connection(db, settings)
                account = _account(db, connection, uid, details)
                run = db.get(SyncRun, run_id)
                inserted, updated = save_transactions(db, account, rows)
                prune_pending_transactions(db, account, rows)
                save_balances(db, account, run, balances)
                checkpoint = db.get(SyncCheckpoint, account.id)
                if checkpoint is None:
                    checkpoint = SyncCheckpoint(account_id=account.id)
                    db.add(checkpoint)
                checkpoint.last_successful_to = end
                checkpoint.last_successful_at = now()
                checkpoint.last_run_id = run_id
                run.account_count += 1
                run.transaction_count += len(rows)
                total += len(rows)
        with Session(engine) as db, db.begin():
            run = db.get(SyncRun, run_id)
            run.status = "SUCCESS"
            run.finished_at = now()
        return len(uids), total
    except Exception as exc:
        if run_id is not None:
            with Session(engine) as db, db.begin():
                run = db.get(SyncRun, run_id)
                if run:
                    run.status = "FAILED"
                    run.error_code = ("PROVIDER" if isinstance(exc, FinanceError) else "INTERNAL")
                    run.finished_at = now()
        raise
    finally:
        client.close()


def import_csv(engine: Engine, csv_file: Path, account_id: UUID | None = None) -> int:
    statement = read_statement(csv_file)
    with Session(engine) as db, db.begin():
        expected_iban = "PL" + statement.account_number
        expected_digest = hashlib.sha256(expected_iban.encode()).hexdigest()
        if account_id is None:
            matches = db.scalars(select(Account).where(
                Account.identifier_digest == expected_digest,
                Account.currency == statement.currency).limit(2)).all()
            if len(matches) != 1:
                raise FinanceError("CSV account is missing or ambiguous in the ledger")
            account = matches[0]
        else:
            account = db.get(Account, account_id)
        if (account is None or account.currency != statement.currency
                or account.identifier_digest != expected_digest):
            raise FinanceError("CSV account does not match selected ledger account")
        run = SyncRun(connection_id=account.connection_id, source="csv")
        db.add(run)
        db.flush()
        rows = [_transaction(row, statement.currency) for row in statement.rows]
        save_transactions(db, account, rows)
        run.account_count = 1
        run.transaction_count = len(rows)
        run.status = "SUCCESS"
        run.finished_at = now()
        return len(rows)


def sync_status(engine: Engine, environment: str) -> str:
    with Session(engine) as db:
        connections = db.scalars(select(BankConnection).where(
            BankConnection.environment == environment)).all()
        if not connections:
            return "No local connection or sync runs"
        connection_ids = [connection.id for connection in connections]
        account_count = db.scalar(select(func.count()).select_from(Account).where(
            Account.connection_id.in_(connection_ids)))
        transaction_count = db.scalar(select(func.count()).select_from(Transaction).join(Account).where(
            Account.connection_id.in_(connection_ids)))
        latest = db.scalar(select(SyncRun).where(SyncRun.connection_id.in_(connection_ids))
                           .order_by(SyncRun.started_at.desc()).limit(1))
        consent = ",".join(sorted(set(connection.consent_status for connection in connections)))
        last = latest.status if latest else "NEVER"
        return (f"consent={consent}; last_sync={last}; accounts={account_count}; "
                f"transactions={transaction_count}")


def main() -> int:
    parser = argparse.ArgumentParser(description="Synchronize local household ledger")
    parser.add_argument("--env", choices=("sandbox", "production"), default="sandbox")
    parser.add_argument("--database-url-file", type=Path, default=Path("secrets/database_url"))
    sub = parser.add_subparsers(dest="command", required=True)
    ais = sub.add_parser("ais")
    window = ais.add_mutually_exclusive_group()
    window.add_argument("--from-date", type=date.fromisoformat)
    window.add_argument("--full", action="store_true", help="Fetch longest available history again")
    csv = sub.add_parser("csv")
    csv.add_argument("--account-id", type=UUID)
    csv.add_argument("--file", type=Path, required=True)
    sub.add_parser("status")
    try:
        args = parser.parse_args()
        engine = database_engine(args.database_url_file)
        try:
            if args.command == "ais":
                accounts, rows = sync_ais(engine, Settings.load(args.env),
                                          from_date=args.from_date, full=args.full)
                print(f"AIS sync complete: accounts={accounts}, rows_seen={rows}")
            elif args.command == "csv":
                rows = import_csv(engine, args.file, args.account_id)
                print(f"CSV import complete: rows_seen={rows}")
            else:
                print(sync_status(engine, args.env))
        finally:
            engine.dispose()
        return 0
    except (FinanceError, OSError, UnicodeError, ValueError):
        print("Sync failed; inspect local status without exposing bank data", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
