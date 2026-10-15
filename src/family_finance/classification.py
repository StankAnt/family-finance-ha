"""Local household-wide rules, corrections, and conservative transfer pairing."""

from __future__ import annotations

from collections import defaultdict
from datetime import date
from decimal import Decimal, InvalidOperation
import re
from typing import Any
from uuid import UUID

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from .decision_input import input_hash, prepare_input
from .models import (Account, BankConnection, CashEntry, Category, CategorizationRule,
                     ClassificationCorrection, DecisionSuggestion, Household, Project, Transaction,
                     TransferPair, now)
from .secrets import FinanceError


ECONOMIC_TYPES = {
    "unclassified", "external_income", "consumption", "internal_transfer",
    "investment_transfer", "mortgage_interest", "mortgage_principal",
    "project_expense", "fx_conversion", "external_transfer",
}

CATEGORY_TREE = {
    "Housing": ("Mortgage payment", "Mortgage interest", "Maintenance", "Energy", "Insurance", "Internet"),
    "Income": ("Salary", "Bonus", "Interest", "Gift", "Other"),
    "Food": ("Groceries", "Eating out", "Delivery"),
    "Sports": ("Tennis", "Yoga"),
    "Subscriptions": ("AI", "Apple", "Hosting"),
    "Transport": ("Fuel", "Vehicle", "Transit"),
    "Shopping": (), "Health": (), "Travel": (), "Entertainment": (),
    "Other": ("Uncategorized",),
}
PROJECT_NAMES: tuple[str, ...] = ()
SEED_RULES = (
    (r"\b(?:BIEDRONKA|LIDL)\b", "Food/Groceries"),
    (r"\b(?:OPENAI|ANTHROPIC)\b", "Subscriptions/AI"),
    (r"\bAPPLE\.COM\b", "Subscriptions/Apple"),
    (r"\bCLOUDFLARE\b", "Subscriptions/Hosting"),
)


def household(db: Session) -> Household:
    rows = db.scalars(select(Household).limit(2)).all()
    if len(rows) != 1:
        raise FinanceError("Exactly one household is required")
    return rows[0]


def _category(db: Session, household_id: UUID, name: str,
              parent_id: UUID | None) -> Category:
    query = select(Category).where(Category.household_id == household_id,
                                   Category.name == name)
    query = query.where(Category.parent_id.is_(None) if parent_id is None
                        else Category.parent_id == parent_id)
    category = db.scalar(query)
    if category is None:
        category = Category(household_id=household_id, parent_id=parent_id, name=name)
        db.add(category)
        db.flush()
    return category


def category_by_path(db: Session, household_id: UUID, path: str) -> Category:
    if not isinstance(path, str):
        raise FinanceError("Invalid category path")
    parts = path.split("/")
    if not 1 <= len(parts) <= 3 or any(not part or len(part) > 120 for part in parts):
        raise FinanceError("Invalid category path")
    parent_id = None
    current = None
    for part in parts:
        query = select(Category).where(Category.household_id == household_id,
                                       Category.name == part)
        query = query.where(Category.parent_id.is_(None) if parent_id is None
                            else Category.parent_id == parent_id)
        current = db.scalar(query)
        if current is None:
            raise FinanceError("Unknown category path")
        parent_id = current.id
    return current


def seed(db: Session) -> tuple[int, int, int]:
    home = household(db)
    for parent, children in CATEGORY_TREE.items():
        root = _category(db, home.id, parent, None)
        for child in children:
            _category(db, home.id, child, root.id)
    for name in PROJECT_NAMES:
        if db.scalar(select(Project).where(Project.household_id == home.id,
                                           Project.name == name)) is None:
            db.add(Project(household_id=home.id, name=name))
    db.flush()
    for pattern, category_path in SEED_RULES:
        category = category_by_path(db, home.id, category_path)
        if db.scalar(select(CategorizationRule).where(
                CategorizationRule.household_id == home.id,
                CategorizationRule.pattern == pattern,
                CategorizationRule.category_id == category.id)) is None:
            db.add(CategorizationRule(household_id=home.id, category_id=category.id,
                                      pattern=pattern, priority=100,
                                      match_field="either", direction="debit",
                                      economic_type="consumption"))
    db.flush()
    categories = len(db.scalars(select(Category).where(Category.household_id == home.id)).all())
    projects = len(db.scalars(select(Project).where(Project.household_id == home.id)).all())
    rules = len(db.scalars(select(CategorizationRule).where(
        CategorizationRule.household_id == home.id)).all())
    return categories, projects, rules


