"""Household PLN cash ledger. No cash details leave the authenticated dashboard."""

from __future__ import annotations

from datetime import date, datetime, timedelta
from decimal import Decimal
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from .accounting import money
from .classification import category_by_path, household
from .models import Account, BankConnection, CashEntry, Category, Project, Transaction
from .secrets import FinanceError

CENT = Decimal("0.01")


def _date(value: object) -> date:
    try:
        result = date.fromisoformat(value) if isinstance(value, str) else None
    except ValueError:
        result = None
    if result is None or result > datetime.now().date():
        raise FinanceError("Invalid cash date")
    return result


def _amount(value: object) -> Decimal:
    result = money(value, positive=True)
    if result <= 0 or result.quantize(CENT) != result:
        raise FinanceError("Cash amount must be positive with at most two decimals")
    return result


def cash_balance(db: Session, day: date) -> Decimal:
    home = household(db)
    return sum((row.amount for row in db.scalars(select(CashEntry).where(
        CashEntry.household_id == home.id, CashEntry.occurred_on <= day))), Decimal(0))


def _ensure_nonnegative(db: Session, home_id: UUID, day: date, delta: Decimal) -> None:
    rows = db.scalars(select(CashEntry).where(CashEntry.household_id == home_id)
        .order_by(CashEntry.occurred_on)).all()
    balance = Decimal(0)
    current_day = None
    for row in rows:
        if current_day is not None and row.occurred_on != current_day:
            if balance + (delta if current_day >= day else 0) < 0:
                raise FinanceError("This change would make a later cash balance negative")
        current_day = row.occurred_on
        balance += row.amount
    if balance + delta < 0:
        raise FinanceError("Not enough cash on this date; set an opening balance first")


def cash_report(db: Session, month: str) -> dict:
    if len(month) != 7 or month[4] != "-":
        raise FinanceError("Invalid month")
    try:
        year, number = map(int, month.split("-"))
        start = date(year, number, 1)
        end = date(year + (number == 12), number % 12 + 1, 1)
    except ValueError as exc:
        raise FinanceError("Invalid month") from exc
    home = household(db)
    rows = db.scalars(select(CashEntry).where(CashEntry.household_id == home.id,
        CashEntry.occurred_on >= start, CashEntry.occurred_on < end)
        .order_by(CashEntry.occurred_on.desc(), CashEntry.created_at.desc())).all()
    categories = {row.id: row for row in db.scalars(select(Category).where(
        Category.household_id == home.id))}
    projects = {row.id: row.name for row in db.scalars(select(Project).where(
        Project.household_id == home.id))}
    linked = {tx.id: tx for tx in db.scalars(select(Transaction).where(
        Transaction.id.in_([row.transaction_id for row in rows if row.transaction_id])))} if rows else {}
    has_opening = db.scalar(select(CashEntry.id).where(CashEntry.household_id == home.id,
        CashEntry.kind == "opening").limit(1)) is not None
    return {"currency": "PLN", "period": month, "has_opening": has_opening,
        "balance": str(cash_balance(db, min(date.today(), end - timedelta(days=1))).quantize(CENT)),
        "received": str(sum((row.amount for row in rows if row.kind == "reimbursement"), Decimal(0)).quantize(CENT)),
        "spent": str(-sum((row.amount for row in rows if row.kind == "expense"), Decimal(0)).quantize(CENT)),
        "rows": [{"id": str(row.id), "date": str(row.occurred_on), "kind": row.kind,
                  "amount": str(row.amount), "note": row.note or "",
                  "transaction_id": str(row.transaction_id) if row.transaction_id else None,
                  "purchase": (linked[row.transaction_id].description or "Банковская покупка")[:250]
                    if row.transaction_id in linked else None,
                  "category": ((f"{categories[categories[row.category_id].parent_id].name}/" if
                      categories[row.category_id].parent_id in categories else "") +
                      categories[row.category_id].name if row.category_id in categories else None),
                  "project": projects.get(row.project_id)} for row in rows]}


