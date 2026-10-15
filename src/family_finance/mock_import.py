"""Convert local bank CSV exports into Enable Banking Mock ASPSP import JSON.

The generated files contain real financial details. Keep them under secrets/ and
never send them to logs or stdout. Uploading them to a third party is a user action.
"""

from __future__ import annotations

import argparse
import csv
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal, InvalidOperation
import json
from pathlib import Path
import re
from typing import Any

from .config import Settings
from .provider import EnableBankingClient
from .secrets import FinanceError, read_private, uuid_text, write_private


@dataclass(frozen=True)
class Statement:
    source: Path
    account_number: str
    currency: str
    export_date: str
    opening_date: str
    header_details: str
    opening_balance: str
    closing_balance: str
    rows: list[list[str]]


def _date(value: str, *, export: bool = False) -> str:
    formats = ("%Y-%m-%d",) if export else ("%d-%m-%Y",)
    for pattern in formats:
        try:
            return datetime.strptime(value.strip(), pattern).date().isoformat()
        except ValueError:
            continue
    raise FinanceError("CSV contains an invalid date")


def _money(value: str) -> Decimal:
    try:
        amount = Decimal(value.replace(" ", "").replace("\u00a0", "").replace(",", "."))
    except InvalidOperation as exc:
        raise FinanceError("CSV contains an invalid amount") from exc
    if not amount.is_finite() or amount.as_tuple().exponent < -2:
        raise FinanceError("CSV amount has unsupported precision")
    return amount


def _amount(value: Decimal) -> str:
    return format(value.quantize(Decimal("0.01")), ".2f")


def read_statement(path: Path) -> Statement:
    with path.open("r", encoding="utf-8-sig", newline="") as stream:
        records = list(csv.reader(stream))
    if len(records) < 2 or any(len(row) != 9 for row in records):
        raise FinanceError("CSV must contain a summary row and nine-column transactions")
    header, rows = records[0], records[1:]
    if header[7].strip() != str(len(rows)):
        raise FinanceError("CSV summary transaction count does not match rows")
    number = path.stem.split("_")[-1]
    if not re.fullmatch(r"\d{26}", number) or number not in re.sub(r"\D", "", header[2]):
        raise FinanceError("CSV account number does not match its filename")
    currency = header[4].strip().upper()
    if currency not in {"PLN", "EUR", "USD"}:
        raise FinanceError("Unexpected CSV account currency")
    export_date = _date(header[0], export=True)
    opening_date = _date(header[1])
    opening_balance = _amount(_money(header[5]))
    closing_balance = _amount(_money(header[6]))
    numbers = []
    for row in rows:
        _date(row[0])
        _date(row[1])
        _money(row[5])
        _money(row[6])
        if not row[7].strip().isdigit():
            raise FinanceError("CSV transaction sequence is invalid")
        numbers.append(int(row[7]))
    if sorted(numbers) != list(range(1, len(rows) + 1)):
        raise FinanceError("CSV transaction sequence is incomplete or duplicated")
    return Statement(path, number, currency, export_date, opening_date,
                     header[3], opening_balance, closing_balance, rows)


def _iban(value: str) -> str | None:
    normalized = re.sub(r"\s+", "", value).upper()
    if re.fullmatch(r"\d{26}", normalized):
        return "PL" + normalized
    if re.fullmatch(r"PL\d{26}", normalized):
        return normalized
    return None


def _transaction(row: list[str], currency: str) -> dict[str, Any]:
    signed = _money(row[5])
    incoming = signed > 0
    reference = "CSV-" + row[7].strip()
    result: dict[str, Any] = {
        "entry_reference": reference,
        "transaction_amount": {"currency": currency, "amount": _amount(abs(signed))},
        "credit_debit_indicator": "CRDT" if incoming else "DBIT",
        "status": "BOOK",
        "booking_date": _date(row[0]),
        "transaction_date": _date(row[1]),
        "balance_after_transaction": {"currency": currency, "amount": _amount(_money(row[6]))},
        "remittance_information": [text for text in (row[2], row[3], row[4]) if text],
    }
    if row[3]:
        result["debtor" if incoming else "creditor"] = {
            "name": row[3], "postal_address": None,
            "organisation_id": None, "private_id": None,
        }
    counterpart_iban = _iban(row[4])
    if counterpart_iban:
        result["debtor_account" if incoming else "creditor_account"] = {
            "iban": counterpart_iban, "other": None,
        }
    return result


