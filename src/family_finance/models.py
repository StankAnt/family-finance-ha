"""Local household ledger. Raw API payloads and credentials are never stored here."""

from __future__ import annotations

from datetime import date, datetime, timezone
from decimal import Decimal
from uuid import UUID, uuid4

from sqlalchemy import Date, DateTime, ForeignKey, Index, Numeric, String, Text, UniqueConstraint
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column
from sqlalchemy.types import Uuid


def now() -> datetime:
    return datetime.now(timezone.utc)


class Base(DeclarativeBase):
    pass


class Household(Base):
    __tablename__ = "household"
    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class BankConnection(Base):
    __tablename__ = "bank_connection"
    __table_args__ = (UniqueConstraint("household_id", "environment", "application_id"),)
    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    household_id: Mapped[UUID] = mapped_column(ForeignKey("household.id"), nullable=False)
    environment: Mapped[str] = mapped_column(String(16), nullable=False)
    application_id: Mapped[str] = mapped_column(String(36), nullable=False)
    provider: Mapped[str] = mapped_column(String(40), default="enable_banking")
    label: Mapped[str] = mapped_column(String(120), default="primary")
    consent_status: Mapped[str] = mapped_column(String(40), default="UNKNOWN")
    consent_valid_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_checked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class Account(Base):
    __tablename__ = "account"
    __table_args__ = (UniqueConstraint("connection_id", "identification_hash"),)
    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    connection_id: Mapped[UUID] = mapped_column(ForeignKey("bank_connection.id"), nullable=False)
    identification_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    identifier_digest: Mapped[str | None] = mapped_column(String(64))
    provider_uid: Mapped[str] = mapped_column(String(36), nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    name: Mapped[str | None] = mapped_column(String(255))
    active: Mapped[bool] = mapped_column(default=True)
    first_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class Category(Base):
    __tablename__ = "category"
    __table_args__ = (UniqueConstraint("household_id", "name", "parent_id"),)
    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    household_id: Mapped[UUID] = mapped_column(ForeignKey("household.id"), nullable=False)
    parent_id: Mapped[UUID | None] = mapped_column(ForeignKey("category.id"))
    name: Mapped[str] = mapped_column(String(120), nullable=False)


class Project(Base):
    __tablename__ = "project"
    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    household_id: Mapped[UUID] = mapped_column(ForeignKey("household.id"), nullable=False)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    active: Mapped[bool] = mapped_column(default=True)


class CategorizationRule(Base):
    __tablename__ = "categorization_rule"
    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    household_id: Mapped[UUID] = mapped_column(ForeignKey("household.id"), nullable=False)
    category_id: Mapped[UUID | None] = mapped_column(ForeignKey("category.id"))
    project_id: Mapped[UUID | None] = mapped_column(ForeignKey("project.id"))
    pattern: Mapped[str] = mapped_column(String(500), nullable=False)
    priority: Mapped[int] = mapped_column(default=100)
    enabled: Mapped[bool] = mapped_column(default=True)
    match_field: Mapped[str] = mapped_column(String(20), default="either")
    direction: Mapped[str] = mapped_column(String(10), default="debit")
    account_id: Mapped[UUID | None] = mapped_column(ForeignKey("account.id"))
    min_abs_amount: Mapped[Decimal | None] = mapped_column(Numeric(20, 4))
    max_abs_amount: Mapped[Decimal | None] = mapped_column(Numeric(20, 4))
    economic_type: Mapped[str | None] = mapped_column(String(40))


class SyncRun(Base):
    __tablename__ = "sync_run"
    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    connection_id: Mapped[UUID] = mapped_column(ForeignKey("bank_connection.id"), nullable=False)
    source: Mapped[str] = mapped_column(String(20), nullable=False)
    status: Mapped[str] = mapped_column(String(20), default="RUNNING")
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    account_count: Mapped[int] = mapped_column(default=0)
    transaction_count: Mapped[int] = mapped_column(default=0)
    error_code: Mapped[str | None] = mapped_column(String(60))


class Transaction(Base):
    __tablename__ = "transaction"
    __table_args__ = (
        UniqueConstraint("account_id", "identity_key"),
        Index("ix_transaction_account_booking", "account_id", "booking_date"),
    )
    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    account_id: Mapped[UUID] = mapped_column(ForeignKey("account.id"), nullable=False)
    identity_key: Mapped[str] = mapped_column(String(80), nullable=False)
    entry_reference: Mapped[str | None] = mapped_column(String(500))
    provider_transaction_id: Mapped[str | None] = mapped_column(String(500))
    status: Mapped[str] = mapped_column(String(20), nullable=False)
    booking_date: Mapped[date | None] = mapped_column(Date)
    value_date: Mapped[date | None] = mapped_column(Date)
    transaction_date: Mapped[date | None] = mapped_column(Date)
    amount: Mapped[Decimal] = mapped_column(Numeric(20, 4), nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    counterparty_name: Mapped[str | None] = mapped_column(Text)
    counterparty_identifier_digest: Mapped[str | None] = mapped_column(String(64))
    payload_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    category_id: Mapped[UUID | None] = mapped_column(ForeignKey("category.id"))
    project_id: Mapped[UUID | None] = mapped_column(ForeignKey("project.id"))
    economic_type: Mapped[str] = mapped_column(String(40), default="unclassified")
    override_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    imported_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class CashEntry(Base):
    """Household cash movement in its original currency."""

    __tablename__ = "cash_entry"
    __table_args__ = (Index("ix_cash_entry_household_date", "household_id", "occurred_on"),)
    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    household_id: Mapped[UUID] = mapped_column(ForeignKey("household.id"), nullable=False)
    occurred_on: Mapped[date] = mapped_column(Date, nullable=False)
    amount: Mapped[Decimal] = mapped_column(Numeric(20, 4), nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False, default="PLN")
    kind: Mapped[str] = mapped_column(String(20), nullable=False)
    transaction_id: Mapped[UUID | None] = mapped_column(ForeignKey("transaction.id"))
    category_id: Mapped[UUID | None] = mapped_column(ForeignKey("category.id"))
    project_id: Mapped[UUID | None] = mapped_column(ForeignKey("project.id"))
    note: Mapped[str | None] = mapped_column(String(250))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class ClassificationCorrection(Base):
    __tablename__ = "classification_correction"
    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    transaction_id: Mapped[UUID] = mapped_column(ForeignKey("transaction.id"), nullable=False)
    old_category_id: Mapped[UUID | None] = mapped_column(Uuid)
    new_category_id: Mapped[UUID | None] = mapped_column(Uuid)
    old_project_id: Mapped[UUID | None] = mapped_column(Uuid)
    new_project_id: Mapped[UUID | None] = mapped_column(Uuid)
    old_economic_type: Mapped[str] = mapped_column(String(40), nullable=False)
    new_economic_type: Mapped[str] = mapped_column(String(40), nullable=False)
    source: Mapped[str] = mapped_column(String(20), nullable=False, default="manual")
    applied_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class DecisionSuggestion(Base):
    __tablename__ = "decision_suggestion"
    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    transaction_id: Mapped[UUID] = mapped_column(ForeignKey("transaction.id"), unique=True, nullable=False)
    category_id: Mapped[UUID | None] = mapped_column(ForeignKey("category.id"))
    input_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    model: Mapped[str] = mapped_column(String(80), nullable=False)
    confidence: Mapped[Decimal | None] = mapped_column(Numeric(6, 5))
    purchase_probability: Mapped[Decimal | None] = mapped_column(Numeric(6, 5))
    status: Mapped[str] = mapped_column(String(20), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    applied_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class TransferPair(Base):
    __tablename__ = "transfer_pair"
    __table_args__ = (
        UniqueConstraint("debit_transaction_id"),
        UniqueConstraint("credit_transaction_id"),
    )
    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    household_id: Mapped[UUID] = mapped_column(ForeignKey("household.id"), nullable=False)
    debit_transaction_id: Mapped[UUID] = mapped_column(ForeignKey("transaction.id"), nullable=False)
    credit_transaction_id: Mapped[UUID] = mapped_column(ForeignKey("transaction.id"), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False)
    reason: Mapped[str] = mapped_column(String(40), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class AccountBalanceSnapshot(Base):
    __tablename__ = "account_balance_snapshot"
    __table_args__ = (UniqueConstraint("account_id", "sync_run_id", "balance_type", "reference_date"),)
    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    account_id: Mapped[UUID] = mapped_column(ForeignKey("account.id"), nullable=False)
    sync_run_id: Mapped[UUID] = mapped_column(ForeignKey("sync_run.id"), nullable=False)
    balance_type: Mapped[str] = mapped_column(String(20), nullable=False)
    reference_date: Mapped[date | None] = mapped_column(Date)
    amount: Mapped[Decimal] = mapped_column(Numeric(20, 4), nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class SyncCheckpoint(Base):
    __tablename__ = "sync_checkpoint"
    account_id: Mapped[UUID] = mapped_column(ForeignKey("account.id"), primary_key=True)
    last_successful_to: Mapped[date | None] = mapped_column(Date)
    last_successful_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_run_id: Mapped[UUID | None] = mapped_column(ForeignKey("sync_run.id"))


class FxRate(Base):
    __tablename__ = "fx_rate"
    __table_args__ = (UniqueConstraint("currency", "effective_date", "source"),)
    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    effective_date: Mapped[date] = mapped_column(Date, nullable=False)
    pln_per_unit: Mapped[Decimal] = mapped_column(Numeric(20, 8), nullable=False)
    source: Mapped[str] = mapped_column(String(40), nullable=False, default="NBP_A_MID")
    fetched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class Mortgage(Base):
    __tablename__ = "mortgage"
    __table_args__ = (UniqueConstraint("household_id", "name"),)
    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    household_id: Mapped[UUID] = mapped_column(ForeignKey("household.id"), nullable=False)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False)


class MortgageAllocation(Base):
    __tablename__ = "mortgage_allocation"
    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    mortgage_id: Mapped[UUID] = mapped_column(ForeignKey("mortgage.id"), nullable=False)
    transaction_id: Mapped[UUID] = mapped_column(ForeignKey("transaction.id"), unique=True, nullable=False)
    principal: Mapped[Decimal] = mapped_column(Numeric(20, 4), nullable=False)
    interest: Mapped[Decimal] = mapped_column(Numeric(20, 4), nullable=False)
    fees: Mapped[Decimal] = mapped_column(Numeric(20, 4), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class ValuationSnapshot(Base):
    __tablename__ = "valuation_snapshot"
    __table_args__ = (UniqueConstraint("household_id", "kind", "name", "as_of"),)
    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    household_id: Mapped[UUID] = mapped_column(ForeignKey("household.id"), nullable=False)
    kind: Mapped[str] = mapped_column(String(30), nullable=False)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    as_of: Mapped[date] = mapped_column(Date, nullable=False)
    amount: Mapped[Decimal] = mapped_column(Numeric(20, 4), nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    estimated: Mapped[bool] = mapped_column(default=False)


class Goal(Base):
    __tablename__ = "goal"
    __table_args__ = (UniqueConstraint("household_id", "name"),)
    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    household_id: Mapped[UUID] = mapped_column(ForeignKey("household.id"), nullable=False)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    target_amount: Mapped[Decimal] = mapped_column(Numeric(20, 4), nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    target_date: Mapped[date | None] = mapped_column(Date)
    active: Mapped[bool] = mapped_column(default=True)


class GoalProgress(Base):
    __tablename__ = "goal_progress"
    __table_args__ = (UniqueConstraint("goal_id", "as_of"),)
    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    goal_id: Mapped[UUID] = mapped_column(ForeignKey("goal.id"), nullable=False)
    as_of: Mapped[date] = mapped_column(Date, nullable=False)
    amount: Mapped[Decimal] = mapped_column(Numeric(20, 4), nullable=False)
    estimated: Mapped[bool] = mapped_column(default=False)


class CoverageDeclaration(Base):
    __tablename__ = "coverage_declaration"
    __table_args__ = (UniqueConstraint("household_id", "as_of"),)
    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    household_id: Mapped[UUID] = mapped_column(ForeignKey("household.id"), nullable=False)
    as_of: Mapped[date] = mapped_column(Date, nullable=False)
    accounts_complete: Mapped[bool] = mapped_column(nullable=False)
    assets_complete: Mapped[bool] = mapped_column(nullable=False)
    liabilities_complete: Mapped[bool] = mapped_column(nullable=False)


class ManualRevision(Base):
    __tablename__ = "manual_revision"
    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    household_id: Mapped[UUID] = mapped_column(ForeignKey("household.id"), nullable=False)
    entity_kind: Mapped[str] = mapped_column(String(40), nullable=False)
    record_id: Mapped[UUID] = mapped_column(Uuid, nullable=False)
    previous_value: Mapped[str] = mapped_column(Text, nullable=False)
    new_value: Mapped[str] = mapped_column(Text, nullable=False)
    changed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
