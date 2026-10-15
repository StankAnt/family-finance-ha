"""Private-network finance API for an authenticated Home Assistant integration."""

from __future__ import annotations

from datetime import date, datetime, timedelta
import hmac
from pathlib import Path
import re
from typing import Any, Literal
from uuid import UUID
from zoneinfo import ZoneInfo

from fastapi import FastAPI, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy import String, and_, cast, func, or_, select
from sqlalchemy.orm import Session

from .accounting import import_manual, monthly_report, pln, position_report
from .classification import (ECONOMIC_TYPES, add_project, add_rule, apply_overrides,
                             category_by_path, classify, confirm_manual_pair, decide_pair,
                             household)
from .models import (Account, AccountBalanceSnapshot, BankConnection, Category, ClassificationCorrection, DecisionSuggestion, Goal,
                     Mortgage, MortgageAllocation, Project, SyncRun, Transaction, TransferPair)
from .secrets import FinanceError, read_private
from .sync import database_engine

app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)


class Command(BaseModel):
    operation: str = Field(max_length=30)
    payload: dict[str, Any] = Field(default_factory=dict)
    source: Literal["sandbox", "production"] = "sandbox"


def _category_path(category: Category, categories: dict) -> str:
    parent = categories.get(category.parent_id)
    return f"{parent.name}/{category.name}" if parent else category.name


def _options(db: Session) -> dict:
    home = household(db)
    categories = {item.id: item for item in db.scalars(select(Category).where(
        Category.household_id == home.id)).all()}
    accounts = db.scalars(select(Account).join(BankConnection).where(
        BankConnection.household_id == home.id, Account.active.is_(True))
        .order_by(Account.currency, Account.name, Account.id)).all()
    account_choices = []
    for index, account in enumerate(accounts, 1):
        balances = db.scalars(select(AccountBalanceSnapshot).where(
            AccountBalanceSnapshot.account_id == account.id,
            AccountBalanceSnapshot.balance_type.in_(("CLBD", "ITBD")))).all()
        latest = max(balances, key=lambda row: (row.reference_date or row.observed_at.date(),
                                                 row.observed_at), default=None)
        label = f"{account.name or 'Счёт без названия'} · {account.currency} · №{index}"
        if latest:
            label += f" · последний остаток {latest.amount} ({latest.reference_date or latest.observed_at.date()})"
        account_choices.append({"id": str(account.id), "label": label})
    return {
        "accounts": account_choices,
        "categories": sorted(_category_path(item, categories) for item in categories.values()),
        "projects": sorted(item.name for item in db.scalars(select(Project).where(
            Project.household_id == home.id)).all()),
        "mortgages": sorted([{"name": item.name, "currency": item.currency} for item in db.scalars(
            select(Mortgage).where(Mortgage.household_id == home.id)).all()], key=lambda x: x["name"]),
        "goals": sorted([{"name": item.name, "currency": item.currency} for item in db.scalars(
            select(Goal).where(Goal.household_id == home.id)).all()], key=lambda x: x["name"]),
        "economic_types": sorted(ECONOMIC_TYPES - {"internal_transfer"}),
    }


