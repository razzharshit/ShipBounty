from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from enum import Enum
from typing import Optional

from sqlalchemy import (
    Boolean,
    DateTime,
    Enum as SQLEnum,
    ForeignKey,
    Index,
    Integer,
    JSON,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    event,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.models.score import ImmutableRecordError


def _enum_column(enum_cls, name: str) -> SQLEnum:
    return SQLEnum(
        enum_cls,
        name=name,
        values_callable=lambda values: [item.value for item in values],
    )


class TreasuryEnvironment(str, Enum):
    TESTNET = "testnet"
    MAINNET = "mainnet"


class TreasuryStatus(str, Enum):
    ACTIVE = "active"
    PAUSED = "paused"


class TreasuryApprovalDecision(str, Enum):
    APPROVED = "approved"
    REJECTED = "rejected"


class LedgerEntryType(str, Enum):
    RESERVATION = "reservation"
    RELEASE = "release"
    SETTLEMENT = "settlement"
    RECONCILIATION_ADJUSTMENT = "reconciliation_adjustment"


class ReconciliationOutcome(str, Enum):
    PENDING = "pending"
    SUBMITTED = "submitted"
    CONFIRMED = "confirmed"
    FAILED = "failed"
    ERROR = "error"


class TreasuryAccount(Base):
    __tablename__ = "treasury_accounts"
    __table_args__ = (
        UniqueConstraint(
            "organization_id",
            "provider_key",
            "environment",
            "chain",
            "currency",
            "treasury_address",
            name="uq_treasury_accounts_scope",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    organization_id: Mapped[int] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    provider_key: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    environment: Mapped[TreasuryEnvironment] = mapped_column(
        _enum_column(TreasuryEnvironment, "treasuryenvironment"),
        nullable=False,
        index=True,
    )
    chain: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    currency: Mapped[str] = mapped_column(String(16), nullable=False, index=True)
    treasury_address: Mapped[str] = mapped_column(String(255), nullable=False)
    asset_contract_address: Mapped[Optional[str]] = mapped_column(
        String(255), nullable=True
    )
    asset_decimals: Mapped[int] = mapped_column(Integer, default=6, nullable=False)
    custody_model: Mapped[str] = mapped_column(
        String(32), default="multisig", nullable=False
    )
    opening_balance: Mapped[Decimal] = mapped_column(
        Numeric(24, 6), default=Decimal("0"), nullable=False
    )
    observed_balance: Mapped[Optional[Decimal]] = mapped_column(
        Numeric(24, 6), nullable=True
    )
    per_payout_limit: Mapped[Decimal] = mapped_column(
        Numeric(24, 6), nullable=False
    )
    daily_spending_limit: Mapped[Decimal] = mapped_column(
        Numeric(24, 6), nullable=False
    )
    manual_approval_threshold: Mapped[Optional[Decimal]] = mapped_column(
        Numeric(24, 6), nullable=True
    )
    standard_required_approvals: Mapped[int] = mapped_column(
        Integer, default=1, nullable=False
    )
    high_value_required_approvals: Mapped[int] = mapped_column(
        Integer, default=2, nullable=False
    )
    required_confirmations: Mapped[int] = mapped_column(
        Integer, default=1, nullable=False
    )
    simulation_required: Mapped[bool] = mapped_column(
        Boolean, default=True, nullable=False
    )
    status: Mapped[TreasuryStatus] = mapped_column(
        _enum_column(TreasuryStatus, "treasurystatus"),
        default=TreasuryStatus.PAUSED,
        nullable=False,
        index=True,
    )
    provider_config: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    paused_reason: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    last_balance_checked_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime, nullable=True
    )
    created_by_user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False
    )

    payouts = relationship("Payout", back_populates="treasury_account")
    ledger_entries = relationship("PayoutLedgerEntry", back_populates="treasury")


class TreasuryApproval(Base):
    __tablename__ = "treasury_approvals"
    __table_args__ = (
        UniqueConstraint(
            "payout_id",
            "approver_user_id",
            name="uq_treasury_approvals_payout_approver",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    payout_id: Mapped[int] = mapped_column(
        ForeignKey("payouts.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    treasury_account_id: Mapped[int] = mapped_column(
        ForeignKey("treasury_accounts.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    approver_user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    decision: Mapped[TreasuryApprovalDecision] = mapped_column(
        _enum_column(TreasuryApprovalDecision, "treasuryapprovaldecision"),
        nullable=False,
        index=True,
    )
    reason: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    amount: Mapped[Decimal] = mapped_column(Numeric(24, 6), nullable=False)
    currency: Mapped[str] = mapped_column(String(16), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, nullable=False
    )

    payout = relationship("Payout")
    treasury = relationship("TreasuryAccount")
    approver = relationship("User")


class PayoutLedgerEntry(Base):
    __tablename__ = "payout_ledger_entries"
    __table_args__ = (
        UniqueConstraint(
            "idempotency_key", name="uq_payout_ledger_entries_idempotency_key"
        ),
        Index(
            "ix_payout_ledger_entries_treasury_created",
            "treasury_account_id",
            "created_at",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    treasury_account_id: Mapped[int] = mapped_column(
        ForeignKey("treasury_accounts.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    payout_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("payouts.id", ondelete="RESTRICT"), nullable=True, index=True
    )
    entry_type: Mapped[LedgerEntryType] = mapped_column(
        _enum_column(LedgerEntryType, "ledgerentrytype"),
        nullable=False,
        index=True,
    )
    currency: Mapped[str] = mapped_column(String(16), nullable=False)
    available_delta: Mapped[Decimal] = mapped_column(
        Numeric(24, 6), default=Decimal("0"), nullable=False
    )
    reserved_delta: Mapped[Decimal] = mapped_column(
        Numeric(24, 6), default=Decimal("0"), nullable=False
    )
    settled_delta: Mapped[Decimal] = mapped_column(
        Numeric(24, 6), default=Decimal("0"), nullable=False
    )
    idempotency_key: Mapped[str] = mapped_column(String(128), nullable=False)
    entry_metadata: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    created_by_user_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, nullable=False
    )

    treasury = relationship("TreasuryAccount", back_populates="ledger_entries")
    payout = relationship("Payout")


class PayoutReconciliation(Base):
    __tablename__ = "payout_reconciliations"
    __table_args__ = (
        UniqueConstraint(
            "payout_id",
            "provider_status_hash",
            name="uq_payout_reconciliations_status_hash",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    payout_id: Mapped[int] = mapped_column(
        ForeignKey("payouts.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    payout_attempt_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("payout_attempts.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    provider_key: Mapped[str] = mapped_column(String(64), nullable=False)
    provider_reference: Mapped[str] = mapped_column(String(255), nullable=False)
    outcome: Mapped[ReconciliationOutcome] = mapped_column(
        _enum_column(ReconciliationOutcome, "reconciliationoutcome"),
        nullable=False,
        index=True,
    )
    confirmations: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    transaction_hash: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    provider_status_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    provider_response: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    error: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    checked_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, nullable=False
    )

    payout = relationship("Payout")
    payout_attempt = relationship("PayoutAttempt")


class TreasuryBalanceSnapshot(Base):
    __tablename__ = "treasury_balance_snapshots"
    __table_args__ = (
        UniqueConstraint(
            "treasury_account_id",
            "balance_hash",
            name="uq_treasury_balance_snapshots_hash",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    treasury_account_id: Mapped[int] = mapped_column(
        ForeignKey("treasury_accounts.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    provider_key: Mapped[str] = mapped_column(String(64), nullable=False)
    currency: Mapped[str] = mapped_column(String(16), nullable=False)
    observed_balance: Mapped[Decimal] = mapped_column(
        Numeric(24, 6), nullable=False
    )
    balance_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    provider_response: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    observed_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, nullable=False
    )

    treasury = relationship("TreasuryAccount")


def _prevent_change(mapper, connection, target) -> None:
    raise ImmutableRecordError(f"{type(target).__name__} records are insert-only")


for immutable_model in (
    TreasuryApproval,
    PayoutLedgerEntry,
    PayoutReconciliation,
    TreasuryBalanceSnapshot,
):
    event.listen(immutable_model, "before_update", _prevent_change)
    event.listen(immutable_model, "before_delete", _prevent_change)