def add_project(db: Session, name: str) -> UUID:
    home = household(db)
    if not isinstance(name, str) or not 1 <= len(name.strip()) <= 120:
        raise FinanceError("Invalid project name")
    name = name.strip()
    project = db.scalar(select(Project).where(Project.household_id == home.id,
                                              Project.name == name))
    if project is None:
        project = Project(household_id=home.id, name=name)
        db.add(project)
        db.flush()
    return project.id


def add_rule(db: Session, *, pattern: str, category_path: str | None,
             project_name: str | None = None, priority: int = 100,
             match_field: str = "either", direction: str = "debit",
             account_id: UUID | None = None, min_abs_amount: Decimal | None = None,
             max_abs_amount: Decimal | None = None,
             economic_type: str | None = "consumption") -> UUID:
    home = household(db)
    if (not isinstance(pattern, str) or not 1 <= len(pattern) <= 500 or
            not isinstance(priority, int) or isinstance(priority, bool) or
            not 0 <= priority <= 10000):
        raise FinanceError("Invalid rule pattern or priority")
    if category_path is not None and not isinstance(category_path, str):
        raise FinanceError("Invalid category path")
    if project_name is not None and not isinstance(project_name, str):
        raise FinanceError("Invalid project name")
    try:
        re.compile(pattern)
    except re.error as exc:
        raise FinanceError("Invalid regular expression") from exc
    if match_field not in {"either", "merchant", "description"}:
        raise FinanceError("Invalid rule match field")
    if direction not in {"debit", "credit", "any"}:
        raise FinanceError("Invalid rule direction")
    if economic_type is not None and economic_type not in ECONOMIC_TYPES - {"internal_transfer"}:
        raise FinanceError("Invalid rule economic type")
    try:
        min_abs_amount = Decimal(str(min_abs_amount)) if min_abs_amount is not None else None
        max_abs_amount = Decimal(str(max_abs_amount)) if max_abs_amount is not None else None
    except InvalidOperation as exc:
        raise FinanceError("Invalid rule amount") from exc
    if ((min_abs_amount is not None and not min_abs_amount.is_finite()) or
            (max_abs_amount is not None and not max_abs_amount.is_finite())):
        raise FinanceError("Invalid rule amount")
    if (min_abs_amount is not None and min_abs_amount < 0 or
            max_abs_amount is not None and max_abs_amount < 0 or
            min_abs_amount is not None and max_abs_amount is not None
            and min_abs_amount > max_abs_amount):
        raise FinanceError("Invalid rule amount range")
    category = category_by_path(db, home.id, category_path) if category_path else None
    project = db.scalar(select(Project).where(Project.household_id == home.id,
                                              Project.name == project_name)) if project_name else None
    if project_name and project is None:
        raise FinanceError("Unknown project")
    if account_id:
        try:
            account_id = UUID(str(account_id))
        except (ValueError, TypeError) as exc:
            raise FinanceError("Invalid rule account ID") from exc
        account = db.get(Account, account_id)
        connection = db.get(BankConnection, account.connection_id) if account else None
        if connection is None or connection.household_id != home.id:
            raise FinanceError("Rule account is outside the household")
    rule = CategorizationRule(household_id=home.id, pattern=pattern,
                              category_id=category.id if category else None,
                              project_id=project.id if project else None,
                              priority=priority, match_field=match_field,
                              direction=direction, account_id=account_id,
                              min_abs_amount=min_abs_amount,
                              max_abs_amount=max_abs_amount,
                              economic_type=economic_type)
    db.add(rule)
    db.flush()
    return rule.id


