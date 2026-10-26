"""Local, explicitly confirmed purchase refunds and shared expenses."""
from datetime import date, timedelta
from decimal import Decimal, ROUND_HALF_UP
import re
import unicodedata
from uuid import UUID

from sqlalchemy import or_, select

from .classification import household
from .models import (Account, BankConnection, CashEntry, ClassificationCorrection,
                     PurchaseLink, PurchaseShare, Transaction, TransferPair, now)
from .secrets import FinanceError

ZERO = Decimal(0)
CENT = Decimal("0.01")
PURCHASE_TYPES = {"consumption", "project_expense", "unclassified"}


def owned_transaction(db, value, *, lock=False):
    try:
        identifier = UUID(str(value))
    except ValueError:
        raise FinanceError("Выберите операцию") from None
    query = select(Transaction).join(Account).join(BankConnection).where(
        Transaction.id == identifier, BankConnection.household_id == household(db).id)
    if lock:
        query = query.with_for_update(of=Transaction)
    tx = db.scalar(query)
    if tx is None or tx.status != "BOOK":
        raise FinanceError("Нужна завершённая операция этой семьи")
    return tx


def purchase(db, identifier, *, lock=False):
    tx = owned_transaction(db, identifier, lock=lock)
    if tx.amount >= 0 or tx.economic_type not in PURCHASE_TYPES:
        raise FinanceError("Выберите покупку, а не перевод или ипотеку")
    if db.scalar(select(TransferPair.id).where(
            or_(TransferPair.debit_transaction_id == tx.id, TransferPair.credit_transaction_id == tx.id),
            TransferPair.status.in_(("CONFIRMED", "REVIEW"))).limit(1)):
        raise FinanceError("Сначала отклоните связь покупки со своим переводом")
    return tx


def cash_in_purchase_currency(db, receipt, tx):
    from .accounting import pln, rate
    if receipt.currency == tx.currency:
        return receipt.amount
    value = pln(db, receipt.amount, receipt.currency, receipt.occurred_on)
    fx = rate(db, tx.currency, receipt.occurred_on)
    if value is None or fx is None:
        raise FinanceError("Не хватает курса для пересчёта возврата")
    return (value / fx).quantize(CENT, rounding=ROUND_HALF_UP)


def paid_share(db, share, tx, day=None):
    cash = db.scalars(select(CashEntry).where(CashEntry.share_id == share.id)).all()
    bank = db.execute(select(PurchaseLink, Transaction).join(Transaction,
        Transaction.id == PurchaseLink.credit_id).where(PurchaseLink.share_id == share.id)).all()
    return sum((cash_in_purchase_currency(db, row, tx) for row in cash
                if day is None or row.occurred_on <= day), ZERO) + sum(
        (credit.amount for _, credit in bank if day is None or credit.booking_date <= day), ZERO)


def purchase_offset(db, tx):
    """Expense adjustment in PLN; cash settlement of an assigned share is not deducted twice."""
    from .accounting import pln
    shares = db.scalars(select(PurchaseShare).where(PurchaseShare.purchase_id == tx.id)).all()
    links = db.execute(select(PurchaseLink, Transaction).join(Transaction,
        Transaction.id == PurchaseLink.credit_id).where(PurchaseLink.purchase_id == tx.id,
        PurchaseLink.share_id.is_(None))).all()
    original_currency = sum((row.amount for row in shares), ZERO) + sum((credit.amount for _, credit in links), ZERO)
    result = pln(db, original_currency, tx.currency, tx.booking_date)
    if result is None:
        return None
    for receipt in db.scalars(select(CashEntry).where(CashEntry.transaction_id == tx.id,
            CashEntry.kind == "reimbursement", CashEntry.share_id.is_(None))):
        value = pln(db, receipt.amount, receipt.currency, receipt.occurred_on)
        if value is None:
            return None
        result += value
    return result


def refund_capacity(db, tx):
    shares = sum(db.scalars(select(PurchaseShare.amount).where(PurchaseShare.purchase_id == tx.id)), ZERO)
    refunds = sum(db.scalars(select(Transaction.amount).join(PurchaseLink,
        PurchaseLink.credit_id == Transaction.id).where(PurchaseLink.purchase_id == tx.id,
        PurchaseLink.share_id.is_(None))), ZERO)
    refunds += sum((cash_in_purchase_currency(db, row, tx) for row in db.scalars(
        select(CashEntry).where(CashEntry.transaction_id == tx.id,
        CashEntry.kind == "reimbursement", CashEntry.share_id.is_(None)))), ZERO)
    return -tx.amount - shares - refunds


