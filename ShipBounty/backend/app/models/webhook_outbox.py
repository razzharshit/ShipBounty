from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Optional

from sqlalchemy import DateTime, Enum as SQLEnum, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


class OutboxState(str, Enum):
    PENDING = "pending"
    PUBLISHED = "published"
    FAILED = "failed"


class WebhookOutbox(Base):
    __tablename__ = "webhook_outbox"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    delivery_pk: Mapped[int] = mapped_column(
        ForeignKey("webhook_deliveries.id", ondelete="CASCADE"),
        unique=True,
        nullable=False,
        index=True,
    )
    task_name: Mapped[str] = mapped_column(
        String(255),
        default="app.worker.tasks.process_webhook_delivery",
        nullable=False,
    )
    status: Mapped[OutboxState] = mapped_column(
        SQLEnum(
            OutboxState,
            name="outboxstate",
            values_callable=lambda enum_cls: [item.value for item in enum_cls],
        ),
        default=OutboxState.PENDING,
        nullable=False,
        index=True,
    )
    attempt_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    last_error: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    available_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)
    published_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)

    delivery = relationship("WebhookDelivery", back_populates="outbox_message")