def _review(db: Session, payload: dict) -> dict:
    home = household(db)
    limit, offset = int(payload.get("limit", 30)), int(payload.get("offset", 0))
    if not 1 <= limit <= 100 or not 0 <= offset <= 10000:
        raise FinanceError("Invalid review page")
    status = payload.get("status", "all")
    if status not in {"unclassified", "all", "pending"}:
        raise FinanceError("Invalid review filter")
    base = select(Transaction).join(Account).join(BankConnection).where(
        BankConnection.household_id == home.id)
    if status == "unclassified":
        base = base.where(Transaction.status == "BOOK",
                          Transaction.economic_type == "unclassified")
    elif status == "pending":
        base = base.where(Transaction.status.in_(("HOLD", "PDNG")))
    else:
        base = base.where(Transaction.status.in_(("BOOK", "HOLD", "PDNG")))
    # Show the purchase date when the bank provides one; posting can be days later.
    effective_date = func.coalesce(Transaction.transaction_date,
                                   Transaction.booking_date, Transaction.value_date)
    period = _period(payload)
    if period:
        start, end = _month_bounds(*period)
        base = base.where(effective_date >= start, effective_date < end)
    project_name = payload.get("project", "")
    category_path = payload.get("category", "")
    if not isinstance(project_name, str) or len(project_name) > 120:
        raise FinanceError("Invalid project filter")
    if not isinstance(category_path, str) or len(category_path) > 250:
        raise FinanceError("Invalid category filter")
    project = None
    if project_name:
        if project_name == "Без проекта":
            base = base.where(Transaction.project_id.is_(None),
                              Transaction.economic_type == "project_expense")
        else:
            project = db.scalar(select(Project).where(Project.household_id == home.id,
                                                      Project.name == project_name))
            if project is None:
                raise FinanceError("Unknown project filter")
            base = base.where(Transaction.project_id == project.id)
    categories = {item.id: item for item in db.scalars(select(Category).where(
        Category.household_id == home.id)).all()}
    if category_path:
        if category_path == "Other/Unclassified":
            base = base.where(Transaction.economic_type == "unclassified", Transaction.amount < 0)
        elif category_path == "Other/Uncategorized":
            base = base.where(Transaction.category_id.is_(None),
                              Transaction.economic_type.in_(("consumption", "project_expense",
                                                             "external_income")))
        elif category_path == "Other/External transfer":
            base = base.where(Transaction.economic_type == "external_transfer", Transaction.amount < 0)
        elif category_path in {"Housing/Mortgage interest", "Housing/Mortgage fees"}:
            allocated_ids = select(MortgageAllocation.transaction_id)
            part = MortgageAllocation.interest if category_path.endswith("interest") else MortgageAllocation.fees
            allocated_with_part = select(MortgageAllocation.transaction_id).where(part > 0)
            condition = Transaction.id.in_(allocated_with_part)
            if category_path.endswith("interest"):
                condition = or_(condition, and_(Transaction.economic_type == "mortgage_interest",
                                                ~Transaction.id.in_(allocated_ids)))
            base = base.where(condition)
        else:
            matching_ids = [item.id for item in categories.values()
                            if _category_path(item, categories) == category_path or
                            _category_path(item, categories).startswith(category_path + "/")]
            if not matching_ids:
                raise FinanceError("Unknown category filter")
            base = base.where(Transaction.category_id.in_(matching_ids))
    search = payload.get("search", "")
    if not isinstance(search, str) or len(search) > 120:
        raise FinanceError("Invalid review search")
    search = search.strip()
    if search:
        pattern = "%" + search.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"
        base = base.where(or_(
            Transaction.description.ilike(pattern, escape="\\"),
            cast(Transaction.amount, String).ilike(pattern, escape="\\"),
            cast(effective_date, String).ilike(pattern, escape="\\")))
    total = db.scalar(select(func.count()).select_from(base.subquery())) or 0
    rows = db.scalars(base.order_by(effective_date.desc(), Transaction.id)
                      .offset(offset).limit(limit)).all()
    projects = {item.id: item.name for item in db.scalars(select(Project).where(
        Project.household_id == home.id)).all()}
    project_total = None
    if project_name:
        expense_query = select(Transaction).join(Account).join(BankConnection).where(
            BankConnection.household_id == home.id, Transaction.status == "BOOK",
            Transaction.economic_type.in_(("consumption", "project_expense")),
            Transaction.amount < 0)
        expense_query = expense_query.where(Transaction.project_id == project.id) if project else \
            expense_query.where(Transaction.project_id.is_(None),
                                Transaction.economic_type == "project_expense")
        expenses = db.scalars(expense_query).all()
        total_pln, missing_fx = 0, 0
        for expense in expenses:
            converted = pln(db, -expense.amount, expense.currency, expense.booking_date)
            if converted is None:
                missing_fx += 1
            else:
                total_pln += converted
        project_total = {"amount_pln": str(total_pln), "transactions": len(expenses),
                         "missing_fx": missing_fx}
    suggestions = {item.transaction_id: item for item in db.scalars(select(DecisionSuggestion).where(
        DecisionSuggestion.transaction_id.in_([tx.id for tx in rows]),
        DecisionSuggestion.status == "SUGGESTED")).all()} if rows else {}
    row_ids = [tx.id for tx in rows]
    pairs = db.scalars(select(TransferPair).where(or_(
        TransferPair.debit_transaction_id.in_(row_ids),
        TransferPair.credit_transaction_id.in_(row_ids)))).all() if row_ids else []
    pair_status = {transaction_id: pair.status for pair in pairs for transaction_id in
                   (pair.debit_transaction_id, pair.credit_transaction_id)}
    return {"total": total, "offset": offset, "project_total": project_total, "rows": [{
        "id": str(tx.id), "date": str(tx.transaction_date or tx.booking_date or tx.value_date or ""),
        "booking_date": str(tx.booking_date) if tx.booking_date else None,
        "bank_status": tx.status, "amount": str(tx.amount),
        "currency": tx.currency, "description": (tx.description or "")[:500],
        "category": (_category_path(categories[tx.category_id], categories)
                     if tx.category_id in categories else None),
        "project": projects.get(tx.project_id), "economic_type": tx.economic_type,
        "pair_status": pair_status.get(tx.id),
        "suggestion": ({"category": _category_path(categories[suggestions[tx.id].category_id], categories),
                        "confidence": str(suggestions[tx.id].confidence),
                        "purchase_probability": str(suggestions[tx.id].purchase_probability),
                        "economic_type": "external_income" if tx.amount > 0 else "consumption"}
                       if tx.id in suggestions and suggestions[tx.id].category_id in categories else None),
    } for tx in rows]}