def mark(db, tx, kind, category_id=None, project_id=None, *, override=None):
    db.add(ClassificationCorrection(transaction_id=tx.id, old_category_id=tx.category_id,
        new_category_id=category_id, old_project_id=tx.project_id, new_project_id=project_id,
        old_economic_type=tx.economic_type, new_economic_type=kind, source="purchase_link"))
    tx.economic_type, tx.category_id, tx.project_id = kind, category_id, project_id
    tx.override_at = override or now()


def set_shares(db, payload):
    from .accounting import money
    if set(payload) - {"purchase_id", "shares", "assignments"} or not {"purchase_id", "shares"} <= set(payload) or not isinstance(payload["shares"], list) or len(payload["shares"]) > 30:
        raise FinanceError("Некорректная разбивка покупки")
    tx = purchase(db, payload["purchase_id"], lock=True)
    existing = {row.person: row for row in db.scalars(select(PurchaseShare).where(PurchaseShare.purchase_id == tx.id))}
    requested = {}
    for item in payload["shares"]:
        if not isinstance(item, dict) or set(item) != {"person", "amount"}:
            raise FinanceError("Укажите имя и сумму каждого участника")
        person = item["person"].strip() if isinstance(item["person"], str) else ""
        amount = money(item["amount"], positive=True)
        if not 1 <= len(person) <= 120 or person in requested or amount <= 0 or amount.quantize(CENT) != amount:
            raise FinanceError("Нужны разные имена и положительные суммы до двух знаков")
        requested[person] = amount
    legacy = {}
    if requested:
        for receipt in db.scalars(select(CashEntry).where(CashEntry.transaction_id == tx.id,
                CashEntry.kind == "reimbursement", CashEntry.share_id.is_(None))):
            legacy[("cash", str(receipt.id))] = (receipt, cash_in_purchase_currency(db, receipt, tx))
        for link, credit in db.execute(select(PurchaseLink, Transaction).join(Transaction,
                Transaction.id == PurchaseLink.credit_id).where(PurchaseLink.purchase_id == tx.id,
                PurchaseLink.kind == "reimbursement", PurchaseLink.share_id.is_(None))):
            legacy[("bank", str(link.id))] = (link, credit.amount)
    assignments = payload.get("assignments", [])
    if not isinstance(assignments, list):
        raise FinanceError("Укажите участников для прежних возвратов")
    assigned = {}
    extra_paid = {}
    for item in assignments:
        if not isinstance(item, dict) or set(item) != {"method", "id", "person"}:
            raise FinanceError("Некорректная привязка прежнего возврата")
        key = (item["method"], item["id"])
        if key not in legacy or key in assigned or item["person"] not in requested:
            raise FinanceError("Выберите участника для каждого прежнего возврата")
        assigned[key] = item["person"]
        extra_paid[item["person"]] = extra_paid.get(item["person"], ZERO) + legacy[key][1]
    if set(assigned) != set(legacy):
        raise FinanceError("Выберите, кто сделал каждый из прежних возвратов")
    for person, amount in requested.items():
        already_paid = paid_share(db, existing[person], tx) if person in existing else ZERO
        if amount < already_paid + extra_paid.get(person, ZERO):
            raise FinanceError("Доля не может быть меньше уже возвращённой суммы")
    available = refund_capacity(db, tx) + sum((row.amount for row in existing.values()), ZERO) + sum((value for _, value in legacy.values()), ZERO)
    if sum(requested.values(), ZERO) > available:
        raise FinanceError("Сумма долей превышает покупку с учётом возвратов")
    for person, row in existing.items():
        has_receipts = db.scalar(select(CashEntry.id).where(CashEntry.share_id == row.id).limit(1)) or db.scalar(
            select(PurchaseLink.id).where(PurchaseLink.share_id == row.id).limit(1))
        if person not in requested:
            if has_receipts:
                raise FinanceError("У участника есть возвраты: сначала отмените их связи")
            db.delete(row)
        else:
            if requested[person] < paid_share(db, row, tx):
                raise FinanceError("Доля не может быть меньше уже возвращённой суммы")
            row.amount = requested[person]
    for person, amount in requested.items():
        if person not in existing:
            existing[person] = PurchaseShare(purchase_id=tx.id, person=person, amount=amount)
            db.add(existing[person])
    db.flush()
    for key, person in assigned.items():
        legacy[key][0].share_id = existing[person].id
    mark(db, tx, "consumption" if tx.economic_type == "unclassified" else tx.economic_type, tx.category_id, tx.project_id)
    db.flush()
    return {"saved": len(requested)}


