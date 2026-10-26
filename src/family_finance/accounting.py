"""Local PLN reporting. Missing rates or classifications remain explicit gaps."""

from __future__ import annotations

from collections import defaultdict
from datetime import date, datetime, timedelta
from decimal import Decimal, ROUND_HALF_UP
import json
from uuid import UUID
from zoneinfo import ZoneInfo

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from .classification import household
from .models import (Account, AccountBalanceSnapshot, BankConnection, CashEntry, Category, CoverageDeclaration, FxRate, Goal,
                     GoalProgress, ManualRevision, Mortgage, MortgageAllocation, Transaction,
                     ValuationSnapshot, Project, SyncRun, now)
from .secrets import FinanceError
from .purchase_returns import purchase_offset, receivables
from .models import PurchaseLink

CENT = Decimal("0.01")
ZERO = Decimal("0")
VALUATION_KINDS = {"investment", "property", "other_asset", "mortgage_debt", "other_debt"}


def money(value: object, *, positive: bool = False) -> Decimal:
    try:
        result = Decimal(str(value))
    except Exception as exc:
        raise FinanceError("Invalid monetary value") from exc
    if not result.is_finite() or result.as_tuple().exponent < -4 or (positive and result < 0):
        raise FinanceError("Invalid monetary value")
    return result


def currency(value: object) -> str:
    if not isinstance(value, str) or value not in {"PLN", "EUR", "USD"}:
        raise FinanceError("Supported currencies are PLN, EUR and USD")
    return value


def rate(db: Session, code: str, day: date) -> Decimal | None:
    if code == "PLN":
        return Decimal(1)
    row = db.scalar(select(FxRate).where(FxRate.currency == code,
                                       FxRate.source == "NBP_A_MID",
                                       FxRate.effective_date <= day,
                                       FxRate.effective_date >= day - timedelta(days=7))
                    .order_by(FxRate.effective_date.desc()).limit(1))
    return row.pln_per_unit if row else None


def pln(db: Session, amount: Decimal, code: str, day: date) -> Decimal | None:
    fx = rate(db, code, day)
    return (amount * fx).quantize(CENT, rounding=ROUND_HALF_UP) if fx is not None else None


def sync_nbp(db: Session, start: date, end: date, *, client: httpx.Client | None = None) -> int:
    if end < start or end > date.today() or start < date(2002, 1, 2):
        raise FinanceError("Invalid NBP date range")
    own_client = client is None
    client = client or httpx.Client(timeout=15, follow_redirects=False,
                                   headers={"Accept": "application/json"})
    added = 0
    try:
        cursor = max(start - timedelta(days=7), date(2002, 1, 2))
        while cursor <= end:
            last = min(cursor + timedelta(days=89), end)
            for code in ("EUR", "USD"):
                url = (f"https://api.nbp.pl/api/exchangerates/rates/a/{code}/"
                       f"{cursor.isoformat()}/{last.isoformat()}/?format=json")
                try:
                    response = client.get(url)
                    if response.status_code == 404:
                        continue
                    response.raise_for_status()
                    payload = response.json()
                    if payload.get("code") != code or payload.get("table") != "A":
                        raise FinanceError("Unexpected NBP response")
                    rows = payload["rates"]
                    if not isinstance(rows, list):
                        raise FinanceError("Unexpected NBP response")
                    for item in rows:
                        effective = date.fromisoformat(item["effectiveDate"])
                        value = Decimal(str(item["mid"]))
                        if not cursor <= effective <= last or not value.is_finite() or value <= 0:
                            raise FinanceError("Unexpected NBP rate")
                        exists = db.scalar(select(FxRate.id).where(
                            FxRate.currency == code, FxRate.effective_date == effective,
                            FxRate.source == "NBP_A_MID"))
                        if exists is None:
                            db.add(FxRate(currency=code, effective_date=effective,
                                          pln_per_unit=value, source="NBP_A_MID"))
                            added += 1
                except (httpx.HTTPError, ValueError, KeyError, TypeError, ArithmeticError) as exc:
                    raise FinanceError("NBP rate sync failed; no partial rates committed") from exc
            cursor = last + timedelta(days=1)
        return added
    finally:
        if own_client:
            client.close()