def _period(payload: dict) -> tuple[int, int] | None:
    month = payload.get("month")
    if month is None:
        return None
    if not isinstance(month, str) or not re.fullmatch(r"\d{4}-(0[1-9]|1[0-2])", month):
        raise FinanceError("Invalid month; expected YYYY-MM")
    year, number = map(int, month.split("-"))
    if year < 1900:
        raise FinanceError("Invalid month; expected YYYY-MM")
    return year, number


def _month_bounds(year: int, month: int) -> tuple[date, date]:
    return date(year, month, 1), date(year + (month == 12), month % 12 + 1, 1)


def _transfers(db: Session) -> dict:
    home = household(db)
    pairs = db.scalars(select(TransferPair).where(TransferPair.household_id == home.id,
                                                   TransferPair.status == "REVIEW")
                       .order_by(TransferPair.created_at.desc()).limit(100)).all()
    rows = []
    for pair in pairs:
        debit = db.get(Transaction, pair.debit_transaction_id)
        credit = db.get(Transaction, pair.credit_transaction_id)
        rows.append({"id": str(pair.id), "debit": {
            "date": str(debit.booking_date), "amount": str(debit.amount),
            "currency": debit.currency, "description": (debit.description or "")[:500]},
            "credit": {"date": str(credit.booking_date), "amount": str(credit.amount),
                       "currency": credit.currency, "description": (credit.description or "")[:500]}})
    return {"rows": rows}