def link_return(db, payload):
    if set(payload) - {"purchase_id", "credit_id", "kind", "share_id"} or not {"purchase_id", "credit_id", "kind"} <= set(payload):
        raise FinanceError("Выберите покупку, поступление и вид возврата")
    tx = purchase(db, payload["purchase_id"], lock=True)
    credit = owned_transaction(db, payload["credit_id"], lock=True)
    kind = payload["kind"]
    if kind not in {"store_refund", "reimbursement"} or credit.amount <= 0 or credit.currency != tx.currency:
        raise FinanceError("Возврат должен быть поступлением в валюте покупки")
    if credit.economic_type not in {"unclassified", "external_income", "external_transfer"}:
        raise FinanceError("Это поступление уже учтено как перевод или другой особый случай")
    if credit.booking_date < (tx.transaction_date or tx.booking_date):
        raise FinanceError("Возврат не может предшествовать покупке")
    if db.scalar(select(PurchaseLink.id).where(PurchaseLink.credit_id == credit.id)):
        raise FinanceError("Поступление уже связано с покупкой")
    if db.scalar(select(TransferPair.id).where(or_(TransferPair.credit_transaction_id == credit.id,
            TransferPair.debit_transaction_id == credit.id), TransferPair.status.in_(("CONFIRMED", "REVIEW"))).limit(1)):
        raise FinanceError("Сначала отклоните связь поступления со своим переводом")
    share = None
    if payload.get("share_id"):
        share = db.get(PurchaseShare, UUID(str(payload["share_id"])))
        if share is None or share.purchase_id != tx.id or kind != "reimbursement":
            raise FinanceError("Выберите участника этой покупки")
        if credit.amount > share.amount - paid_share(db, share, tx):
            raise FinanceError("Возврат превышает оставшийся долг участника")
    else:
        if kind == "reimbursement" and db.scalar(select(PurchaseShare.id).where(PurchaseShare.purchase_id == tx.id).limit(1)):
            raise FinanceError("Выберите, кто из участников вернул деньги")
        if credit.amount > refund_capacity(db, tx):
            raise FinanceError("Возврат превышает оставшуюся личную часть покупки")
    db.add(PurchaseLink(purchase_id=tx.id, credit_id=credit.id, kind=kind,
        share_id=share.id if share else None, old_economic_type=credit.economic_type,
        old_category_id=credit.category_id, old_project_id=credit.project_id, old_override_at=credit.override_at))
    mark(db, credit, "purchase_refund" if kind == "store_refund" else "reimbursement", tx.category_id, tx.project_id)
    mark(db, tx, "consumption" if tx.economic_type == "unclassified" else tx.economic_type, tx.category_id, tx.project_id)
    db.flush()
    return {"linked": True}


def unlink_return(db, payload):
    if set(payload) != {"id"}:
        raise FinanceError("Выберите связь возврата")
    link = db.get(PurchaseLink, UUID(str(payload["id"])))
    if link is None:
        raise FinanceError("Связь не найдена")
    purchase(db, link.purchase_id, lock=True)
    credit = owned_transaction(db, link.credit_id, lock=True)
    mark(db, credit, link.old_economic_type, link.old_category_id, link.old_project_id)
    credit.override_at = link.old_override_at
    db.delete(link)
    db.flush()
    return {"unlinked": True}


