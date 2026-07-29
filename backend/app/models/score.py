from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Optional

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    JSON,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    event,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


class ImmutableRecordError(RuntimeError):
    pass


class ScoreVersion(Base):
    __tablename__ = "score_versions"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    version: Mapped[str] = mapped_column(String(128), unique=True, nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    weights: Mapped[dict] = mapped_column(JSON, nullable=False)
    analyzer_weights: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    required_analyzers: Mapped[list] = mapped_column(JSON, default=list, nullable=False)
    settings: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    policy_hash: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    created_by_user_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)

    repositories = relationship("Repository", back_populates="scoring_policy")
    scores = relationship("Score", back_populates="score_version")


class Score(Base):
    __tablename__ = "scores"
    __table_args__ = (
        UniqueConstraint("analysis_run_id", name="uq_scores_analysis_run_id"),
        UniqueConstraint("deterministic_hash", name="uq_scores_deterministic_hash"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    pr_id: Mapped[int] = mapped_column(
        ForeignKey("pull_requests.id"), nullable=False, index=True
    )
    # Nullable only for preserved pre-Phase-3 legacy rows.
    analysis_run_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("analysis_runs.id", ondelete="CASCADE"), nullable=True, index=True
    )
    score_version_id: Mapped[int] = mapped_column(
        ForeignKey("score_versions.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    head_sha: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    analyzer_suite_version: Mapped[str] = mapped_column(String(128), nullable=False)
    scoring_policy_version: Mapped[str] = mapped_column(String(128), nullable=False)
    category_scores: Mapped[dict] = mapped_column(JSON, nullable=False)
    category_confidence: Mapped[dict] = mapped_column(JSON, nullable=False)
    unavailable_categories: Mapped[list] = mapped_column(JSON, default=list, nullable=False)
    final_score: Mapped[Decimal] = mapped_column(Numeric(5, 2), nullable=False)
    confidence: Mapped[Decimal] = mapped_column(Numeric(5, 4), nullable=False)
    input_complete: Mapped[bool] = mapped_column(Boolean, nullable=False)
    is_authoritative: Mapped[bool] = mapped_column(Boolean, nullable=False)
    explanation: Mapped[dict] = mapped_column(JSON, nullable=False)
    deterministic_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)

    pull_request = relationship(
        "PullRequest", back_populates="scores", foreign_keys=[pr_id]
    )
    analysis_run = relationship("AnalysisRun", back_populates="score")
    score_version = relationship("ScoreVersion", back_populates="scores")
    evidence = relationship(
        "ScoreEvidence", back_populates="score", cascade="all, delete-orphan"
    )


class ScoreEvidence(Base):
    __tablename__ = "score_evidence"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    score_id: Mapped[int] = mapped_column(
        ForeignKey("scores.id", ondelete="CASCADE"), nullable=False, index=True
    )
    analyzer_result_id: Mapped[int] = mapped_column(
        ForeignKey("analyzer_results.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    category: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    evidence_type: Mapped[str] = mapped_column(String(64), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    location: Mapped[Optional[str]] = mapped_column(String(2048), nullable=True)
    evidence_data: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    evidence_hash: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)

    score = relationship("Score", back_populates="evidence")
    analyzer_result = relationship("AnalyzerResult", back_populates="score_evidence")


def _prevent_immutable_change(mapper, connection, target) -> None:
    raise ImmutableRecordError(f"{type(target).__name__} records are insert-only")


for immutable_model in (Score, ScoreEvidence):
    event.listen(immutable_model, "before_update", _prevent_immutable_change)
    event.listen(immutable_model, "before_delete", _prevent_immutable_change)