def _matches(rule: CategorizationRule, transaction: Transaction) -> bool:
    if rule.account_id and rule.account_id != transaction.account_id:
        return False
    if rule.direction == "debit" and transaction.amount >= 0:
        return False
    if rule.direction == "credit" and transaction.amount <= 0:
        return False
    amount = abs(transaction.amount)
    if rule.min_abs_amount is not None and amount < rule.min_abs_amount:
        return False
    if rule.max_abs_amount is not None and amount > rule.max_abs_amount:
        return False
    fields = ({"merchant": transaction.counterparty_name or "",
               "description": transaction.description or ""})
    haystack = (fields[rule.match_field] if rule.match_field != "either" else
                fields["merchant"] + "\n" + fields["description"])
    return bool(re.search(rule.pattern, haystack[:2000], flags=re.IGNORECASE))


def classify(db: Session) -> tuple[int, int]:
    home = household(db)
    rules = db.scalars(select(CategorizationRule).where(
        CategorizationRule.household_id == home.id,
        CategorizationRule.enabled.is_(True)).order_by(
            CategorizationRule.priority, CategorizationRule.id)).all()
    confirmed = db.scalars(select(TransferPair).where(
        TransferPair.household_id == home.id, TransferPair.status == "CONFIRMED")).all()
    transferred = {tid for pair in confirmed for tid in
                   (pair.debit_transaction_id, pair.credit_transaction_id)}
    reimbursed = set(db.scalars(select(CashEntry.transaction_id).where(
        CashEntry.household_id == home.id, CashEntry.kind == "reimbursement")).all())
    accounts = db.scalars(select(Account).join(BankConnection).where(
        BankConnection.household_id == home.id)).all()
    own_identifiers = {account.identifier_digest for account in accounts
                       if account.identifier_digest}
    account_identifiers = {account.id: account.identifier_digest for account in accounts}
    suggestions = {item.transaction_id: item for item in db.scalars(
        select(DecisionSuggestion).where(DecisionSuggestion.status == "APPLIED")).all()}
    transactions = db.scalars(select(Transaction).join(Account).join(BankConnection).where(
        BankConnection.household_id == home.id)).all()
    # Reuse only the latest manual label per transaction and only when every
    # reviewed transaction for that payee and direction has the same result.
    reviews = db.execute(select(Transaction, ClassificationCorrection).join(
        ClassificationCorrection, ClassificationCorrection.transaction_id == Transaction.id).join(
        Account, Account.id == Transaction.account_id).join(
        BankConnection, BankConnection.id == Account.connection_id).where(
        BankConnection.household_id == home.id,
        ClassificationCorrection.source == "manual").order_by(
        ClassificationCorrection.applied_at, ClassificationCorrection.id)).all()
    latest_reviews = {previous.id: (previous, correction) for previous, correction in reviews}
    reviewed_by_payee: dict[tuple[int, str], set[tuple[str, UUID | None, UUID | None]]] = defaultdict(set)
    for previous, correction in latest_reviews.values():
        payee = " ".join((previous.counterparty_name or "").casefold().split())
        kind = correction.new_economic_type
        if len(payee) < 4 or previous.amount == 0:
            continue
        reviewed_by_payee[(1 if previous.amount > 0 else -1, payee)].add(
            (kind, correction.new_category_id, correction.new_project_id))
    reviewed_by_payee = {key: next(iter(labels)) for key, labels in reviewed_by_payee.items()
                         if len(labels) == 1 and (
                             (key[0] > 0 and next(iter(labels))[0] == "external_income") or
                             (key[0] < 0 and next(iter(labels))[0] in {"consumption", "project_expense"}))}
    matched = unknown = 0
    for transaction in transactions:
        suggestion = suggestions.get(transaction.id)
        if transaction.override_at is not None or transaction.id in transferred or transaction.id in reimbursed:
            if suggestion is not None:
                suggestion.status = "SUPERSEDED"
            continue
        card_repayment = bool(re.search(
            r"sp[łl]ata (?:zad[łl]u[żz]enia karty kredytowej|nale[żz]no[śs]ci\s*[-–]\s*dzi[eę]kujemy)",
            f"{transaction.description or ''}\n{transaction.counterparty_name or ''}", re.IGNORECASE))
        if (transaction.status == "BOOK" and (
                (transaction.counterparty_identifier_digest in own_identifiers
                 and transaction.counterparty_identifier_digest
                 != account_identifiers.get(transaction.account_id)) or card_repayment)):
            transaction.category_id = None
            transaction.project_id = None
            transaction.economic_type = "internal_transfer"
            if suggestion is not None:
                suggestion.status = "SUPERSEDED"
            continue
        rule = next((item for item in rules if _matches(item, transaction)), None)
        if rule:
            transaction.category_id = rule.category_id
            transaction.project_id = rule.project_id
            transaction.economic_type = rule.economic_type or "unclassified"
            if suggestion is not None:
                suggestion.status = "SUPERSEDED"
            matched += 1
        elif (transaction.status == "BOOK" and transaction.amount != 0
              and (label := reviewed_by_payee.get((
                  1 if transaction.amount > 0 else -1,
                  " ".join((transaction.counterparty_name or "").casefold().split()))))):
            old = (transaction.economic_type, transaction.category_id, transaction.project_id)
            transaction.economic_type, transaction.category_id, transaction.project_id = label
            if old != label:
                db.add(ClassificationCorrection(
                    transaction_id=transaction.id,
                    old_economic_type=old[0], old_category_id=old[1], old_project_id=old[2],
                    new_economic_type=label[0], new_category_id=label[1], new_project_id=label[2],
                    source="reviewed_rule"))
            if suggestion is not None:
                suggestion.status = "SUPERSEDED"
            matched += 1
        elif (suggestion is not None
              and suggestion.category_id is not None
              and suggestion.input_hash == input_hash(prepare_input(transaction))):
            transaction.category_id = suggestion.category_id
            transaction.project_id = None
            transaction.economic_type = "external_income" if transaction.amount > 0 else "consumption"
        else:
            if suggestion is not None:
                suggestion.status = "STALE"
            transaction.category_id = None
            transaction.project_id = None
            transaction.economic_type = "unclassified"
            unknown += 1
    return matched, unknown


