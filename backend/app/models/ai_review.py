from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from enum import Enum
from typing import Optional

from sqlalchemy import (
    Boolean,
    CheckConstraint,
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
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.models.score import ImmutableRecordError


class AIProviderKind(str, Enum):
    LOCAL = "local"
    EXTERNAL = "external"


class AIReviewStatus(str, Enum):
    PENDING = "pending"
    COMPLETE = "complete"
    FAILED = "failed"
    BLOCKED = "blocked"


class AIReviewPolicy(Base):
    __tablename__ = "ai_review_policies"
    __table_args__ = (
        UniqueConstraint(
            "repository_id", "version", name="uq_ai_review_policies_repository_version"
        ),
        UniqueConstraint(
            "repository_id",
            "policy_hash",
            name="uq_ai_review_policies_repository_hash",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
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
        "Repository",
        back_populates="ai_review_policies",
        foreign_keys=[repository_id],
    )
    reviews = relationship("AIReview", back_populates="ai_review_policy")


class AIReview(Base):
    __tablename__ = "ai_reviews"
    __table_args__ = (
        UniqueConstraint("review_key", name="uq_ai_reviews_review_key"),
        CheckConstraint("advisory_only", name="ck_ai_reviews_advisory_only"),
        Index("ix_ai_reviews_pr_status", "pr_id", "status"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    pr_id: Mapped[int] = mapped_column(
        ForeignKey("pull_requests.id", ondelete="CASCADE"), nullable=False, index=True
    )
    analysis_run_id: Mapped[int] = mapped_column(
        ForeignKey("analysis_runs.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    repository_policy_id: Mapped[int] = mapped_column(
        ForeignKey("repository_policies.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    ai_review_policy_id: Mapped[int] = mapped_column(
        ForeignKey("ai_review_policies.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    requested_by_user_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    provider: Mapped[str] = mapped_column(String(128), nullable=False)
    model: Mapped[str] = mapped_column(String(255), nullable=False)
    provider_kind: Mapped[AIProviderKind] = mapped_column(
        SQLEnum(
            AIProviderKind,
            name="aiproviderkind",
            values_callable=lambda enum_cls: [item.value for item in enum_cls],
        ),
        nullable=False,
    )
    prompt_version: Mapped[str] = mapped_column(String(128), nullable=False)
    input_commit_sha: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    input_snapshot: Mapped[dict] = mapped_column(JSON, nullable=False)
    input_hash: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    privacy_decision: Mapped[dict] = mapped_column(JSON, nullable=False)
    status: Mapped[AIReviewStatus] = mapped_column(
        SQLEnum(
            AIReviewStatus,
            name="aireviewstatus",
            values_callable=lambda enum_cls: [item.value for item in enum_cls],
        ),
        nullable=False,
        index=True,
    )
    output: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    provider_request_id: Mapped[Optional[str]] = mapped_column(
        String(255), nullable=True
    )
    prompt_tokens: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    completion_tokens: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    total_tokens: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    cost_amount: Mapped[Optional[Decimal]] = mapped_column(
        Numeric(18, 8), nullable=True
    )
    cost_currency: Mapped[Optional[str]] = mapped_column(String(16), nullable=True)
    moderation_result: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    failure_reason: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    advisory_only: Mapped[bool] = mapped_column(
        Boolean, default=True, nullable=False
    )
    review_key: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, nullable=False
    )
    completed_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)

    pull_request = relationship("PullRequest", back_populates="ai_reviews")
    analysis_run = relationship("AnalysisRun")
    repository_policy = relationship("RepositoryPolicy")
    ai_review_policy = relationship("AIReviewPolicy", back_populates="reviews")
    requested_by = relationship("User")


def _prevent_change(mapper, connection, target) -> None:
    raise ImmutableRecordError(f"{type(target).__name__} records are insert-only")


def _protect_ai_review(mapper, connection, target: AIReview) -> None:
    state = inspect(target)
    immutable_fields = (
        "pr_id",
        "analysis_run_id",
        "repository_policy_id",
        "ai_review_policy_id",
        "requested_by_user_id",
        "provider",
        "model",
        "provider_kind",
        "prompt_version",
        "input_commit_sha",
        "input_snapshot",
        "input_hash",
        "privacy_decision",
        "advisory_only",
        "review_key",
    )
    if any(state.attrs[field].history.has_changes() for field in immutable_fields):
        raise ImmutableRecordError("AI review provenance is immutable")
    status_history = state.attrs.status.history
    previous = status_history.deleted[0] if status_history.deleted else target.status
    if previous in {
        AIReviewStatus.COMPLETE,
        AIReviewStatus.FAILED,
        AIReviewStatus.BLOCKED,
    }:
        raise ImmutableRecordError("Terminal AI reviews are immutable")


event.listen(AIReviewPolicy, "before_update", _prevent_change)
event.listen(AIReviewPolicy, "before_delete", _prevent_change)
event.listen(AIReview, "before_update", _protect_ai_review)
event.listen(AIReview, "before_delete", _prevent_change)
