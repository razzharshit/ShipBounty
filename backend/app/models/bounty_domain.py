from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from enum import Enum
from typing import Optional

from sqlalchemy import (
    Boolean,
    BigInteger,
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
    inspect,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.models.score import ImmutableRecordError


class IssueState(str, Enum):
    OPEN = "open"
    CLOSED = "closed"


class BountyStatus(str, Enum):
    DRAFT = "draft"
    OPEN = "open"
    ASSIGNED = "assigned"
    CLOSED = "closed"
    PAID = "paid"
    CANCELLED = "cancelled"
    EXPIRED = "expired"


class FundingStatus(str, Enum):
    UNFUNDED = "unfunded"
    PENDING = "pending"
    FUNDED = "funded"
    EXHAUSTED = "exhausted"
    REFUNDED = "refunded"


class AssignmentStatus(str, Enum):
    ACTIVE = "active"
    COMPLETED = "completed"
    CANCELLED = "cancelled"


class ClaimStatus(str, Enum):
    APPROVED = "approved"
    REJECTED = "rejected"
    CANCELLED = "cancelled"
    PAID = "paid"


class WalletStatus(str, Enum):
    ACTIVE = "active"
    INACTIVE = "inactive"


class PayoutState(str, Enum):
    CREATED = "created"
    AUTHORIZED = "authorized"
    SUBMITTING = "submitting"
    SUBMISSION_UNKNOWN = "submission_unknown"
    SUBMITTED = "submitted"
    CONFIRMED = "confirmed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class PayoutAttemptState(str, Enum):
    SUBMITTING = "submitting"
    SUBMISSION_UNKNOWN = "submission_unknown"
    SUBMITTED = "submitted"
    FAILED = "failed"


def enum_column(enum_cls, name: str) -> SQLEnum:
    return SQLEnum(
        enum_cls,
        name=name,
        values_callable=lambda values: [item.value for item in values],
    )


class BountyPolicy(Base):
    __tablename__ = "bounty_policies"
    __table_args__ = (
        UniqueConstraint(
            "repository_id", "version", name="uq_bounty_policies_repository_version"
        ),
        UniqueConstraint(
            "repository_id",
            "policy_hash",
            name="uq_bounty_policies_repository_hash",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    organization_id: Mapped[int] = mapped_column(
        ForeignKey("organizations.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    repository_id: Mapped[int] = mapped_column(
        ForeignKey("repositories.id", ondelete="CASCADE"), nullable=False, index=True
    )
    version: Mapped[str] = mapped_column(String(128), nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    rules: Mapped[dict] = mapped_column(JSON, nullable=False)
    policy_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    created_by_user_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, nullable=False
    )

    repository = relationship(
        "Repository", back_populates="bounty_policies", foreign_keys=[repository_id]
    )
    bounties = relationship("Bounty", back_populates="bounty_policy")


class Issue(Base):
    __tablename__ = "issues"
    __table_args__ = (
        UniqueConstraint(
            "repository_id", "github_issue_id", name="uq_issues_repository_github_id"
        ),
        UniqueConstraint(
            "repository_id", "number", name="uq_issues_repository_number"
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    organization_id: Mapped[int] = mapped_column(
        ForeignKey("organizations.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    repository_id: Mapped[int] = mapped_column(
        ForeignKey("repositories.id", ondelete="CASCADE"), nullable=False, index=True
    )
    github_issue_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    number: Mapped[int] = mapped_column(Integer, nullable=False)
    title: Mapped[str] = mapped_column(String(512), nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    url: Mapped[Optional[str]] = mapped_column(String(2048), nullable=True)
    state: Mapped[IssueState] = mapped_column(
        enum_column(IssueState, "issuestate"), nullable=False, index=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False
    )

    repository = relationship("Repository", back_populates="issues")
    bounties = relationship("Bounty", back_populates="issue")


class Bounty(Base):
    __tablename__ = "bounties"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    organization_id: Mapped[int] = mapped_column(
        ForeignKey("organizations.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    repository_id: Mapped[int] = mapped_column(
        ForeignKey("repositories.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    issue_id: Mapped[int] = mapped_column(
        ForeignKey("issues.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    bounty_policy_id: Mapped[int] = mapped_column(
        ForeignKey("bounty_policies.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    eligibility_policy_id: Mapped[int] = mapped_column(
        ForeignKey("repository_policies.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    amount: Mapped[Decimal] = mapped_column(Numeric(18, 6), nullable=False)
    currency: Mapped[str] = mapped_column(String(16), nullable=False)
    status: Mapped[BountyStatus] = mapped_column(
        enum_column(BountyStatus, "bountystatus"), nullable=False, index=True
    )
    funding_status: Mapped[FundingStatus] = mapped_column(
        enum_column(FundingStatus, "fundingstatus"), nullable=False, index=True
    )
    expires_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    created_by_user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, nullable=False
    )

    repository = relationship("Repository", back_populates="bounties")
    issue = relationship("Issue", back_populates="bounties")
    bounty_policy = relationship("BountyPolicy", back_populates="bounties")
    eligibility_policy = relationship("RepositoryPolicy")
    assignments = relationship("BountyAssignment", back_populates="bounty")
    claims = relationship("Claim", back_populates="bounty")


class BountyAssignment(Base):
    __tablename__ = "bounty_assignments"
    __table_args__ = (
        Index(
            "uq_bounty_assignments_active_bounty",
            "bounty_id",
            unique=True,
            postgresql_where=text("status = 'active'"),
            sqlite_where=text("status = 'active'"),
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    bounty_id: Mapped[int] = mapped_column(
        ForeignKey("bounties.id", ondelete="CASCADE"), nullable=False, index=True
    )
    assignee_user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    pull_request_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("pull_requests.id", ondelete="SET NULL"), nullable=True, index=True
    )
    status: Mapped[AssignmentStatus] = mapped_column(
        enum_column(AssignmentStatus, "assignmentstatus"),
        nullable=False,
        index=True,
    )
    assigned_by_user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    assigned_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, nullable=False
    )
    completed_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)

    bounty = relationship("Bounty", back_populates="assignments")
    assignee = relationship("User", foreign_keys=[assignee_user_id])
    pull_request = relationship("PullRequest")


class Wallet(Base):
    __tablename__ = "wallets"
    __table_args__ = (
        UniqueConstraint(
            "user_id", "chain", "normalized_address", name="uq_wallets_user_chain_address"
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    chain: Mapped[str] = mapped_column(String(64), nullable=False)
    address: Mapped[str] = mapped_column(String(255), nullable=False)
    normalized_address: Mapped[str] = mapped_column(String(255), nullable=False)
    status: Mapped[WalletStatus] = mapped_column(
        enum_column(WalletStatus, "walletstatus"), nullable=False, index=True
    )
    verified: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, nullable=False
    )


class Claim(Base):
    __tablename__ = "claims"
    __table_args__ = (
        Index(
            "uq_claims_payable_bounty",
            "bounty_id",
            unique=True,
            postgresql_where=text("status IN ('approved', 'paid')"),
            sqlite_where=text("status IN ('approved', 'paid')"),
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    bounty_id: Mapped[int] = mapped_column(
        ForeignKey("bounties.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    assignment_id: Mapped[int] = mapped_column(
        ForeignKey("bounty_assignments.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    pull_request_id: Mapped[int] = mapped_column(
        ForeignKey("pull_requests.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    eligibility_decision_id: Mapped[int] = mapped_column(
        ForeignKey("eligibility_decisions.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    approval_id: Mapped[int] = mapped_column(
        ForeignKey("approvals.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    claimant_user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    wallet_id: Mapped[int] = mapped_column(
        ForeignKey("wallets.id", ondelete="RESTRICT"), nullable=False
    )
    amount: Mapped[Decimal] = mapped_column(Numeric(18, 6), nullable=False)
    currency: Mapped[str] = mapped_column(String(16), nullable=False)
    destination_chain: Mapped[str] = mapped_column(String(64), nullable=False)
    destination_address: Mapped[str] = mapped_column(String(255), nullable=False)
    status: Mapped[ClaimStatus] = mapped_column(
        enum_column(ClaimStatus, "claimstatus"), nullable=False, index=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, nullable=False
    )

    bounty = relationship("Bounty", back_populates="claims")
    assignment = relationship("BountyAssignment")
    pull_request = relationship("PullRequest")
    eligibility_decision = relationship("EligibilityDecision")
    approval = relationship("Approval")
    wallet = relationship("Wallet")
    payouts = relationship("Payout", back_populates="claim")


class Payout(Base):
    __tablename__ = "payouts"
    __table_args__ = (
        UniqueConstraint("claim_id", name="uq_payouts_claim"),
        UniqueConstraint("idempotency_key", name="uq_payouts_idempotency_key"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    claim_id: Mapped[int] = mapped_column(
        ForeignKey("claims.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    approval_id: Mapped[int] = mapped_column(
        ForeignKey("approvals.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    amount: Mapped[Decimal] = mapped_column(Numeric(18, 6), nullable=False)
    currency: Mapped[str] = mapped_column(String(16), nullable=False)
    destination_chain: Mapped[str] = mapped_column(String(64), nullable=False)
    destination_address: Mapped[str] = mapped_column(String(255), nullable=False)
    idempotency_key: Mapped[str] = mapped_column(String(128), nullable=False)
    treasury_account_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("treasury_accounts.id", ondelete="RESTRICT"),
        nullable=True,
        index=True,
    )
    provider_key: Mapped[Optional[str]] = mapped_column(
        String(64), nullable=True, index=True
    )
    provider_reference: Mapped[Optional[str]] = mapped_column(
        String(255), nullable=True, index=True
    )
    state: Mapped[PayoutState] = mapped_column(
        enum_column(PayoutState, "payoutstate"), nullable=False, index=True
    )
    authorized_by_user_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    authorized_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    transaction_hash: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    explorer_url: Mapped[Optional[str]] = mapped_column(String(2048), nullable=True)
    required_confirmations: Mapped[int] = mapped_column(
        Integer, default=1, nullable=False
    )
    observed_confirmations: Mapped[int] = mapped_column(
        Integer, default=0, nullable=False
    )
    last_status_checked_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime, nullable=True
    )
    next_reconciliation_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime, nullable=True, index=True
    )
    confirmed_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    failure_reason: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False
    )

    claim = relationship("Claim", back_populates="payouts")
    approval = relationship("Approval")
    treasury_account = relationship("TreasuryAccount", back_populates="payouts")
    attempts = relationship("PayoutAttempt", back_populates="payout")


class PayoutAttempt(Base):
    __tablename__ = "payout_attempts"
    __table_args__ = (
        UniqueConstraint(
            "payout_id", "attempt_number", name="uq_payout_attempts_number"
        ),
        UniqueConstraint(
            "idempotency_key", name="uq_payout_attempts_idempotency_key"
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    payout_id: Mapped[int] = mapped_column(
        ForeignKey("payouts.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    attempt_number: Mapped[int] = mapped_column(Integer, nullable=False)
    idempotency_key: Mapped[str] = mapped_column(String(128), nullable=False)
    state: Mapped[PayoutAttemptState] = mapped_column(
        enum_column(PayoutAttemptState, "payoutattemptstate"),
        nullable=False,
        index=True,
    )
    provider: Mapped[str] = mapped_column(String(64), nullable=False)
    request_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    provider_reference: Mapped[Optional[str]] = mapped_column(
        String(255), nullable=True, index=True
    )
    transaction_hash: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    explorer_url: Mapped[Optional[str]] = mapped_column(String(2048), nullable=True)
    simulation_result: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    provider_response: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    last_checked_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    recovery_attempt_count: Mapped[int] = mapped_column(
        Integer, default=0, nullable=False
    )
    error: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, nullable=False
    )
    submitted_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    completed_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)

    payout = relationship("Payout", back_populates="attempts")


def _prevent_change(mapper, connection, target) -> None:
    raise ImmutableRecordError(f"{type(target).__name__} records are insert-only")


def _protect_payout_snapshot(mapper, connection, target: Payout) -> None:
    state = inspect(target)
    immutable_fields = (
        "claim_id",
        "approval_id",
        "amount",
        "currency",
        "destination_chain",
        "destination_address",
        "idempotency_key",
        "treasury_account_id",
        "provider_key",
        "required_confirmations",
    )
    if any(state.attrs[field].history.has_changes() for field in immutable_fields):
        raise ImmutableRecordError("Payout authorization snapshot is immutable")


def _protect_claim_snapshot(mapper, connection, target: Claim) -> None:
    state = inspect(target)
    immutable_fields = (
        "bounty_id",
        "assignment_id",
        "pull_request_id",
        "eligibility_decision_id",
        "approval_id",
        "claimant_user_id",
        "wallet_id",
        "amount",
        "currency",
        "destination_chain",
        "destination_address",
    )
    if any(state.attrs[field].history.has_changes() for field in immutable_fields):
        raise ImmutableRecordError("Claim authorization snapshot is immutable")


def _protect_terminal_attempt(mapper, connection, target: PayoutAttempt) -> None:
    history = inspect(target).attrs.state.history
    previous = history.deleted[0] if history.deleted else target.state
    if previous in {PayoutAttemptState.SUBMITTED, PayoutAttemptState.FAILED}:
        raise ImmutableRecordError("Terminal payout attempts are immutable")


event.listen(BountyPolicy, "before_update", _prevent_change)
event.listen(BountyPolicy, "before_delete", _prevent_change)
event.listen(Claim, "before_update", _protect_claim_snapshot)
event.listen(Claim, "before_delete", _prevent_change)

event.listen(Payout, "before_update", _protect_payout_snapshot)
event.listen(Payout, "before_delete", _prevent_change)
event.listen(PayoutAttempt, "before_update", _protect_terminal_attempt)
event.listen(PayoutAttempt, "before_delete", _protect_terminal_attempt)