def apply_overrides(db: Session, changes: list[dict[str, Any]]) -> int:
    home = household(db)
    if not isinstance(changes, list) or len(changes) > 5000:
        raise FinanceError("Invalid correction document")
    confirmed = db.scalars(select(TransferPair).where(
        TransferPair.household_id == home.id, TransferPair.status == "CONFIRMED")).all()
    transferred = {tid for pair in confirmed for tid in
                   (pair.debit_transaction_id, pair.credit_transaction_id)}
    count = 0
    seen: set[UUID] = set()
    for change in changes:
        if not isinstance(change, dict) or "transaction_id" not in change:
            raise FinanceError("Invalid correction entry")
        try:
            transaction_id = UUID(str(change["transaction_id"]))
        except ValueError as exc:
            raise FinanceError("Invalid internal transaction ID") from exc
        if transaction_id in seen:
            raise FinanceError("Duplicate correction transaction")
        seen.add(transaction_id)
        transaction = db.get(Transaction, transaction_id)
        if transaction is None:
            raise FinanceError("Correction transaction not found")
        if transaction.status != "BOOK":
            raise FinanceError("Only booked transactions can be categorized")
        account = db.get(Account, transaction.account_id)
        connection = db.get(BankConnection, account.connection_id)
        if connection.household_id != home.id or transaction_id in transferred:
            raise FinanceError("Correction requires a household transaction without a confirmed pair")
        old = (transaction.category_id, transaction.project_id, transaction.economic_type)
        if "category" in change:
            value = change["category"]
            if value is not None and not isinstance(value, str):
                raise FinanceError("Invalid correction category")
            transaction.category_id = (category_by_path(db, home.id, value).id
                                       if isinstance(value, str) else None)
        if "project" in change:
            value = change["project"]
            if value is not None and not isinstance(value, str):
                raise FinanceError("Invalid correction project")
            project = db.scalar(select(Project).where(Project.household_id == home.id,
                                                      Project.name == value)) if isinstance(value, str) else None
            if value is not None and project is None:
                raise FinanceError("Unknown project")
            transaction.project_id = project.id if project else None
        if "economic_type" in change:
            value = change["economic_type"]
            if value not in ECONOMIC_TYPES - {"internal_transfer"}:
                raise FinanceError("Invalid manual economic type")
            if value not in {"consumption", "project_expense", "unclassified"} and db.scalar(
                    select(CashEntry.id).where(CashEntry.transaction_id == transaction.id,
                    CashEntry.kind == "reimbursement").limit(1)):
                raise FinanceError("Remove the cash reimbursement before changing this purchase type")
            transaction.economic_type = value
        current = (transaction.category_id, transaction.project_id, transaction.economic_type)
        transaction.override_at = now()
        suggestion = db.scalar(select(DecisionSuggestion).where(
            DecisionSuggestion.transaction_id == transaction.id,
            DecisionSuggestion.status.in_(["APPLIED", "SUGGESTED"])))
        if suggestion is not None:
            suggestion.status = "SUPERSEDED"
        if current != old:
            db.add(ClassificationCorrection(
                transaction_id=transaction.id,
                old_category_id=old[0], new_category_id=current[0],
                old_project_id=old[1], new_project_id=current[1],
                old_economic_type=old[2], new_economic_type=current[2]))
            count += 1
    return count


