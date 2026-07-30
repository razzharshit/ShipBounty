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
    JSON,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    event,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


class AnalysisRunStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETE = "complete"
    INCOMPLETE = "incomplete"
    FAILED = "failed"


class AnalyzerResultStatus(str, Enum):
    AVAILABLE = "available"
    UNAVAILABLE = "unavailable"
    INCONCLUSIVE = "inconclusive"
    ERROR = "error"


class AnalyzerToolStatus(str, Enum):
    PASSED = "passed"
    FAILED = "failed"
    UNAVAILABLE = "unavailable"
    TIMED_OUT = "timed_out"
    TOOL_ERROR = "tool_error"


class AnalysisRun(Base):
    __tablename__ = "analysis_runs"
    __table_args__ = (
        UniqueConstraint("run_key", name="uq_analysis_runs_run_key"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    pr_id: Mapped[int] = mapped_column(
        ForeignKey("pull_requests.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    delivery_pk: Mapped[int] = mapped_column(
        ForeignKey("webhook_deliveries.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    # analysis_version remains as a compatibility alias for older reporting.
    analysis_version: Mapped[str] = mapped_column(String(64), nullable=False)
    analyzer_version: Mapped[str] = mapped_column(String(128), nullable=False)
    scoring_policy_version: Mapped[str] = mapped_column(String(128), nullable=False)
    run_key: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    input_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    analyzer_manifest: Mapped[list] = mapped_column(JSON, default=list, nullable=False)
    head_sha: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    status: Mapped[AnalysisRunStatus] = mapped_column(
        SQLEnum(
            AnalysisRunStatus,
            name="analysisrunstatus",
            values_callable=lambda enum_cls: [item.value for item in enum_cls],
        ),
        nullable=False,
    )
    input_complete: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    is_authoritative: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    incomplete_reason: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    metrics_snapshot: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)
    started_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)
    completed_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)

    pull_request = relationship("PullRequest", back_populates="analysis_runs")
    delivery = relationship("WebhookDelivery", back_populates="analysis_runs")
    analyzer_results = relationship(
        "AnalyzerResult", back_populates="analysis_run", cascade="all, delete-orphan"
    )
    score = relationship("Score", back_populates="analysis_run", uselist=False)


class AnalyzerResult(Base):
    __tablename__ = "analyzer_results"
    __table_args__ = (
        UniqueConstraint(
            "analysis_run_id",
            "analyzer_name",
            "analyzer_version",
            name="uq_analyzer_results_run_analyzer",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    analysis_run_id: Mapped[int] = mapped_column(
        ForeignKey("analysis_runs.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    analyzer_name: Mapped[str] = mapped_column(String(128), nullable=False)
    analyzer_version: Mapped[str] = mapped_column(String(64), nullable=False)
    category: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[AnalyzerResultStatus] = mapped_column(
        SQLEnum(
            AnalyzerResultStatus,
            name="analyzerresultstatus",
            values_callable=lambda enum_cls: [item.value for item in enum_cls],
        ),
        nullable=False,
    )
    score: Mapped[Optional[Decimal]] = mapped_column(Numeric(5, 2), nullable=True)
    confidence: Mapped[Decimal] = mapped_column(
        Numeric(5, 4), default=Decimal("0"), nullable=False
    )
    findings: Mapped[list] = mapped_column(JSON, default=list, nullable=False)
    evidence: Mapped[list] = mapped_column(JSON, default=list, nullable=False)
    errors: Mapped[list] = mapped_column(JSON, default=list, nullable=False)
    duration_ms: Mapped[int] = mapped_column(default=0, nullable=False)
    result_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)

    analysis_run = relationship("AnalysisRun", back_populates="analyzer_results")
    score_evidence = relationship("ScoreEvidence", back_populates="analyzer_result")
    raw_artifacts = relationship(
        "AnalyzerRawArtifact", back_populates="analyzer_result"
    )


class AnalyzerRawArtifact(Base):
    __tablename__ = "analyzer_raw_artifacts"
    __table_args__ = (
        UniqueConstraint(
            "analyzer_result_id",
            name="uq_analyzer_raw_artifacts_result",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    analyzer_result_id: Mapped[int] = mapped_column(
        ForeignKey("analyzer_results.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    tool_status: Mapped[AnalyzerToolStatus] = mapped_column(
        SQLEnum(
            AnalyzerToolStatus,
            name="analyzertoolstatus",
            values_callable=lambda enum_cls: [item.value for item in enum_cls],
        ),
        nullable=False,
        index=True,
    )
    command: Mapped[list] = mapped_column(JSON, nullable=False)
    image: Mapped[str] = mapped_column(String(512), nullable=False)
    exit_code: Mapped[Optional[int]] = mapped_column(nullable=True)
    stdout: Mapped[str] = mapped_column(Text, nullable=False)
    stderr: Mapped[str] = mapped_column(Text, nullable=False)
    output_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    duration_ms: Mapped[int] = mapped_column(nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, nullable=False
    )

    analyzer_result = relationship(
        "AnalyzerResult", back_populates="raw_artifacts"
    )


def _prevent_analyzer_result_change(mapper, connection, target) -> None:
    from app.models.score import ImmutableRecordError

    raise ImmutableRecordError("AnalyzerResult records are insert-only")


def _prevent_analyzer_raw_artifact_change(mapper, connection, target) -> None:
    from app.models.score import ImmutableRecordError

    raise ImmutableRecordError("AnalyzerRawArtifact records are insert-only")


event.listen(AnalyzerResult, "before_update", _prevent_analyzer_result_change)
event.listen(AnalyzerResult, "before_delete", _prevent_analyzer_result_change)
event.listen(
    AnalyzerRawArtifact,
    "before_update",
    _prevent_analyzer_raw_artifact_change,
)
event.listen(
    AnalyzerRawArtifact,
    "before_delete",
    _prevent_analyzer_raw_artifact_change,
)
