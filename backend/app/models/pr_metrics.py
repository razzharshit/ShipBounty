from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, JSON, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


class PRMetrics(Base):
    __tablename__ = "pr_metrics"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    pr_id: Mapped[int] = mapped_column(ForeignKey("pull_requests.id"), nullable=False, unique=True, index=True)
    total_files: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    total_additions: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    total_deletions: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    has_tests: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    has_docs: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    language_breakdown: Mapped[dict[str, int]] = mapped_column(JSON, default=dict, nullable=False)
    analysis_version: Mapped[str] = mapped_column(String(64), default="v1", nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime,
        default=datetime.utcnow,
        onupdate=datetime.utcnow,
        nullable=False,
    )

    pull_request = relationship("PullRequest", back_populates="metrics")