def add_cash(db: Session, payload: dict) -> dict:
    kind = payload.get("kind")
    required = {"kind", "date", "amount"}
    optional = {"transaction_id", "category", "project", "note"}
    if kind not in {"opening", "reimbursement", "expense"} or required - set(payload) or set(payload) - required - optional:
        raise FinanceError("Invalid cash entry fields")
    home = household(db)
    day = _date(payload["date"])
    amount = _amount(payload["amount"])
    note = payload.get("note") or None
    if note is not None and (not isinstance(note, str) or len(note) > 250):
        raise FinanceError("Invalid cash note")
    tx_id = None
    category_id = None
    project_id = None
    if kind == "opening":
        if db.scalar(select(CashEntry.id).where(CashEntry.household_id == home.id,
                CashEntry.kind == "opening").limit(1)):
            raise FinanceError("Opening balance already exists; delete it before replacing")
        earliest = db.scalar(select(CashEntry.occurred_on).where(
            CashEntry.household_id == home.id).order_by(CashEntry.occurred_on).limit(1))
        if earliest and day > earliest:
            raise FinanceError("Opening balance date must be before other cash entries")
        if any(payload.get(key) for key in ("transaction_id", "category", "project")):
            raise FinanceError("Opening balance cannot be linked to a purchase")
    elif kind == "reimbursement":
        if not payload.get("transaction_id") or any(payload.get(key) for key in ("category", "project")):
            raise FinanceError("Select one bank purchase for the reimbursement")
        try:
            tx_id = UUID(str(payload["transaction_id"]))
        except ValueError as exc:
            raise FinanceError("Invalid bank purchase") from exc
        tx = db.scalar(select(Transaction).join(Account).join(BankConnection).where(
            Transaction.id == tx_id, BankConnection.household_id == home.id))
        if tx is None or tx.status != "BOOK" or tx.currency != "PLN" or tx.amount >= 0 or \
                tx.economic_type not in {"consumption", "project_expense", "unclassified"}:
            raise FinanceError("Select a completed PLN purchase")
        if day < (tx.transaction_date or tx.booking_date or day):
            raise FinanceError("Cash cannot be received before the purchase")
        prior = sum((row.amount for row in db.scalars(select(CashEntry).where(
            CashEntry.household_id == home.id, CashEntry.kind == "reimbursement",
            CashEntry.transaction_id == tx_id))), Decimal(0))
        if prior + amount > -tx.amount:
            raise FinanceError("Total reimbursements cannot exceed the purchase")
    else:
        if payload.get("transaction_id"):
            raise FinanceError("A cash expense is not a bank transaction")
        category = payload.get("category")
        project = payload.get("project")
        if category:
            if not isinstance(category, str) or category == "Income" or category.startswith("Income/"):
                raise FinanceError("Select an expense category")
            category_id = category_by_path(db, home.id, category).id
        if project:
            item = db.scalar(select(Project).where(Project.household_id == home.id,
                Project.name == project))
            if item is None:
                raise FinanceError("Unknown project")
            project_id = item.id
        if cash_balance(db, day) < amount:
            raise FinanceError("Not enough cash on this date; set an opening balance first")
        _ensure_nonnegative(db, home.id, day, -amount)
    entry = CashEntry(household_id=home.id, occurred_on=day,
        amount=-amount if kind == "expense" else amount, kind=kind,
        transaction_id=tx_id, category_id=category_id, project_id=project_id, note=note)
    db.add(entry)
    db.commit()
    return {"saved": 1, "id": str(entry.id)}


def delete_cash(db: Session, payload: dict) -> dict:
    if set(payload) != {"id"}:
        raise FinanceError("Invalid cash entry fields")
    try:
        entry_id = UUID(str(payload["id"]))
    except ValueError as exc:
        raise FinanceError("Invalid cash entry") from exc
    home = household(db)
    entry = db.scalar(select(CashEntry).where(CashEntry.id == entry_id,
        CashEntry.household_id == home.id))
    if entry is None:
        raise FinanceError("Cash entry not found")
    if entry.kind == "opening" and db.scalar(select(CashEntry.id).where(
            CashEntry.household_id == home.id, CashEntry.id != entry.id).limit(1)):
        raise FinanceError("Delete later cash entries before deleting the opening balance")
    if entry.amount > 0:
        _ensure_nonnegative(db, home.id, entry.occurred_on, -entry.amount)
    db.delete(entry)
    db.commit()
    return {"deleted": 1}
