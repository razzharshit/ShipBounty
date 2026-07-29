from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy import (
    BigInteger,
    DateTime,
    ForeignKey,
    Integer,
    JSON,
    String,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class WorkerHeartbeat(Base):
    __tablename__ = "worker_heartbeats"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    worker_id: Mapped[str] = mapped_column(
        String(255), unique=True, nullable=False, index=True
    )
    queues: Mapped[list] = mapped_column(JSON, default=list, nullable=False)
    status: Mapped[str] = mapped_column(String(32), default="online", nullable=False)
    active_tasks: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    worker_metadata: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    first_seen_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, nullable=False
    )
    last_seen_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, nullable=False, index=True
    )


class GitHubRateLimitSnapshot(Base):
    __tablename__ = "github_rate_limit_snapshots"
    __table_args__ = (
        UniqueConstraint(
            "installation_id",
            "resource",
            name="uq_github_rate_limits_installation_resource",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    installation_id: Mapped[int] = mapped_column(
        BigInteger, nullable=False, index=True
    )
    organization_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )
    repository_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("repositories.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )
    resource: Mapped[str] = mapped_column(String(64), nullable=False)
    limit: Mapped[int] = mapped_column(Integer, nullable=False)
    remaining: Mapped[int] = mapped_column(Integer, nullable=False)
    used: Mapped[int] = mapped_column(Integer, nullable=False)
    reset_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    observed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=datetime.utcnow, nullable=False, index=True
    )
