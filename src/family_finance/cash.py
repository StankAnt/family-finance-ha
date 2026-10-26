"""Household cash ledger in original currencies."""

from __future__ import annotations

from datetime import date, datetime, timedelta
from decimal import Decimal
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from .accounting import currency, money, pln, rate
from .classification import category_by_path, household
from .models import Account, BankConnection, CashEntry, Category, FxRate, Project, PurchaseShare, Transaction
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


def cash_balances(db: Session, day: date) -> dict[str, Decimal]:
    home = household(db)
    balances: dict[str, Decimal] = {}
    for row in db.scalars(select(CashEntry).where(
            CashEntry.household_id == home.id, CashEntry.occurred_on <= day, CashEntry.affects_wallet.is_(True))):
        balances[row.currency] = balances.get(row.currency, Decimal(0)) + row.amount
    return balances


def cash_balance(db: Session, day: date, code: str = "PLN") -> Decimal:
    return cash_balances(db, day).get(code, Decimal(0))


def _rate_date(db: Session, code: str, day: date) -> str | None:
    if code == "PLN":
        return None
    effective = db.scalar(select(FxRate.effective_date).where(
        FxRate.currency == code, FxRate.source == "NBP_A_MID",
        FxRate.effective_date <= day, FxRate.effective_date >= day - timedelta(days=7))
        .order_by(FxRate.effective_date.desc()).limit(1))
    return str(effective) if effective else None