def purchase_details(db, tx):
    shares = db.scalars(select(PurchaseShare).where(PurchaseShare.purchase_id == tx.id).order_by(PurchaseShare.person)).all()
    receipts = []
    for cash in db.scalars(select(CashEntry).where(CashEntry.transaction_id == tx.id, CashEntry.kind == "reimbursement")):
        person = db.get(PurchaseShare, cash.share_id) if cash.share_id else None
        receipts.append({"id": str(cash.id), "date": str(cash.occurred_on), "amount": str(cash.amount),
            "currency": cash.currency, "method": "cash", "person": person.person if person else None,
            "affects_wallet": cash.affects_wallet})
    for link, credit in db.execute(select(PurchaseLink, Transaction).join(Transaction,
            Transaction.id == PurchaseLink.credit_id).where(PurchaseLink.purchase_id == tx.id)):
        person = db.get(PurchaseShare, link.share_id) if link.share_id else None
        receipts.append({"id": str(link.id), "date": str(credit.booking_date), "amount": str(credit.amount),
            "currency": credit.currency, "method": "bank", "person": person.person if person else None,
            "kind": link.kind, "credit_id": str(credit.id)})
    return {"shares": [{"id": str(s.id), "person": s.person, "amount": str(s.amount),
        "paid": str(paid_share(db, s, tx)), "outstanding": str(s.amount - paid_share(db, s, tx))} for s in shares],
        "own_amount": str(-tx.amount - sum((s.amount for s in shares), ZERO)),
        "remaining_refundable": str(refund_capacity(db, tx)), "receipts": receipts}


def receivables(db, day):
    from .accounting import pln
    total, missing, rows = ZERO, False, []
    for share, tx in db.execute(select(PurchaseShare, Transaction).join(Transaction,
            Transaction.id == PurchaseShare.purchase_id).join(Account).join(BankConnection).where(
                BankConnection.household_id == household(db).id, Transaction.booking_date <= day)):
        remaining = share.amount - paid_share(db, share, tx, day)
        if remaining <= 0:
            continue
        value = pln(db, remaining, tx.currency, day)
        missing |= value is None
        total += value or ZERO
        rows.append({"purchase_id": str(tx.id), "person": share.person, "amount": str(remaining),
                     "currency": tx.currency, "date": str(tx.transaction_date or tx.booking_date)})
    return {"amount_pln": str(total.quantize(CENT)) if not missing else None, "rows": rows}


STOP = set("visa mastercard plat karta transakcja platnosc zwrot refund return payment zakup purchase card warszawa polska pl sp zoo na za od dla przelew".split())


def merchant_tokens(tx):
    text = f"{tx.counterparty_name or ''} {tx.description or ''}".lower().replace("ł", "l")
    text = "".join(c for c in unicodedata.normalize("NFKD", text) if not unicodedata.combining(c))
    return {word for word in re.findall(r"[a-z]{3,}", text) if word not in STOP}


def return_candidates(db, credit):
    if credit.amount <= 0 or credit.status != "BOOK" or credit.economic_type not in {"unclassified", "external_income", "external_transfer"}:
        return []
    tokens = merchant_tokens(credit)
    if not tokens or db.scalar(select(PurchaseLink.id).where(PurchaseLink.credit_id == credit.id)):
        return []
    candidates = []
    txs = db.scalars(select(Transaction).join(Account).join(BankConnection).where(
        BankConnection.household_id == household(db).id, Transaction.status == "BOOK",
        Transaction.amount <= -credit.amount, Transaction.currency == credit.currency,
        Transaction.economic_type.in_(PURCHASE_TYPES), Transaction.booking_date <= credit.booking_date,
        Transaction.booking_date >= credit.booking_date - timedelta(days=180)))
    for tx in txs:
        overlap = tokens & merchant_tokens(tx)
        if not overlap or refund_capacity(db, tx) < credit.amount:
            continue
        if db.scalar(select(TransferPair.id).where(TransferPair.debit_transaction_id == tx.id,
                TransferPair.status.in_(("REVIEW", "CONFIRMED"))).limit(1)):
            continue
        candidates.append((len(overlap), -(credit.booking_date - tx.booking_date).days,
            {"id": str(tx.id), "date": str(tx.transaction_date or tx.booking_date),
             "amount": str(tx.amount), "currency": tx.currency, "description": (tx.description or "")[:250]}))
    candidates.sort(key=lambda item: item[:2], reverse=True)
    result = [item[2] for item in candidates[:3]]
    for item in result:
        item["purchase"] = purchase_details(db, db.get(Transaction, UUID(item["id"])))
    return result
