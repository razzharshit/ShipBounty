from datetime import datetime
from enum import Enum

from typing import Optional

from sqlalchemy import BigInteger, Boolean, DateTime, Enum as SQLEnum, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


class PullRequestState(str, Enum):
    DRAFT = "draft"
    OPEN = "open"
    CLOSED = "closed"
    MERGED = "merged"


class ReviewState(str, Enum):
    NOT_REQUESTED = "not_requested"
    UNDER_REVIEW = "under_review"
    CHANGES_REQUESTED = "changes_requested"
    APPROVED = "approved"


class EligibilityState(str, Enum):
    NOT_EVALUATED = "not_evaluated"
    INELIGIBLE = "ineligible"
    ELIGIBLE = "eligible"
    CLAIMED = "claimed"
    PAID = "paid"


class PullRequest(Base):
    __tablename__ = "pull_requests"
    __table_args__ = (
        UniqueConstraint(
            "repo_id",
            "github_pr_number",
            name="uq_pull_requests_repo_github_pr_number",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    github_pr_id: Mapped[int] = mapped_column(BigInteger, unique=True, nullable=False, index=True)
    github_pr_number: Mapped[Optional[int]] = mapped_column(
        Integer, nullable=True, index=True
    )
    title: Mapped[str] = mapped_column(String(512), nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    author_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False, index=True)
    repo_id: Mapped[int] = mapped_column(ForeignKey("repositories.id"), nullable=False, index=True)
    state: Mapped[PullRequestState] = mapped_column(
        SQLEnum(
            PullRequestState,
            name="pullrequeststate",
            values_callable=lambda enum_cls: [item.value for item in enum_cls],
        ),
        default=PullRequestState.OPEN,
        nullable=False,
    )
    review_state: Mapped[ReviewState] = mapped_column(
        SQLEnum(
            ReviewState,
            name="reviewstate",
            values_callable=lambda enum_cls: [item.value for item in enum_cls],
        ),
        default=ReviewState.NOT_REQUESTED,
        nullable=False,
    )
    eligibility_state: Mapped[EligibilityState] = mapped_column(
        SQLEnum(
            EligibilityState,
            name="eligibilitystate",
            values_callable=lambda enum_cls: [item.value for item in enum_cls],
        ),
        default=EligibilityState.NOT_EVALUATED,
        nullable=False,
    )
    additions: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    deletions: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    changed_files: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    github_updated_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    github_created_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    merged_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    head_sha: Mapped[Optional[str]] = mapped_column(String(64), nullable=True, index=True)
    last_processed_delivery_id: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    last_synchronized_head_sha: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    file_sync_complete: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    incomplete_reason: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    synchronized_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    latest_score_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey(
            "scores.id",
            name="fk_pull_requests_latest_score_id",
            ondelete="SET NULL",
            use_alter=True,
        ),
        nullable=True,
        index=True,
    )
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)

    author = relationship("User", back_populates="pull_requests")
    repository = relationship("Repository", back_populates="pull_requests")
    scores = relationship(
        "Score",
        back_populates="pull_request",
        foreign_keys="Score.pr_id",
    )
    latest_score = relationship(
        "Score",
        foreign_keys=[latest_score_id],
        post_update=True,
    )
    files = relationship(
        "PullRequestFile",
        primaryjoin=(
            "and_(PullRequest.id == PullRequestFile.pr_id, "
            "PullRequestFile.is_current.is_(True))"
        ),
        viewonly=True,
    )
    file_history = relationship("PullRequestFile", back_populates="pull_request")
    metrics = relationship("PRMetrics", back_populates="pull_request", uselist=False)
    analysis_runs = relationship("AnalysisRun", back_populates="pull_request")
    eligibility_decisions = relationship(
        "EligibilityDecision", back_populates="pull_request"
    )
    ai_reviews = relationship("AIReview", back_populates="pull_request")
