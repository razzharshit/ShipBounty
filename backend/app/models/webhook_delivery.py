from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Optional

from sqlalchemy import BigInteger, DateTime, Enum as SQLEnum, ForeignKey, Integer, JSON, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


class IngestionState(str, Enum):
    RECEIVED = "received"
    QUEUED = "queued"
    PROCESSING = "processing"
    COMPLETE = "complete"
    INCOMPLETE = "incomplete"
    FAILED = "failed"


class WebhookDelivery(Base):
    __tablename__ = "webhook_deliveries"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    delivery_id: Mapped[str] = mapped_column(String(255), unique=True, nullable=False, index=True)
    event_type: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    action: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    installation_id: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True, index=True)
    repository_id: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True, index=True)
    repository_full_name: Mapped[Optional[str]] = mapped_column(
        String(512), nullable=True, index=True
    )
    repository_owner_login: Mapped[Optional[str]] = mapped_column(
        String(255), nullable=True, index=True
    )
    organization_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("organizations.id", ondelete="SET NULL"), nullable=True, index=True
    )
    repository_pk: Mapped[Optional[int]] = mapped_column(
        ForeignKey("repositories.id", ondelete="SET NULL"), nullable=True, index=True
    )
    payload: Mapped[dict] = mapped_column(
        JSON().with_variant(JSONB(), "postgresql"),
        nullable=False,
    )
    payload_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[IngestionState] = mapped_column(
        SQLEnum(
            IngestionState,
            name="ingestionstate",
            values_callable=lambda enum_cls: [item.value for item in enum_cls],
        ),
        default=IngestionState.RECEIVED,
        nullable=False,
        index=True,
    )
    attempt_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    last_error: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    incomplete_reason: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    received_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)
    started_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    completed_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    next_retry_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True, index=True)

    outbox_message = relationship(
        "WebhookOutbox",
        back_populates="delivery",
        uselist=False,
        cascade="all, delete-orphan",
    )
    analysis_runs = relationship("AnalysisRun", back_populates="delivery")
