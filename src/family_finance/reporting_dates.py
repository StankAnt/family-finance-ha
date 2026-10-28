"""Budget period is independent of the actual movement of bank funds."""
from sqlalchemy import case, func

from .models import Transaction


def operation_date_expression():
    return func.coalesce(Transaction.transaction_date, Transaction.booking_date,
                         Transaction.value_date)


def budget_date_expression():
    return case((Transaction.economic_type == "external_income",
                 func.coalesce(Transaction.income_month, operation_date_expression())),
                else_=operation_date_expression())


def budget_date(transaction):
    actual = transaction.transaction_date or transaction.booking_date or transaction.value_date
    if transaction.economic_type == "external_income":
        return transaction.income_month or actual
    return actual