def build_account(statement: Statement, current_account: dict[str, Any]) -> dict[str, Any]:
    if current_account.get("currency") != statement.currency:
        raise FinanceError("CSV currency does not match selected Mock ASPSP account")
    uid = current_account.get("uid")
    if not isinstance(uid, str) or not current_account.get("identification_hash"):
        raise FinanceError("Mock ASPSP account metadata is incomplete")
    iban = "PL" + statement.account_number
    keys = ("account_servicer", "cash_account_type", "credit_limit", "name", "product",
            "psu_status", "usage")
    info = {key: current_account.get(key) for key in keys}
    info.update({
        "account_id": {"iban": iban, "other": None},
        "all_account_ids": [{"scheme_name": "IBAN", "identification": iban, "issuer": None}],
        "currency": statement.currency,
        "details": statement.header_details,
        "identification_hash": current_account["identification_hash"],
        "linked_account": None,
        "resource_id": uid,
    })
    transactions = [_transaction(row, statement.currency) for row in statement.rows]
    closing_balance = {
        "name": "Booked balance",
        "balance_amount": {"currency": statement.currency, "amount": statement.closing_balance},
        "balance_type": "CLBD",
        "reference_date": statement.export_date,
        "last_committed_transaction": transactions[0]["entry_reference"],
    }
    opening_balance = {
        "name": "Opening booked balance",
        "balance_amount": {"currency": statement.currency, "amount": statement.opening_balance},
        "balance_type": "OPBD",
        "reference_date": statement.opening_date,
    }
    return {"info": info, "transactions": transactions,
            "balances": [opening_balance, closing_balance]}


def write_import_files(accounts: list[dict[str, Any]], output_dir: Path) -> None:
    if len(accounts) != 4:
        raise FinanceError("Expected four Mock ASPSP accounts")
    output_dir.mkdir(mode=0o700, parents=True, exist_ok=True)
    if output_dir.stat().st_mode & 0o077:
        raise FinanceError("Mock import directory permissions are unsafe")
    for index, account in enumerate(accounts, 1):
        write_private(output_dir / f"account-{index}.json",
                      json.dumps({"accounts": [account]}, ensure_ascii=False, indent=2) + "\n")
    write_private(output_dir / "all-accounts.json",
                  json.dumps({"accounts": accounts}, ensure_ascii=False, indent=2) + "\n")


def generate(source_dir: Path, output_dir: Path, *, reverse_pln: bool = False) -> list[int]:
    paths = sorted(source_dir.glob("historia_*.csv"))
    if len(paths) != 4:
        raise FinanceError("Expected exactly four CSV statements")
    statements = [read_statement(path) for path in paths]
    grouped: dict[str, list[Statement]] = {"PLN": [], "EUR": [], "USD": []}
    for statement in statements:
        grouped[statement.currency].append(statement)
    if sorted(map(len, grouped.values())) != [1, 1, 2]:
        raise FinanceError("Expected two PLN, one EUR, and one USD statement")
    grouped["PLN"].sort(key=lambda statement: len(statement.rows), reverse=True)
    if reverse_pln:
        grouped["PLN"].reverse()
    selected = grouped["PLN"] + grouped["EUR"] + grouped["USD"]

    settings = Settings.load("sandbox")
    client = EnableBankingClient(settings)
    try:
        session_id = uuid_text(read_private(settings.secrets_dir / "session_id").decode().strip())
        session = client.request("GET", f"/sessions/{session_id}")
        if session.get("status") != "AUTHORIZED" or len(session.get("accounts", [])) != 4:
            raise FinanceError("Expected an authorized four-account sandbox session")
        details = [client.request("GET", f"/accounts/{uuid_text(uid)}/details")
                   for uid in session["accounts"]]
    finally:
        client.close()
    accounts = [build_account(statement, detail)
                for statement, detail in zip(selected, details, strict=True)]
    write_import_files(accounts, output_dir)
    return [len(statement.rows) for statement in selected]


def main() -> int:
    parser = argparse.ArgumentParser(description="Create private Mock ASPSP JSON from four CSV statements")
    parser.add_argument("--source-dir", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path)
    parser.add_argument("--reverse-pln", action="store_true")
    args = parser.parse_args()
    try:
        settings = Settings.load("sandbox")
        output_dir = args.output_dir or settings.secrets_dir / "mock-import"
        counts = generate(args.source_dir, output_dir, reverse_pln=args.reverse_pln)
        print(f"Mock import saved locally: 4 accounts, {sum(counts)} transactions; "
              f"counts by account={counts}; output directory={output_dir}")
        return 0
    except (FinanceError, OSError, UnicodeError) as exc:
        parser.exit(1, f"Error: {exc if isinstance(exc, FinanceError) else 'local file operation failed'}\n")