def import_manual(db: Session, payload: dict) -> dict[str, int]:
    """Import user-supplied allocations, valuations and goals in one transaction."""
    home = household(db)
    counts = defaultdict(int)
    if set(payload) - {"mortgages", "allocations", "valuations", "goals", "goal_progress", "coverage", "account_balances", "replace_existing"}:
        raise FinanceError("Unknown manual import section")
    replace_existing = payload.get("replace_existing", False)
    if not isinstance(replace_existing, bool):
        raise FinanceError("replace_existing must be boolean")

    def replace(record, values: dict, entity_kind: str) -> None:
        previous = {key: getattr(record, key) for key in values}
        if previous == values:
            return
        if not replace_existing:
            raise FinanceError("Existing manual record differs; select explicit correction")
        db.add(ManualRevision(household_id=home.id, entity_kind=entity_kind,
                              record_id=record.id,
                              previous_value=json.dumps(previous, default=str, sort_keys=True),
                              new_value=json.dumps(values, default=str, sort_keys=True)))
        for key, value in values.items():
            setattr(record, key, value)
        counts["corrected"] += 1
    for raw in payload.get("account_balances", []):
        if set(raw) != {"account_id", "as_of", "amount"}:
            raise FinanceError("Invalid account balance fields")
        account = db.get(Account, UUID(str(raw["account_id"])))
        if account is None or db.scalar(select(BankConnection.household_id).where(
                BankConnection.id == account.connection_id)) != home.id:
            raise FinanceError("Unknown household account")
        day = date.fromisoformat(raw["as_of"])
        if day > datetime.now(ZoneInfo("Europe/Warsaw")).date():
            raise FinanceError("Account balance date cannot be in the future")
        amount = money(raw["amount"])
        existing = db.scalar(select(AccountBalanceSnapshot).join(SyncRun).where(
            AccountBalanceSnapshot.account_id == account.id,
            AccountBalanceSnapshot.reference_date == day,
            AccountBalanceSnapshot.balance_type == "CLBD",
            SyncRun.source == "manual"))
        if existing is None:
            run = SyncRun(connection_id=account.connection_id, source="manual",
                          status="SUCCESS", finished_at=now(), account_count=1)
            db.add(run)
            db.flush()
            db.add(AccountBalanceSnapshot(account_id=account.id, sync_run_id=run.id,
                                          balance_type="CLBD", reference_date=day,
                                          amount=amount, currency=account.currency))
            counts["account_balances"] += 1
        else:
            replace(existing, {"amount": amount}, "account_balance")
    for raw in payload.get("mortgages", []):
        name, code = str(raw["name"]), currency(raw["currency"])
        if not 1 <= len(name) <= 120:
            raise FinanceError("Invalid mortgage name")
        obj = db.scalar(select(Mortgage).where(Mortgage.household_id == home.id, Mortgage.name == name))
        if obj is None:
            db.add(Mortgage(household_id=home.id, name=name, currency=code))
            counts["mortgages"] += 1
        elif obj.currency != code:
            raise FinanceError("Mortgage currency cannot change")
    db.flush()
    for raw in payload.get("allocations", []):
        tx = db.get(Transaction, UUID(str(raw["transaction_id"])))
        mortgage = db.scalar(select(Mortgage).where(Mortgage.household_id == home.id,
                                                   Mortgage.name == raw["mortgage"]))
        if tx is None or mortgage is None or tx.status != "BOOK" or tx.amount >= 0:
            raise FinanceError("Allocation needs a booked debit and known mortgage")
        if tx.economic_type not in {"mortgage_principal", "mortgage_interest"}:
            raise FinanceError("Select and save a mortgage type before splitting the payment")
        owner = db.scalar(select(BankConnection.household_id).join(Account).where(Account.id == tx.account_id))
        if owner != home.id or tx.currency != mortgage.currency:
            raise FinanceError("Allocation account or currency mismatch")
        principal = money(raw["principal"], positive=True)
        interest = money(raw["interest"], positive=True)
        fees = money(raw["fees"], positive=True)
        if principal + interest + fees != -tx.amount:
            raise FinanceError("Mortgage allocation does not reconcile to bank debit")
        existing = db.scalar(select(MortgageAllocation).where(MortgageAllocation.transaction_id == tx.id))
        if existing is None:
            db.add(MortgageAllocation(mortgage_id=mortgage.id, transaction_id=tx.id,
                                      principal=principal, interest=interest, fees=fees))
            counts["allocations"] += 1
        else:
            replace(existing, {"mortgage_id": mortgage.id, "principal": principal,
                               "interest": interest, "fees": fees}, "mortgage_allocation")
    for raw in payload.get("valuations", []):
        kind, name, day = str(raw["kind"]), str(raw["name"]), date.fromisoformat(raw["as_of"])
        if kind not in VALUATION_KINDS or not 1 <= len(name) <= 120:
            raise FinanceError("Invalid valuation")
        amount, code = money(raw["amount"], positive=True), currency(raw["currency"])
        existing = db.scalar(select(ValuationSnapshot).where(
            ValuationSnapshot.household_id == home.id, ValuationSnapshot.kind == kind,
            ValuationSnapshot.name == name, ValuationSnapshot.as_of == day))
        if existing is None:
            db.add(ValuationSnapshot(household_id=home.id, kind=kind, name=name, as_of=day,
                                     amount=amount, currency=code, estimated=bool(raw.get("estimated", False))))
            counts["valuations"] += 1
        else:
            replace(existing, {"amount": amount, "currency": code,
                               "estimated": bool(raw.get("estimated", False))}, "valuation")
    for raw in payload.get("goals", []):
        name = str(raw["name"])
        if not 1 <= len(name) <= 120:
            raise FinanceError("Invalid goal name")
        amount, code = money(raw["target_amount"], positive=True), currency(raw["currency"])
        if amount == 0:
            raise FinanceError("Goal target must be positive")
        deadline = date.fromisoformat(raw["target_date"]) if raw.get("target_date") else None
        existing = db.scalar(select(Goal).where(Goal.household_id == home.id, Goal.name == name))
        if existing is None:
            db.add(Goal(household_id=home.id, name=name, target_amount=amount,
                        currency=code, target_date=deadline))
            counts["goals"] += 1
        else:
            replace(existing, {"target_amount": amount, "currency": code,
                               "target_date": deadline}, "goal")
    db.flush()
    for raw in payload.get("goal_progress", []):
        goal = db.scalar(select(Goal).where(Goal.household_id == home.id, Goal.name == raw["goal"]))
        if goal is None:
            raise FinanceError("Unknown goal for progress")
        day, amount = date.fromisoformat(raw["as_of"]), money(raw["amount"], positive=True)
        existing = db.scalar(select(GoalProgress).where(GoalProgress.goal_id == goal.id,
                                                      GoalProgress.as_of == day))
        if existing is None:
            db.add(GoalProgress(goal_id=goal.id, as_of=day, amount=amount,
                                estimated=bool(raw.get("estimated", False))))
            counts["goal_progress"] += 1
        else:
            replace(existing, {"amount": amount,
                               "estimated": bool(raw.get("estimated", False))}, "goal_progress")
    for raw in payload.get("coverage", []):
        day = date.fromisoformat(raw["as_of"])
        flags = tuple(raw[key] for key in ("accounts_complete", "assets_complete", "liabilities_complete"))
        if not all(isinstance(flag, bool) for flag in flags):
            raise FinanceError("Coverage values must be booleans")
        existing = db.scalar(select(CoverageDeclaration).where(
            CoverageDeclaration.household_id == home.id, CoverageDeclaration.as_of == day))
        if existing is None:
            db.add(CoverageDeclaration(household_id=home.id, as_of=day,
                                       accounts_complete=flags[0], assets_complete=flags[1],
                                       liabilities_complete=flags[2]))
            counts["coverage"] += 1
        else:
            replace(existing, {"accounts_complete": flags[0], "assets_complete": flags[1],
                               "liabilities_complete": flags[2]}, "coverage")
    return dict(counts)


