from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


class PullRequestFile(Base):
    __tablename__ = "pull_request_files"
    __table_args__ = (UniqueConstraint("pr_id", "filename", name="uq_pull_request_files_pr_filename"),)

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    pr_id: Mapped[int] = mapped_column(ForeignKey("pull_requests.id"), nullable=False, index=True)
    filename: Mapped[str] = mapped_column(String(1024), nullable=False)
    previous_filename: Mapped[Optional[str]] = mapped_column(String(1024), nullable=True)
    github_status: Mapped[str] = mapped_column(String(32), default="modified", nullable=False)
    sha: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    additions: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    deletions: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    changes: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    patch: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    patch_available: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    patch_status: Mapped[str] = mapped_column(String(32), default="not_returned", nullable=False)
    contents_url: Mapped[Optional[str]] = mapped_column(String(2048), nullable=True)
    blob_url: Mapped[Optional[str]] = mapped_column(String(2048), nullable=True)
    raw_url: Mapped[Optional[str]] = mapped_column(String(2048), nullable=True)
    first_seen_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)
    last_seen_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)
    is_current: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False, index=True)
    removed_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)

    pull_request = relationship("PullRequest", back_populates="file_history")
