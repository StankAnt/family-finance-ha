"""Normalize AIS and CSV rows into an idempotent local ledger."""

from __future__ import annotations

from collections import Counter, defaultdict
from datetime import date
from decimal import Decimal, InvalidOperation
import hashlib
import json
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from .models import Account, AccountBalanceSnapshot, SyncRun, Transaction, now
from .secrets import FinanceError


def _date(raw: object) -> date | None:
    if raw is None:
        return None
    if not isinstance(raw, str):
        raise FinanceError("Invalid transaction date")
    try:
        return date.fromisoformat(raw[:10])
    except ValueError as exc:
        raise FinanceError("Invalid transaction date") from exc


def _amount(raw: object, currency: str) -> Decimal:
    if not isinstance(raw, dict) or raw.get("currency") != currency:
        raise FinanceError("Transaction amount currency mismatch")
    try:
        value = Decimal(str(raw["amount"]))
    except (KeyError, InvalidOperation) as exc:
        raise FinanceError("Invalid transaction amount") from exc
    if not value.is_finite() or value.as_tuple().exponent < -4:
        raise FinanceError("Invalid transaction amount precision")
    return value


def _digest(value: object) -> str:
    encoded = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode()).hexdigest()


def _text(raw: object) -> str | None:
    if isinstance(raw, str):
        return raw or None
    if isinstance(raw, list) and all(isinstance(item, str) for item in raw):
        return "\n".join(item for item in raw if item) or None
    return None


def _normalized(raw: dict[str, Any], currency: str) -> dict[str, Any]:
    indicator = raw.get("credit_debit_indicator")
    if indicator not in {"CRDT", "DBIT"}:
        raise FinanceError("Invalid credit/debit indicator")
    amount = _amount(raw.get("transaction_amount"), currency)
    if amount < 0:
        raise FinanceError("Provider amount must be unsigned")
    amount = amount if indicator == "CRDT" else -amount
    status = raw.get("status")
    if status not in {"BOOK", "CNCL", "HOLD", "OTHR", "PDNG", "RJCT", "SCHD"}:
        raise FinanceError("Unexpected transaction status")
    party = raw.get("debtor") if indicator == "CRDT" else raw.get("creditor")
    party_name = party.get("name") if isinstance(party, dict) else None
    if party_name is not None and not isinstance(party_name, str):
        party_name = None
    reference = raw.get("entry_reference")
    reference = reference.strip() if isinstance(reference, str) else None
    provider_id = raw.get("transaction_id")
    provider_id = provider_id if isinstance(provider_id, str) else None
    other_account = raw.get("debtor_account") if indicator == "CRDT" else raw.get("creditor_account")
    other_iban = other_account.get("iban") if isinstance(other_account, dict) else None
    other_digest = (hashlib.sha256(other_iban.replace(" ", "").upper().encode()).hexdigest()
                    if isinstance(other_iban, str) and other_iban else None)
    result = {
        "entry_reference": reference or None,
        "provider_transaction_id": provider_id,
        "status": status,
        "booking_date": _date(raw.get("booking_date")),
        "value_date": _date(raw.get("value_date")),
        "transaction_date": _date(raw.get("transaction_date")),
        "amount": amount,
        "currency": currency,
        "description": _text(raw.get("remittance_information")),
        "counterparty_name": party_name,
        "counterparty_identifier_digest": other_digest,
        "payload_hash": _digest(raw),
    }
    return result


def prepare_transactions(rows: list[dict[str, Any]], currency: str) -> list[dict[str, Any]]:
    normalized = [_normalized(row, currency) for row in rows]
    references = Counter(item["entry_reference"] for item in normalized if item["entry_reference"])
    occurrences: defaultdict[str, int] = defaultdict(int)
    for item in normalized:
        reference = item["entry_reference"]
        if reference and references[reference] == 1:
            item["identity_key"] = "r:" + _digest(reference)
        else:
            # Equal purchases get separate occurrence numbers. Unstable bank data
            # may produce a new row; that is safer than merging distinct purchases.
            facts = {key: item[key] for key in (
                "status", "booking_date", "value_date", "transaction_date", "amount",
                "currency", "description", "counterparty_name")}
            fingerprint = _digest({key: str(value) for key, value in facts.items()})
            occurrences[fingerprint] += 1
            item["identity_key"] = f"f:{fingerprint}:{occurrences[fingerprint]}"
    return normalized


def save_transactions(db: Session, account: Account, rows: list[dict[str, Any]]) -> tuple[int, int]:
    prepared = prepare_transactions(rows, account.currency)
    inserted = updated = 0
    for item in prepared:
        identity = item.pop("identity_key")
        current = db.scalar(select(Transaction).where(
            Transaction.account_id == account.id, Transaction.identity_key == identity))
        if current is None:
            db.add(Transaction(account_id=account.id, identity_key=identity, **item))
            inserted += 1
        elif (current.payload_hash != item["payload_hash"] or
              current.counterparty_identifier_digest != item["counterparty_identifier_digest"]):
            for key, value in item.items():
                if key == "transaction_date" and value is None and current.transaction_date is not None:
                    # Keep a date recovered from a statement when AIS omits it.
                    continue
                setattr(current, key, value)
            current.updated_at = now()
            # Classification and manual overrides intentionally survive updates.
            updated += 1
    return inserted, updated


def prune_pending_transactions(db: Session, account: Account,
                               rows: list[dict[str, Any]]) -> int:
    """Remove holds absent from a complete fresh account response."""
    current = {row["identity_key"] for row in prepare_transactions(rows, account.currency)}
    stale = db.scalars(select(Transaction).where(
        Transaction.account_id == account.id,
        Transaction.status.in_(("HOLD", "PDNG")))).all()
    removed = 0
    for transaction in stale:
        if transaction.identity_key not in current:
            db.delete(transaction)
            removed += 1
    return removed


def save_balances(db: Session, account: Account, run: SyncRun,
                  balances: list[dict[str, Any]]) -> None:
    for raw in balances:
        kind = raw.get("balance_type")
        if not isinstance(kind, str) or len(kind) > 20:
            raise FinanceError("Invalid balance type")
        db.add(AccountBalanceSnapshot(
            account_id=account.id, sync_run_id=run.id, balance_type=kind,
            reference_date=_date(raw.get("reference_date")),
            amount=_amount(raw.get("balance_amount"), account.currency),
            currency=account.currency))