def monthly_report(db: Session, year: int, month: int) -> dict:
    home = household(db)
    start = date(year, month, 1)
    end = date(year + (month == 12), month % 12 + 1, 1)
    rows = db.scalars(select(Transaction).join(Account).join(BankConnection).where(
        BankConnection.household_id == home.id, Transaction.status == "BOOK",
        Transaction.booking_date >= start, Transaction.booking_date < end)).all()
    allocations = {a.transaction_id: a for a in db.scalars(select(MortgageAllocation).where(
        MortgageAllocation.transaction_id.in_([tx.id for tx in rows]))).all()} if rows else {}
    reimbursements = defaultdict(lambda: ZERO)
    missing_cash_fx_ids = set()
    if rows:
        for receipt in db.scalars(select(CashEntry).where(
                CashEntry.household_id == home.id, CashEntry.kind == "reimbursement",
                CashEntry.transaction_id.in_([tx.id for tx in rows]))):
            converted = pln(db, receipt.amount, receipt.currency, receipt.occurred_on)
            if converted is None:
                missing_cash_fx_ids.add(receipt.id)
            else:
                reimbursements[receipt.transaction_id] += converted
    categories = {item.id: item for item in db.scalars(select(Category).where(
        Category.household_id == home.id)).all()}
    expense_offsets = {}
    for tx in rows:
        if tx.amount < 0 and tx.economic_type in {"consumption", "project_expense", "unclassified"}:
            offset = purchase_offset(db, tx)
            if offset is None:
                missing_cash_fx_ids.add(tx.id)
            expense_offsets[tx.id] = offset or ZERO
    linked_credit_ids = set(db.scalars(select(PurchaseLink.credit_id)))
    projects = {item.id: item.name for item in db.scalars(select(Project).where(
        Project.household_id == home.id)).all()}
    sums = defaultdict(lambda: ZERO)
    category_sums = defaultdict(lambda: ZERO)
    income_category_sums = defaultdict(lambda: ZERO)
    project_sums = defaultdict(lambda: ZERO)
    category_by_type = defaultdict(lambda: defaultdict(lambda: ZERO))
    category_by_project_type = defaultdict(lambda: defaultdict(lambda: defaultdict(lambda: ZERO)))
    counts = defaultdict(int)
    original = defaultdict(lambda: ZERO)
    for tx in rows:
        counts["booked"] += 1
        if tx.economic_type == "internal_transfer" and tx.id not in allocations:
            counts["internal_transfer"] += 1
            continue
        original[tx.currency] += tx.amount
        amount_pln = pln(db, tx.amount, tx.currency, tx.booking_date)
        if amount_pln is None:
            counts["missing_fx"] += 1
            continue
        sums["cashflow"] += amount_pln
        if tx.id in linked_credit_ids:
            counts["linked_returns"] += 1
            sums["bank_returns_received"] += amount_pln
            continue
        allocation = allocations.get(tx.id)
        if tx.amount < 0 and tx.economic_type in {"consumption", "project_expense", "unclassified"}:
            sums["purchase_cost_adjustments"] += min(-amount_pln, expense_offsets.get(tx.id, ZERO))
        if amount_pln < 0 and tx.economic_type != "fx_conversion":
            sums["outflows_total"] -= amount_pln
        if allocation:
            sums["outflows_mortgage"] -= amount_pln
            for key, value in (("mortgage_principal", allocation.principal),
                               ("mortgage_interest", allocation.interest),
                               ("mortgage_fees", allocation.fees)):
                converted = pln(db, value, tx.currency, tx.booking_date)
                sums[key] += converted
                if key == "mortgage_principal":
                    sums["mortgage_principal_confirmed"] += converted
                if key in {"mortgage_interest", "mortgage_fees"}:
                    category_by_type[key]["Housing/Mortgage interest" if key == "mortgage_interest"
                                          else "Housing/Mortgage fees"] += converted
            counts["mortgage_allocated"] += 1
            continue
        kind = tx.economic_type
        if kind == "unclassified":
            counts["unclassified"] += 1
            sums["unclassified_net"] += amount_pln
            if amount_pln < 0:
                counts["unclassified_debits"] += 1
                spend = max(-amount_pln - expense_offsets.get(tx.id, ZERO), ZERO)
                sums["unclassified_spending"] += spend
                category_sums["Other/Unclassified"] += spend
                category_by_type[kind]["Other/Unclassified"] += spend
            elif amount_pln > 0:
                counts["unclassified_credits"] += 1
                sums["unclassified_receipts"] += amount_pln
        elif kind in {"mortgage_principal", "mortgage_interest"}:
            sums["outflows_mortgage"] -= amount_pln
            sums[kind] -= amount_pln
            if kind == "mortgage_interest":
                category_by_type[kind]["Housing/Mortgage interest"] -= amount_pln
            counts["mortgage_single_purpose"] += 1
            counts["mortgage_unallocated"] += 1
        elif kind == "external_income":
            sums["external_income"] += amount_pln
            income_path = "Other/Uncategorized"
            if tx.category_id in categories:
                category = categories[tx.category_id]
                parent = categories.get(category.parent_id)
                path = f"{parent.name}/{category.name}" if parent else category.name
                income_category_sums[path] += amount_pln
                income_path = path
            category_by_type[kind][income_path] += amount_pln
        elif kind in {"consumption", "project_expense"}:
            spend = max(-amount_pln - expense_offsets.get(tx.id, ZERO), ZERO)
            sums["spending"] += spend
            spend_path = "Other/Uncategorized"
            if tx.category_id in categories:
                category = categories[tx.category_id]
                parent = categories.get(category.parent_id)
                path = f"{parent.name}/{category.name}" if parent else category.name
                category_sums[path] += spend
                spend_path = path
            category_by_type[kind][spend_path] += spend
            if tx.project_id in projects:
                project_name = projects[tx.project_id]
                project_sums[project_name] += spend
                category_by_project_type[project_name][kind][spend_path] += spend
            elif kind == "project_expense":
                project_sums["Без проекта"] += spend
                category_by_project_type["Без проекта"][kind][spend_path] += spend
            if tx.project_id is None and kind == "consumption":
                sums["baseline_living"] += spend
            else:
                sums["exceptional_projects"] += spend
        elif kind == "investment_transfer":
            sums["investment_cashflow"] += amount_pln
            sums["investment_contributions"] += max(-amount_pln, ZERO)
            sums["investment_returns"] += max(amount_pln, ZERO)
            sums["outflows_investments"] += max(-amount_pln, ZERO)
        elif kind == "fx_conversion":
            sums["fx_conversion_cashflow"] += amount_pln
        else:
            sums["other_cashflow"] += amount_pln
            if amount_pln < 0:
                category_by_type["other_external_outflow"]["Other/External transfer"] -= amount_pln
    # Cash expenses are new household purchases. Cash reimbursements already reduce
    # the linked bank purchase above, so they must not become external income.
    for entry in db.scalars(select(CashEntry).where(CashEntry.household_id == home.id,
            CashEntry.kind == "expense", CashEntry.occurred_on >= start,
            CashEntry.occurred_on < end)):
        spend = pln(db, -entry.amount, entry.currency, entry.occurred_on)
        if spend is None:
            missing_cash_fx_ids.add(entry.id)
            continue
        sums["spending"] += spend
        sums["cash_spending"] += spend
        sums["outflows_total"] += spend
        sums["cashflow"] -= spend
        category = categories.get(entry.category_id)
        parent = categories.get(category.parent_id) if category else None
        path = f"{parent.name}/{category.name}" if parent else category.name if category else "Other/Uncategorized"
        category_sums[path] += spend
        kind = "project_expense" if entry.project_id else "consumption"
        category_by_type[kind][path] += spend
        if entry.project_id in projects:
            name = projects[entry.project_id]
            project_sums[name] += spend
            category_by_project_type[name][kind][path] += spend
            sums["exceptional_projects"] += spend
        else:
            sums["baseline_living"] += spend
    for receipt in db.scalars(select(CashEntry).where(
            CashEntry.household_id == home.id, CashEntry.kind == "reimbursement",
            CashEntry.affects_wallet.is_(True),
            CashEntry.occurred_on >= start, CashEntry.occurred_on < end)):
        converted = pln(db, receipt.amount, receipt.currency, receipt.occurred_on)
        if converted is None:
            missing_cash_fx_ids.add(receipt.id)
        else:
            sums["cashflow"] += converted
    if missing_cash_fx_ids:
        counts["cash_missing_fx"] = len(missing_cash_fx_ids)
        counts["missing_fx"] += len(missing_cash_fx_ids)
    sums["outflows_without_mortgage_investments"] = (
        sums["outflows_total"] - sums["outflows_mortgage"] - sums["outflows_investments"])
    sums["outflows_total"] += ZERO
    sums["outflows_mortgage"] += ZERO
    sums["outflows_investments"] += ZERO
    sums["living_cost_with_interest"] = sums["baseline_living"] + sums["mortgage_interest"] + sums["mortgage_fees"]
    sums["total_expense_with_interest"] = sums["spending"] + sums["mortgage_interest"] + sums["mortgage_fees"]
    sums["personal_spending_after_returns"] = sums["spending"] + sums["unclassified_spending"]
    sums["provisional_expense_with_interest"] = sums["total_expense_with_interest"] + sums["unclassified_spending"]
    sums["unclassified_spending"] += ZERO
    sums["unclassified_receipts"] += ZERO
    sums["investment_contributions"] += ZERO
    sums["investment_returns"] += ZERO
    sums["mortgage_principal_confirmed"] += ZERO
    sums["cash_spending"] += ZERO
    sums["cash_reimbursements"] = sum(reimbursements.values(), ZERO)
    return {
        "period": f"{year:04d}-{month:02d}", "currency": "PLN",
        "fx_source": "NBP table A mid; latest published on/before booking date, max 7 days",
        "amounts_pln": {key: str(value.quantize(CENT)) for key, value in sorted(sums.items())},
        "external_original_net_by_currency": {key: str(value) for key, value in sorted(original.items())},
        "spending_by_category_pln": {key: str(value.quantize(CENT)) for key, value in sorted(category_sums.items())},
        "income_by_category_pln": {key: str(value.quantize(CENT)) for key, value in sorted(income_category_sums.items())},
        "spending_by_project_pln": {key: str(value.quantize(CENT)) for key, value in sorted(project_sums.items())},
        "category_by_type_pln": {kind: {key: str(value.quantize(CENT))
                                         for key, value in sorted(values.items())}
                                 for kind, values in sorted(category_by_type.items())},
        "category_by_project_type_pln": {
            project: {kind: {key: str(value.quantize(CENT)) for key, value in sorted(values.items())}
                      for kind, values in sorted(by_type.items())}
            for project, by_type in sorted(category_by_project_type.items())},
        "counts": dict(sorted(counts.items())),
        "cashflow_complete": counts["missing_fx"] == 0 and counts["unclassified"] == 0,
        "living_cost_complete": (counts["missing_fx"] == 0 and counts["unclassified"] == 0
                                 and counts["mortgage_unallocated"] == 0),
        "notes": ["Cashflow excludes recognized own-account transfers but includes unknown external movements.",
                  "Unclassified rows may include additional own-account transfers; totals are provisional until reviewed.",
                  "Investment transfers and mortgage principal reduce cash but are not living costs.",
                  "FX conversion cashflow is shown separately; valuation changes are not income."],
    }