def _date_of(transaction: Transaction) -> date | None:
    return transaction.booking_date or transaction.value_date or transaction.transaction_date


def pair_transfers(db: Session) -> tuple[int, int]:
    home = household(db)
    accounts = db.scalars(select(Account).join(BankConnection).where(
        BankConnection.household_id == home.id)).all()
    own = {account.id: account for account in accounts}
    existing = db.scalars(select(TransferPair).where(TransferPair.household_id == home.id)).all()
    occupied = {tid for pair in existing for tid in
                (pair.debit_transaction_id, pair.credit_transaction_id)}
    occupied.update(db.scalars(select(CashEntry.transaction_id).where(
        CashEntry.household_id == home.id, CashEntry.kind == "reimbursement")).all())
    transactions = db.scalars(select(Transaction).where(
        Transaction.account_id.in_(own), Transaction.status == "BOOK",
        Transaction.counterparty_identifier_digest.is_not(None),
        Transaction.override_at.is_(None))).all()
    debits = [transaction for transaction in transactions if transaction.amount < 0 and transaction.id not in occupied]
    credits = [transaction for transaction in transactions if transaction.amount > 0 and transaction.id not in occupied]
    candidate_map: dict[UUID, list[Transaction]] = {}
    reverse: defaultdict[UUID, int] = defaultdict(int)
    for debit in debits:
        account = own[debit.account_id]
        debit_date = _date_of(debit)
        if not account.identifier_digest or debit_date is None:
            continue
        candidates = []
        for credit in credits:
            credit_account = own[credit.account_id]
            credit_date = _date_of(credit)
            if (credit.account_id != debit.account_id and credit_date is not None
                    and credit_account.identifier_digest == debit.counterparty_identifier_digest
                    and credit.counterparty_identifier_digest == account.identifier_digest
                    and abs((debit_date - credit_date).days) <= 2):
                candidates.append(credit)
        candidate_map[debit.id] = candidates
        for credit in candidates:
            reverse[credit.id] += 1
    confirmed = review = 0
    for debit in debits:
        candidates = candidate_map.get(debit.id, [])
        if len(candidates) != 1 or reverse[candidates[0].id] != 1:
            continue
        credit = candidates[0]
        exact = debit.currency == credit.currency and -debit.amount == credit.amount
        pair = TransferPair(household_id=home.id, debit_transaction_id=debit.id,
                            credit_transaction_id=credit.id,
                            status="CONFIRMED" if exact else "REVIEW",
                            reason="reciprocal_account_ids",
                            decided_at=now() if exact else None)
        db.add(pair)
        if exact:
            for transaction in (debit, credit):
                transaction.category_id = None
                transaction.project_id = None
                transaction.economic_type = "internal_transfer"
                suggestion = db.scalar(select(DecisionSuggestion).where(
                    DecisionSuggestion.transaction_id == transaction.id,
                    DecisionSuggestion.status == "APPLIED"))
                if suggestion is not None:
                    suggestion.status = "SUPERSEDED"
            confirmed += 1
        else:
            review += 1
    return confirmed, review