def execute(db: Session, operation: str, payload: dict) -> dict:
    if operation == "overview":
        today = datetime.now(ZoneInfo("Europe/Warsaw")).date()
        year, month = _period(payload) or (today.year, today.month)
        _, end = _month_bounds(year, month)
        as_of = min(today, end - timedelta(days=1))
        latest = db.scalar(select(SyncRun).order_by(SyncRun.started_at.desc()).limit(1))
        return {"month": monthly_report(db, year, month),
                "position": position_report(db, as_of),
                "source_status": {
                    "accounts": db.scalar(select(func.count()).select_from(Account)) or 0,
                    "transactions": db.scalar(select(func.count()).select_from(Transaction)) or 0,
                    "last_sync": latest.status if latest else "NEVER",
                    "ai_checked": db.scalar(select(func.count()).select_from(DecisionSuggestion)) or 0,
                    "ai_applied": db.scalar(select(func.count()).select_from(DecisionSuggestion).where(
                        DecisionSuggestion.status == "APPLIED")) or 0,
                    "manual_corrections": db.scalar(select(func.count()).select_from(ClassificationCorrection).where(
                        ClassificationCorrection.source == "manual")) or 0,
                    "learned_matches": db.scalar(select(func.count()).select_from(ClassificationCorrection).where(
                        ClassificationCorrection.source == "reviewed_rule")) or 0,
                    "mortgages": db.scalar(select(func.count()).select_from(Mortgage)) or 0,
                    "mortgage_allocations": db.scalar(select(func.count()).select_from(MortgageAllocation)) or 0}}
    if operation == "options":
        return _options(db)
    if operation == "review":
        return _review(db, payload)
    if operation == "transfers":
        return _transfers(db)
    if operation == "decide_transfer":
        if set(payload) != {"pair_id", "confirm"} or not isinstance(payload["confirm"], bool):
            raise FinanceError("Invalid transfer decision")
        decide_pair(db, UUID(str(payload["pair_id"])), confirm=payload["confirm"])
        db.commit()
        return {"decided": 1}
    if operation == "manual_pair":
        if set(payload) != {"debit_id", "credit_id"}:
            raise FinanceError("Invalid manual transfer fields")
        confirm_manual_pair(db, UUID(str(payload["debit_id"])), UUID(str(payload["credit_id"])))
        db.commit()
        return {"confirmed": 1}
    if operation == "correct":
        allowed = {"transaction_id", "category", "project", "economic_type"}
        if set(payload) - allowed or "transaction_id" not in payload:
            raise FinanceError("Invalid correction fields")
        count = apply_overrides(db, [payload])
        before = db.scalar(select(func.count()).select_from(ClassificationCorrection).where(
            ClassificationCorrection.source == "reviewed_rule")) or 0
        classify(db)
        after = db.scalar(select(func.count()).select_from(ClassificationCorrection).where(
            ClassificationCorrection.source == "reviewed_rule")) or 0
        db.commit()
        return {"changed": count, "learned": after - before}
    if operation == "correct_mortgage":
        required = {"transaction_id", "category", "project", "economic_type", "mortgage",
                    "principal", "interest", "fees", "replace_existing"}
        if set(payload) != required or payload["economic_type"] not in {
                "mortgage_principal", "mortgage_interest"}:
            raise FinanceError("Invalid mortgage payment fields")
        changed = apply_overrides(db, [{key: payload[key] for key in
                                        ("transaction_id", "category", "project", "economic_type")}])
        allocation = {key: payload[key] for key in
                      ("transaction_id", "mortgage", "principal", "interest", "fees")}
        for part in ("interest", "fees"):
            if allocation[part] == "":
                allocation[part] = "0"
        imported = import_manual(db, {"allocations": [allocation],
                              "replace_existing": payload["replace_existing"]})
        db.commit()
        return {"changed": changed, "imported": imported}
    if operation == "manual":
        counts = import_manual(db, payload)
        db.commit()
        return {"imported": counts}
    if operation == "project":
        if set(payload) != {"name"}:
            raise FinanceError("Invalid project fields")
        add_project(db, payload["name"])
        db.commit()
        return {"saved": 1}
    if operation == "category":
        if set(payload) != {"name", "parent"}:
            raise FinanceError("Invalid category fields")
        name, parent_path = payload["name"], payload["parent"]
        if not isinstance(name, str) or not 1 <= len(name.strip()) <= 120 or "/" in name:
            raise FinanceError("Invalid category name")
        home = household(db)
        parent = category_by_path(db, home.id, parent_path) if parent_path else None
        if parent_path and parent_path.count("/") >= 2:
            raise FinanceError("Category depth limit exceeded")
        exists = db.scalar(select(Category).where(Category.household_id == home.id,
                                                 Category.parent_id == (parent.id if parent else None),
                                                 Category.name == name.strip()))
        if exists is None:
            db.add(Category(household_id=home.id, parent_id=parent.id if parent else None,
                            name=name.strip()))
            db.commit()
        return {"saved": 1}
    if operation == "rule":
        fields = {"pattern", "category", "project", "priority", "direction", "economic_type"}
        if set(payload) != fields:
            raise FinanceError("Invalid rule fields")
        add_rule(db, pattern=payload["pattern"], category_path=payload["category"] or None,
                 project_name=payload["project"] or None, priority=int(payload["priority"]),
                 direction=payload["direction"], economic_type=payload["economic_type"])
        matched, unknown = classify(db)
        db.commit()
        return {"matched": matched, "unclassified": unknown}
    raise FinanceError("Unknown dashboard operation")


@app.post("/api")
def command(request: Request, body: Command) -> dict:
    key = read_private(Path("secrets/dashboard_api_key")).decode().strip()
    supplied = request.headers.get("X-Finance-Key", "")
    if not hmac.compare_digest(supplied, key):
        raise HTTPException(status_code=403, detail="Forbidden")
    if request.headers.get("content-length") and int(request.headers["content-length"]) > 65536:
        raise HTTPException(status_code=413, detail="Too large")
    database_file = (Path("secrets/production_database_url") if body.source == "production"
                     else Path("secrets/database_url"))
    engine = database_engine(database_file)
    try:
        with Session(engine) as db:
            try:
                result = execute(db, body.operation, body.payload)
            except (FinanceError, KeyError, ValueError, TypeError) as exc:
                db.rollback()
                message = str(exc) if isinstance(exc, FinanceError) else "Invalid input"
                raise HTTPException(status_code=400, detail=message) from None
        return result
    finally:
        engine.dispose()


def main() -> None:
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8766, access_log=False, log_level="warning")


if __name__ == "__main__":
    main()