def position_report(db: Session, day: date) -> dict:
    home = household(db)
    accounts = db.scalars(select(Account).join(BankConnection).where(
        BankConnection.household_id == home.id, Account.active.is_(True))).all()
    parts = defaultdict(lambda: ZERO)
    gaps = []
    stale = []
    account_rows = []
    calculated_balances = 0
    for account in accounts:
        all_snapshots = db.scalars(select(AccountBalanceSnapshot).where(
            AccountBalanceSnapshot.account_id == account.id)).all()
        future_dates = [(row.reference_date or row.observed_at.date()) for row in all_snapshots
                        if (row.reference_date or row.observed_at.date()) > day]
        snapshots = [row for row in all_snapshots if
                     (row.reference_date or row.observed_at.date()) <= day]
        snapshots.sort(key=lambda row: (row.reference_date or row.observed_at.date(),
                                        row.observed_at), reverse=True)
        snapshot = next((row for row in snapshots if row.balance_type in {"CLBD", "ITBD"}), None)
        available = next((row for row in snapshots if row.balance_type == "ITAV"), None)
        calculated = False
        basis_date = None
        booked = snapshot.amount if snapshot else None
        if snapshot is None:
            # The AIS balances endpoint has no as-of date. For a recent past day,
            # reverse the booked movements already present when the first later
            # bank balance was saved. This is an estimate: late postings and
            # incomplete bank history can change the result.
            future = sorted((row for row in all_snapshots
                             if row.balance_type in {"CLBD", "ITBD"}
                             and row.observed_at.date() > day
                             and (row.observed_at.date() - day).days <= 30
                             and db.get(SyncRun, row.sync_run_id).source == "ais"),
                            key=lambda row: row.observed_at)
            if future:
                anchor = future[0]
                movements = db.scalars(select(Transaction.amount).where(
                    Transaction.account_id == account.id,
                    Transaction.status == "BOOK",
                    Transaction.booking_date > day,
                    Transaction.booking_date <= anchor.observed_at.date(),
                    Transaction.imported_at <= anchor.observed_at)).all()
                booked = anchor.amount - sum(movements, ZERO)
                calculated = True
                basis_date = anchor.observed_at.date()
                calculated_balances += 1
        account_rows.append({"name": account.name or "Счёт без названия",
                             "currency": account.currency,
                             "booked": str(booked) if booked is not None else None,
                             "available": str(available.amount) if available and not calculated else None,
                             "as_of": str(day if calculated else (snapshot.reference_date or snapshot.observed_at.date())) if booked is not None else None,
                             "balance_source": "calculated" if calculated else db.get(SyncRun, snapshot.sync_run_id).source if snapshot else None,
                             "balance_basis_date": str(basis_date) if basis_date else None,
                             "next_balance_date": str(min(future_dates)) if future_dates else None})
        if booked is None:
            gaps.append("account_balance")
            continue
        value = pln(db, booked, account.currency, day)
        if value is None:
            gaps.append("account_fx")
            continue
        parts["bank_cash"] += value
        if snapshot and (day - (snapshot.reference_date or snapshot.observed_at.date())).days > 7:
            stale.append("account_balance")
    if calculated_balances:
        gaps.append("account_balance_estimated")
    valuations = db.scalars(select(ValuationSnapshot).where(
        ValuationSnapshot.household_id == home.id, ValuationSnapshot.as_of <= day)
        .order_by(ValuationSnapshot.as_of.desc())).all()
    seen = set()
    estimate_count = 0
    latest_mortgage_snapshots = {}
    mortgage_debts = []
    mortgages_by_name = {row.name: row for row in db.scalars(select(Mortgage).where(
        Mortgage.household_id == home.id))}
    for snapshot in valuations:
        identity = (snapshot.kind, snapshot.name)
        if identity in seen:
            continue
        seen.add(identity)
        amount = snapshot.amount
        principal_since_snapshot = ZERO
        calculated_debt = False
        if snapshot.kind == "mortgage_debt":
            latest_mortgage_snapshots[snapshot.name] = snapshot
            mortgage = mortgages_by_name.get(snapshot.name)
            if mortgage and mortgage.currency == snapshot.currency:
                principal_since_snapshot = sum(db.scalars(select(MortgageAllocation.principal)
                    .join(Transaction).where(MortgageAllocation.mortgage_id == mortgage.id,
                        Transaction.status == "BOOK", Transaction.booking_date > snapshot.as_of,
                        Transaction.booking_date <= day)), ZERO)
                calculated_debt = principal_since_snapshot > 0
                amount -= principal_since_snapshot
                if amount < 0:
                    gaps.append("mortgage_debt_overpaid")
                    amount = ZERO
            mortgage_debts.append({"name": snapshot.name, "amount": str(amount),
                "currency": snapshot.currency, "as_of": str(day if calculated_debt else snapshot.as_of),
                "basis_date": str(snapshot.as_of),
                "principal_since_snapshot": str(principal_since_snapshot),
                "calculated": calculated_debt})
        value = pln(db, amount, snapshot.currency, day)
        if value is None:
            gaps.append("valuation_fx")
            continue
        parts[snapshot.kind] += value
        estimate_count += int(snapshot.estimated or calculated_debt)
        if (day - snapshot.as_of).days > 90:
            stale.append(snapshot.kind)
    required = {"investment", "property"}
    if db.scalar(select(Mortgage.id).where(Mortgage.household_id == home.id).limit(1)):
        required.add("mortgage_debt")
    for kind in required - {kind for kind, _ in seen}:
        gaps.append(kind)
    cash_by_currency = defaultdict(lambda: ZERO)
    for entry in db.scalars(select(CashEntry).where(
            CashEntry.household_id == home.id, CashEntry.occurred_on <= day, CashEntry.affects_wallet.is_(True))):
        cash_by_currency[entry.currency] += entry.amount
    for code, amount in cash_by_currency.items():
        value = pln(db, amount, code, day)
        if value is None and amount:
            gaps.append("cash_fx")
        else:
            parts["cash_on_hand"] += value or ZERO
    owed = receivables(db, day)
    if owed["amount_pln"] is None:
        gaps.append("receivables_fx")
    parts["receivables"] = Decimal(owed["amount_pln"] or "0")
    assets = parts["bank_cash"] + parts["cash_on_hand"] + parts["receivables"] + parts["investment"] + parts["property"] + parts["other_asset"]
    debts = parts["mortgage_debt"] + parts["other_debt"]
    goals = []
    for goal in db.scalars(select(Goal).where(Goal.household_id == home.id, Goal.active.is_(True))):
        progress = db.scalar(select(GoalProgress).where(GoalProgress.goal_id == goal.id,
                                                     GoalProgress.as_of <= day)
                             .order_by(GoalProgress.as_of.desc()).limit(1))
        goals.append({"name": goal.name, "target": str(goal.target_amount),
                      "currency": goal.currency, "target_date": str(goal.target_date) if goal.target_date else None,
                      "progress": str(progress.amount) if progress else None,
                      "progress_as_of": str(progress.as_of) if progress else None,
                      "progress_estimated": progress.estimated if progress else None})
    declaration = db.scalar(select(CoverageDeclaration).where(
        CoverageDeclaration.household_id == home.id, CoverageDeclaration.as_of <= day)
        .order_by(CoverageDeclaration.as_of.desc()).limit(1))
    complete = bool(declaration and declaration.accounts_complete and
                    declaration.assets_complete and declaration.liabilities_complete and not gaps)
    reconciliation = []
    for name, current in latest_mortgage_snapshots.items():
        mortgage = db.scalar(select(Mortgage).where(Mortgage.household_id == home.id,
                                                   Mortgage.name == name))
        previous = db.scalar(select(ValuationSnapshot).where(
            ValuationSnapshot.household_id == home.id,
            ValuationSnapshot.kind == "mortgage_debt", ValuationSnapshot.name == name,
            ValuationSnapshot.as_of < current.as_of).order_by(ValuationSnapshot.as_of.desc()).limit(1))
        if previous is None or mortgage is None or (previous.currency, current.currency) != (
                mortgage.currency, mortgage.currency):
            continue
        principal = sum((row[0] for row in db.execute(
            select(MortgageAllocation.principal).join(Transaction).where(
                MortgageAllocation.mortgage_id == mortgage.id,
                Transaction.booking_date > previous.as_of,
                Transaction.booking_date <= current.as_of)).all()), ZERO)
        difference = current.amount - (previous.amount - principal)
        reconciliation.append({"mortgage": name, "from": str(previous.as_of),
                               "to": str(current.as_of), "currency": current.currency,
                               "allocated_principal": str(principal),
                               "unexplained_balance_change": str(difference),
                               "reconciled": difference == 0})
    return {"as_of": str(day), "currency": "PLN",
            "components_pln": {key: str(value.quantize(CENT)) for key, value in sorted(parts.items())},
            "liquid_savings_pln": str(parts["bank_cash"].quantize(CENT)) if "account_balance" not in gaps and "account_fx" not in gaps else None,
            "money_total_pln": str((parts["bank_cash"] + parts["cash_on_hand"]).quantize(CENT))
                if not {"account_balance", "account_fx", "cash_fx"}.intersection(gaps) else None,
            "cash_on_hand_pln": str(parts["cash_on_hand"].quantize(CENT)) if "cash_fx" not in gaps else None,
            "cash_on_hand_by_currency": {code: str(amount.quantize(CENT))
                                         for code, amount in sorted(cash_by_currency.items())},
            "receivables": owed,
            "net_worth_pln": str((assets - debts).quantize(CENT)) if complete else None,
            "partial_net_worth_pln": str((assets - debts).quantize(CENT)),
            "complete": complete, "coverage_confirmed_as_of": str(declaration.as_of) if declaration else None,
            "coverage_flags": ({"accounts": declaration.accounts_complete,
                                "assets": declaration.assets_complete,
                                "liabilities": declaration.liabilities_complete} if declaration else None),
            "missing_components": sorted(set(gaps)),
            "stale_components": sorted(set(stale)), "estimated_component_count": estimate_count + calculated_balances,
            "goals": goals, "accounts": account_rows,
            "mortgage_debts": mortgage_debts,
            "mortgage_reconciliation": reconciliation,
            "notes": ["Manual investment/property values exclude transfers already counted as bank cash.",
                      "Partial net worth omits missing components; do not use it as total net worth."]}