def decide_pair(db: Session, pair_id: UUID, *, confirm: bool) -> None:
    home = household(db)
    pair = db.get(TransferPair, pair_id)
    if pair is None or pair.household_id != home.id:
        raise FinanceError("Transfer pair not found")
    if pair.status == ("CONFIRMED" if confirm else "REJECTED"):
        return
    if pair.status == "REJECTED" and confirm:
        raise FinanceError("Rejected transfer pair cannot be confirmed")
    debit = db.get(Transaction, pair.debit_transaction_id)
    credit = db.get(Transaction, pair.credit_transaction_id)
    if confirm:
        if db.scalar(select(CashEntry.id).where(CashEntry.transaction_id.in_([debit.id, credit.id]),
                CashEntry.kind == "reimbursement").limit(1)):
            raise FinanceError("Remove the cash reimbursement before confirming a transfer")
        if debit.override_at is not None or credit.override_at is not None:
            raise FinanceError("Manual overrides must be cleared before confirming transfer")
        pair.status = "CONFIRMED"
        for transaction in (debit, credit):
            transaction.category_id = None
            transaction.project_id = None
            transaction.economic_type = "internal_transfer"
            suggestion = db.scalar(select(DecisionSuggestion).where(
                DecisionSuggestion.transaction_id == transaction.id,
                DecisionSuggestion.status == "APPLIED"))
            if suggestion is not None:
                suggestion.status = "SUPERSEDED"
    else:
        pair.status = "REJECTED"
        for transaction in (debit, credit):
            if transaction.override_at is None and transaction.economic_type == "internal_transfer":
                transaction.economic_type = "unclassified"
    pair.decided_at = now()


def confirm_manual_pair(db: Session, debit_id: UUID, credit_id: UUID) -> None:
    """Confirm an exact own-account transfer selected by an administrator."""
    home = household(db)
    if debit_id == credit_id:
        raise FinanceError("Choose two different transactions")
    debit, credit = db.get(Transaction, debit_id), db.get(Transaction, credit_id)
    if debit is None or credit is None:
        raise FinanceError("Transfer transaction not found")
    if debit.status != "BOOK" or credit.status != "BOOK" or debit.amount >= 0 or credit.amount <= 0:
        raise FinanceError("Choose a booked debit and a booked credit")
    debit_account = db.get(Account, debit.account_id)
    credit_account = db.get(Account, credit.account_id)
    if debit_account.id == credit_account.id:
        raise FinanceError("Own transfer needs two different accounts")
    owners = [db.get(BankConnection, account.connection_id).household_id
              for account in (debit_account, credit_account)]
    if owners != [home.id, home.id]:
        raise FinanceError("Both accounts must belong to the household")
    debit_date, credit_date = _date_of(debit), _date_of(credit)
    if (debit.currency != credit.currency or -debit.amount != credit.amount or
            debit_date is None or credit_date is None or
            abs((debit_date - credit_date).days) > 7):
        raise FinanceError("Transfer amounts, currencies or dates do not match")
    if debit.override_at is not None or credit.override_at is not None:
        raise FinanceError("Manually corrected transactions cannot be paired")
    if db.scalar(select(CashEntry.id).where(CashEntry.transaction_id.in_([debit_id, credit_id]),
            CashEntry.kind == "reimbursement").limit(1)):
        raise FinanceError("Remove the cash reimbursement before pairing a transfer")
    occupied = db.scalar(select(TransferPair.id).where(or_(
        TransferPair.debit_transaction_id.in_([debit_id, credit_id]),
        TransferPair.credit_transaction_id.in_([debit_id, credit_id]))))
    if occupied is not None:
        raise FinanceError("One of the transactions already belongs to a transfer pair")
    pair = TransferPair(household_id=home.id, debit_transaction_id=debit_id,
                        credit_transaction_id=credit_id, status="REVIEW", reason="manual_review")
    db.add(pair)
    db.flush()
    decide_pair(db, pair.id, confirm=True)
