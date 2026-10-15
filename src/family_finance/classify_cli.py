"""Local classification and opt-in Decisions suggestions; private review stays on disk."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .ai_decisions import DecisionsClient, apply_saved, suggest
from .classification import (add_project, add_rule, apply_overrides, classify, decide_pair,
                             household, pair_transfers, seed)
from .decision_input import input_hash, prepare_input
from .models import Account, BankConnection, Category, DecisionSuggestion, Transaction, TransferPair
from .secrets import FinanceError, read_private, write_private
from .sync import database_engine


def _review_export(db: Session, destination: Path) -> tuple[int, int, int]:
    home = household(db)
    rows = db.execute(select(Transaction, Account).join(Account).join(BankConnection).where(
        BankConnection.household_id == home.id,
        Transaction.economic_type == "unclassified").order_by(
            Transaction.booking_date.desc()).limit(5000)).all()
    pairs = db.scalars(select(TransferPair).where(
        TransferPair.household_id == home.id, TransferPair.status == "REVIEW")).all()
    applied_rows = db.execute(select(Transaction, DecisionSuggestion).join(
        DecisionSuggestion, DecisionSuggestion.transaction_id == Transaction.id
    ).join(Account).join(BankConnection).where(
        BankConnection.household_id == home.id,
        DecisionSuggestion.status == "APPLIED").order_by(
            DecisionSuggestion.applied_at.desc()).limit(5000)).all()
    suggestions = {row.transaction_id: row for row in db.scalars(
        select(DecisionSuggestion).where(DecisionSuggestion.transaction_id.in_(
            [tx.id for tx, _ in rows]))).all()}
    suggestions = {tx.id: suggestions[tx.id] for tx, _ in rows
                   if tx.id in suggestions and suggestions[tx.id].status in
                   {"SUGGESTED", "UNKNOWN"} and
                   suggestions[tx.id].input_hash == input_hash(prepare_input(tx))}
    categories = {category.id: category for category in db.scalars(select(Category).where(
        Category.household_id == home.id)).all()}

    def category_path(category_id):
        category = categories.get(category_id)
        if category is None:
            return None
        parent = categories.get(category.parent_id)
        return f"{parent.name}/{category.name}" if parent else category.name

    transactions = [{
        "transaction_id": str(tx.id), "date": str(tx.booking_date or tx.value_date or ""),
        "amount": str(tx.amount), "currency": tx.currency,
        "description": tx.description, "counterparty_name": tx.counterparty_name,
        "account_id": str(account.id),
        "ai_suggestion": ({"category": category_path(suggestions[tx.id].category_id),
                           "confidence": (str(suggestions[tx.id].confidence)
                                          if suggestions[tx.id].confidence is not None else None),
                           "purchase_probability": (
                               str(suggestions[tx.id].purchase_probability)
                               if suggestions[tx.id].purchase_probability is not None else None),
                           "status": suggestions[tx.id].status}
                          if tx.id in suggestions else None),
        "suggested_correction": {"transaction_id": str(tx.id),
                                 "category": category_path(suggestions[tx.id].category_id)
                                 if tx.id in suggestions else None,
                                 "project": None,
                                 "economic_type": ("consumption" if tx.id in suggestions and
                                                   suggestions[tx.id].category_id else "unclassified")},
    } for tx, account in rows]
    transfer_pairs = []
    for pair in pairs:
        debit = db.get(Transaction, pair.debit_transaction_id)
        credit = db.get(Transaction, pair.credit_transaction_id)
        transfer_pairs.append({
            "pair_id": str(pair.id),
            "debit": {"date": str(debit.booking_date or ""), "amount": str(debit.amount),
                      "currency": debit.currency, "description": debit.description},
            "credit": {"date": str(credit.booking_date or ""), "amount": str(credit.amount),
                       "currency": credit.currency, "description": credit.description},
        })
    ai_applied = [{
        "transaction_id": str(tx.id), "date": str(tx.booking_date or tx.value_date or ""),
        "amount": str(tx.amount), "currency": tx.currency,
        "description": tx.description, "counterparty_name": tx.counterparty_name,
        "category": category_path(suggestion.category_id),
        "confidence": str(suggestion.confidence),
        "purchase_probability": str(suggestion.purchase_probability),
    } for tx, suggestion in applied_rows]
    write_private(destination, json.dumps({"category_options": sorted(
                                               category_path(category.id)
                                               for category in categories.values()),
                                           "unclassified": transactions,
                                           "transfer_pairs_for_review": transfer_pairs,
                                           "ai_applied_for_audit": ai_applied},
                                          ensure_ascii=False, indent=2) + "\n")
    return len(rows), len(pairs), len(ai_applied)


def _summary(db: Session) -> str:
    home = household(db)
    base = select(Transaction).join(Account).join(BankConnection).where(
        BankConnection.household_id == home.id)
    total = db.scalar(select(func.count()).select_from(base.subquery()))
    unknown = db.scalar(select(func.count()).select_from(base.where(
        Transaction.economic_type == "unclassified").subquery()))
    confirmed = db.scalar(select(func.count()).select_from(TransferPair).where(
        TransferPair.household_id == home.id, TransferPair.status == "CONFIRMED"))
    review = db.scalar(select(func.count()).select_from(TransferPair).where(
        TransferPair.household_id == home.id, TransferPair.status == "REVIEW"))
    internal = db.scalar(select(func.count()).select_from(base.where(
        Transaction.economic_type == "internal_transfer").subquery()))
    ai_applied = db.scalar(select(func.count()).select_from(DecisionSuggestion).join(
        Transaction).join(Account).join(BankConnection).where(
            BankConnection.household_id == home.id,
            DecisionSuggestion.status == "APPLIED"))
    return (f"transactions={total}; unclassified={unknown}; "
            f"internal_transfer_legs={internal}; ai_applied={ai_applied}; "
            f"confirmed_transfer_pairs={confirmed}; transfer_pairs_for_review={review}")


def main() -> int:
    parser = argparse.ArgumentParser(description="Local household classification")
    parser.add_argument("--database-url-file", type=Path, default=Path("secrets/database_url"))
    parser.add_argument("--openai-key-file", type=Path,
                        default=Path("secrets/openai/api_key"))
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("seed")
    sub.add_parser("run")
    sub.add_parser("summary")
    sub.add_parser("ai-probe", help="Check Decisions access using invented data")
    sub.add_parser("ai-apply-saved", help="Apply eligible saved proposals without an API call")
    ai = sub.add_parser("ai-suggest", help="Send a bounded set of unclassified sandbox descriptions")
    ai.add_argument("--limit", type=int, default=10)
    ai.add_argument("--review-only", action="store_true",
                    help="Save proposals without applying any category")
    export = sub.add_parser("review-export")
    export.add_argument("--output", type=Path,
                        default=Path("secrets/review/classification-review.json"))
    rules = sub.add_parser("add-rule")
    rules.add_argument("--file", type=Path, required=True)
    projects = sub.add_parser("add-project")
    projects.add_argument("--file", type=Path, required=True)
    overrides = sub.add_parser("apply-overrides")
    overrides.add_argument("--file", type=Path, required=True)
    decision = sub.add_parser("decide-pair")
    decision.add_argument("--pair-id", type=UUID, required=True)
    choice = decision.add_mutually_exclusive_group(required=True)
    choice.add_argument("--confirm", action="store_true")
    choice.add_argument("--reject", action="store_true")
    args = parser.parse_args()
    try:
        if args.command == "ai-probe":
            client = DecisionsClient(args.openai_key_file)
            try:
                choice, _, _ = client.choose("Merchant: Fictional supermarket\nDescription: groceries")
            finally:
                client.close()
            print("Decisions API probe succeeded" if choice is not None else
                  "Decisions API probe returned a refusal")
            return 0
        engine = database_engine(args.database_url_file)
        try:
            if args.command == "ai-suggest":
                client = DecisionsClient(args.openai_key_file)
                try:
                    with Session(engine) as db:
                        sent, proposed, applied = suggest(
                            db, client, limit=args.limit, auto_apply=not args.review_only)
                finally:
                    client.close()
                print(f"Decisions requests={sent}; category_suggestions={proposed}; "
                      f"automatically_applied={applied}; review_required={proposed - applied}")
                return 0
            if args.command == "ai-apply-saved":
                with Session(engine) as db:
                    count = apply_saved(db)
                print(f"Previously saved suggestions applied={count}; OpenAI requests=0")
                return 0
            with Session(engine) as db, db.begin():
                if args.command == "seed":
                    categories, projects, rules = seed(db)
                    print(f"Seeded: categories={categories}; projects={projects}; rules={rules}")
                elif args.command == "run":
                    confirmed, review = pair_transfers(db)
                    matched, unknown = classify(db)
                    print(f"Classified: rule_matches={matched}; remaining_unclassified={unknown}; "
                          f"new_transfer_pairs={confirmed}; new_pairs_for_review={review}")
                elif args.command == "summary":
                    print(_summary(db))
                elif args.command == "review-export":
                    transactions, pairs, ai_applied = _review_export(db, args.output)
                    print(f"Private review saved: transactions={transactions}; "
                          f"transfer_pairs={pairs}; ai_applied={ai_applied}; path={args.output}")
                elif args.command == "add-rule":
                    document = json.loads(read_private(args.file))
                    if not isinstance(document, dict):
                        raise FinanceError("Rule file must contain a JSON object")
                    add_rule(db, **document)
                    print("Rule saved locally")
                elif args.command == "add-project":
                    document = json.loads(read_private(args.file))
                    if not isinstance(document, dict):
                        raise FinanceError("Project file must contain a JSON object")
                    add_project(db, document.get("name"))
                    print("Project saved locally")
                elif args.command == "apply-overrides":
                    document = json.loads(read_private(args.file))
                    if not isinstance(document, dict):
                        raise FinanceError("Correction file must contain a JSON object")
                    count = apply_overrides(db, document.get("corrections"))
                    print(f"Corrections applied: {count}")
                else:
                    decide_pair(db, args.pair_id, confirm=args.confirm)
                    print("Transfer pair decision saved")
        finally:
            engine.dispose()
        return 0
    except FinanceError as exc:
        print(f"Classification failed: {exc}", file=sys.stderr)
        return 1
    except (OSError, UnicodeError, ValueError, TypeError, json.JSONDecodeError):
        print("Classification failed; check local input and database status", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