def _ensure_nonnegative(db: Session, home_id: UUID, day: date, code: str, delta: Decimal) -> None:
    rows = db.scalars(select(CashEntry).where(CashEntry.household_id == home_id,
            CashEntry.currency == code, CashEntry.affects_wallet.is_(True))
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
    as_of = min(date.today(), end - timedelta(days=1))
    balances = cash_balances(db, as_of)
    balance_rows = []
    total_pln = Decimal(0)
    missing_fx = []
    balance_missing = False
    for code, amount in sorted(balances.items()):
        converted = pln(db, amount, code, as_of)
        if converted is None and amount:
            missing_fx.append({"currency": code, "date": str(as_of)})
            balance_missing = True
        else:
            total_pln += converted or Decimal(0)
        balance_rows.append({"currency": code, "amount": str(amount.quantize(CENT)),
                             "amount_pln": str(converted) if converted is not None else None,
                             "rate": str(rate(db, code, as_of)) if code != "PLN" and converted is not None else None,
                             "rate_date": _rate_date(db, code, as_of)})
    spent = Decimal(0)
    spent_missing = False
    received = Decimal(0)
    received_missing = False
    for row in rows:
        if row.kind not in {"expense", "reimbursement"}:
            continue
        converted = pln(db, abs(row.amount), row.currency, row.occurred_on)
        if converted is None:
            missing_fx.append({"currency": row.currency, "date": str(row.occurred_on)})
            spent_missing |= row.kind == "expense"
            received_missing |= row.kind == "reimbursement"
        elif row.kind == "expense":
            spent += converted
        else:
            received += converted
    history_pln = {row.id: pln(db, row.amount, row.currency, row.occurred_on)
                   for row in rows}
    for row in rows:
        if history_pln[row.id] is None and row.amount:
            marker = {"currency": row.currency, "date": str(row.occurred_on)}
            if marker not in missing_fx:
                missing_fx.append(marker)
    opening_currencies = list(db.scalars(select(CashEntry.currency).where(
        CashEntry.household_id == home.id, CashEntry.kind == "opening")).all())
    return {"currency": "PLN", "period": month, "as_of": str(as_of),
        "opening_currencies": opening_currencies, "balances": balance_rows,
        "balance": str(total_pln.quantize(CENT)) if not balance_missing else None,
        "missing_fx": missing_fx,
        "received": str(received.quantize(CENT)) if not received_missing else None,
        "spent": str(spent.quantize(CENT)) if not spent_missing else None,
        "rows": [{"id": str(row.id), "date": str(row.occurred_on), "kind": row.kind,
                  "amount": str(row.amount), "currency": row.currency,
                  "affects_wallet": row.affects_wallet,
                  "person": db.get(PurchaseShare, row.share_id).person if row.share_id else None,
                  "amount_pln": str(history_pln[row.id]) if history_pln[row.id] is not None else None,
                  "rate_date": _rate_date(db, row.currency, row.occurred_on),
                  "note": row.note or "",
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
    optional = {"transaction_id", "category", "project", "note", "currency", "affects_wallet", "share_id"}
    if kind not in {"opening", "reimbursement", "expense"} or required - set(payload) or set(payload) - required - optional:
        raise FinanceError("Invalid cash entry fields")
    home = household(db)
    day = _date(payload["date"])
    amount = _amount(payload["amount"])
    code = currency(payload.get("currency", "PLN"))
    note = payload.get("note") or None
    if note is not None and (not isinstance(note, str) or len(note) > 250):
        raise FinanceError("Invalid cash note")
    tx_id = None
    category_id = None
    project_id = None
    share_id = None
    affects_wallet = payload.get("affects_wallet", True)
    if not isinstance(affects_wallet, bool) or (kind != "reimbursement" and (not affects_wallet or payload.get("share_id"))):
        raise FinanceError("Выбор кошелька и участника доступен только для возврата")
    if kind == "opening":
        if db.scalar(select(CashEntry.id).where(CashEntry.household_id == home.id,
                CashEntry.kind == "opening", CashEntry.currency == code).limit(1)):
            raise FinanceError("Opening balance for this currency already exists")
        earliest = db.scalar(select(CashEntry.occurred_on).where(
            CashEntry.household_id == home.id, CashEntry.currency == code, CashEntry.affects_wallet.is_(True))
            .order_by(CashEntry.occurred_on).limit(1))
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
        from types import SimpleNamespace
        from .purchase_returns import purchase, cash_in_purchase_currency, paid_share, refund_capacity
        tx = purchase(db, tx_id, lock=True)
        if day < (tx.transaction_date or tx.booking_date or day):
            raise FinanceError("Cash cannot be received before the purchase")
        converted = cash_in_purchase_currency(db, SimpleNamespace(amount=amount, currency=code, occurred_on=day), tx)
        if payload.get("share_id"):
            share = db.get(PurchaseShare, UUID(str(payload["share_id"])))
            if share is None or share.purchase_id != tx.id:
                raise FinanceError("Выберите участника этой покупки")
            share_id = share.id
            capacity = share.amount - paid_share(db, share, tx)
        else:
            if db.scalar(select(PurchaseShare.id).where(PurchaseShare.purchase_id == tx.id).limit(1)):
                raise FinanceError("Выберите, кто вернул деньги")
            capacity = refund_capacity(db, tx)
        if converted > capacity:
            raise FinanceError("Возврат превышает остаток покупки или долг участника")
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
        if cash_balance(db, day, code) < amount:
            raise FinanceError("Not enough cash on this date; set an opening balance first")
        _ensure_nonnegative(db, home.id, day, code, -amount)
    entry = CashEntry(household_id=home.id, occurred_on=day,
        amount=-amount if kind == "expense" else amount, currency=code, kind=kind,
        transaction_id=tx_id, category_id=category_id, project_id=project_id, note=note,
        affects_wallet=affects_wallet, share_id=share_id)
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
            CashEntry.household_id == home.id, CashEntry.currency == entry.currency,
            CashEntry.affects_wallet.is_(True),
            CashEntry.id != entry.id).limit(1)):
        raise FinanceError("Delete later cash entries before deleting the opening balance")
    if entry.amount > 0 and entry.affects_wallet:
        _ensure_nonnegative(db, home.id, entry.occurred_on, entry.currency, -entry.amount)
    db.delete(entry)
    db.commit()
    return {"deleted": 1}
