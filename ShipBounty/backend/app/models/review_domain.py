from __future__ import annotations

from datetime import datetime
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


class HumanReviewStatus(str, Enum):
    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    CANCELLED = "cancelled"


class ReviewRecommendation(str, Enum):
    APPROVE = "approve"
    REQUEST_CHANGES = "request_changes"
    REJECT = "reject"


class FindingSeverity(str, Enum):
    INFO = "info"
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class ApprovalOutcome(str, Enum):
    APPROVED = "approved"
    REJECTED = "rejected"


class EligibilityDecisionStatus(str, Enum):
    PENDING_REVIEW = "pending_review"
    CHANGES_REQUESTED = "changes_requested"
    PENDING_APPROVAL = "pending_approval"
    ELIGIBLE = "eligible"
    INELIGIBLE = "ineligible"
    SUPERSEDED = "superseded"


class RepositoryPolicy(Base):
    __tablename__ = "repository_policies"
    __table_args__ = (
        UniqueConstraint(
            "repository_id",
            "version",
            name="uq_repository_policies_repository_version",
        ),
        UniqueConstraint(
            "repository_id",
            "policy_hash",
            name="uq_repository_policies_repository_hash",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    repository_id: Mapped[int] = mapped_column(
        ForeignKey("repositories.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    version: Mapped[str] = mapped_column(String(128), nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    rules: Mapped[dict] = mapped_column(JSON, nullable=False)
    policy_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    created_by_user_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, nullable=False
    )

    repository = relationship(
        "Repository",
        back_populates="eligibility_policies",
        foreign_keys=[repository_id],
    )
    decisions = relationship("EligibilityDecision", back_populates="repository_policy")


class EligibilityDecision(Base):
    __tablename__ = "eligibility_decisions"
    __table_args__ = (
        Index(
            "uq_eligibility_decisions_current_pr",
            "pr_id",
            unique=True,
            postgresql_where=text("is_current"),
            sqlite_where=text("is_current = 1"),
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    pr_id: Mapped[int] = mapped_column(
        ForeignKey("pull_requests.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    score_id: Mapped[int] = mapped_column(
        ForeignKey("scores.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    score_version_id: Mapped[int] = mapped_column(
        ForeignKey("score_versions.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    repository_policy_id: Mapped[int] = mapped_column(
        ForeignKey("repository_policies.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    status: Mapped[EligibilityDecisionStatus] = mapped_column(
        SQLEnum(
            EligibilityDecisionStatus,
            name="eligibilitydecisionstatus",
            values_callable=lambda enum_cls: [item.value for item in enum_cls],
        ),
        nullable=False,
        index=True,
    )
    is_current: Mapped[bool] = mapped_column(
        Boolean, default=True, nullable=False, index=True
    )
    evaluation_result: Mapped[dict] = mapped_column(JSON, nullable=False)
    failure_reasons: Mapped[list] = mapped_column(JSON, default=list, nullable=False)
    requires_human_review: Mapped[bool] = mapped_column(Boolean, nullable=False)
    required_approvals: Mapped[int] = mapped_column(Integer, nullable=False)
    evaluation_hash: Mapped[str] = mapped_column(
        String(64), unique=True, nullable=False
    )
    evaluated_by_user_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    final_approved_by_user_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, nullable=False
    )
    finalized_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)

    pull_request = relationship("PullRequest", back_populates="eligibility_decisions")
    score = relationship("Score")
    score_version = relationship("ScoreVersion")
    repository_policy = relationship("RepositoryPolicy", back_populates="decisions")
    reviews = relationship(
        "Review", back_populates="eligibility_decision", cascade="all, delete-orphan"
    )
    approvals = relationship(
        "Approval",
        back_populates="eligibility_decision",
        cascade="all, delete-orphan",
    )
    final_approver = relationship(
        "User", foreign_keys=[final_approved_by_user_id]
    )


class Review(Base):
    __tablename__ = "reviews"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    eligibility_decision_id: Mapped[int] = mapped_column(
        ForeignKey("eligibility_decisions.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    reviewer_user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    status: Mapped[HumanReviewStatus] = mapped_column(
        SQLEnum(
            HumanReviewStatus,
            name="humanreviewstatus",
            values_callable=lambda enum_cls: [item.value for item in enum_cls],
        ),
        nullable=False,
        index=True,
    )
    recommendation: Mapped[Optional[ReviewRecommendation]] = mapped_column(
        SQLEnum(
            ReviewRecommendation,
            name="reviewrecommendation",
            values_callable=lambda enum_cls: [item.value for item in enum_cls],
        ),
        nullable=True,
    )
    summary: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    started_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, nullable=False
    )
    completed_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)

    eligibility_decision = relationship(
        "EligibilityDecision", back_populates="reviews"
    )
    reviewer = relationship("User")
    findings = relationship(
        "ReviewFinding", back_populates="review", cascade="all, delete-orphan"
    )


class ReviewFinding(Base):
    __tablename__ = "review_findings"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    review_id: Mapped[int] = mapped_column(
        ForeignKey("reviews.id", ondelete="CASCADE"), nullable=False, index=True
    )
    severity: Mapped[FindingSeverity] = mapped_column(
        SQLEnum(
            FindingSeverity,
            name="findingseverity",
            values_callable=lambda enum_cls: [item.value for item in enum_cls],
        ),
        nullable=False,
        index=True,
    )
    category: Mapped[str] = mapped_column(String(64), nullable=False)
    code: Mapped[str] = mapped_column(String(128), nullable=False)
    message: Mapped[str] = mapped_column(Text, nullable=False)
    evidence: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, nullable=False
    )

    review = relationship("Review", back_populates="findings")


class Approval(Base):
    __tablename__ = "approvals"
    __table_args__ = (
        UniqueConstraint(
            "eligibility_decision_id",
            "approver_user_id",
            name="uq_approvals_decision_approver",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    eligibility_decision_id: Mapped[int] = mapped_column(
        ForeignKey("eligibility_decisions.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    approver_user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    outcome: Mapped[ApprovalOutcome] = mapped_column(
        SQLEnum(
            ApprovalOutcome,
            name="approvaloutcome",
            values_callable=lambda enum_cls: [item.value for item in enum_cls],
        ),
        nullable=False,
        index=True,
    )
    reason: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    score_id: Mapped[int] = mapped_column(
        ForeignKey("scores.id", ondelete="RESTRICT"), nullable=False
    )
    score_version_id: Mapped[int] = mapped_column(
        ForeignKey("score_versions.id", ondelete="RESTRICT"), nullable=False
    )
    repository_policy_id: Mapped[int] = mapped_column(
        ForeignKey("repository_policies.id", ondelete="RESTRICT"), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, nullable=False
    )

    eligibility_decision = relationship(
        "EligibilityDecision", back_populates="approvals"
    )
    approver = relationship("User")


def _prevent_change(mapper, connection, target) -> None:
    raise ImmutableRecordError(f"{type(target).__name__} records are insert-only")


def _prevent_terminal_change(mapper, connection, target) -> None:
    history = inspect(target).attrs.status.history
    previous = history.deleted[0] if history.deleted else target.status
    terminal = {
        HumanReviewStatus.COMPLETED,
        HumanReviewStatus.CANCELLED,
    }
    if previous in terminal:
        raise ImmutableRecordError(
            f"Terminal {type(target).__name__} records are immutable"
        )


for immutable_model in (RepositoryPolicy, ReviewFinding, Approval):
    event.listen(immutable_model, "before_update", _prevent_change)
    event.listen(immutable_model, "before_delete", _prevent_change)

event.listen(Review, "before_update", _prevent_terminal_change)
event.listen(Review, "before_delete", _prevent_terminal_change)
