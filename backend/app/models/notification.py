from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Optional

from sqlalchemy import (
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
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.models.score import ImmutableRecordError


class NotificationChannel(str, Enum):
    IN_APP = "in_app"
    EMAIL = "email"


class NotificationStatus(str, Enum):
    PENDING = "pending"
    DELIVERED = "delivered"
    FAILED = "failed"


def _channel_column() -> SQLEnum:
    return SQLEnum(
        NotificationChannel,
        name="notificationchannel",
        values_callable=lambda enum_cls: [item.value for item in enum_cls],
    )


def _status_column() -> SQLEnum:
    return SQLEnum(
        NotificationStatus,
        name="notificationstatus",
        values_callable=lambda enum_cls: [item.value for item in enum_cls],
    )


class DomainEvent(Base):
    __tablename__ = "domain_events"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    event_type: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    organization_id: Mapped[int] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    repository_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("repositories.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )
    aggregate_type: Mapped[str] = mapped_column(String(64), nullable=False)
    aggregate_id: Mapped[str] = mapped_column(String(255), nullable=False)
    actor_user_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    payload: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    event_key: Mapped[str] = mapped_column(
        String(64), unique=True, nullable=False, index=True
    )
    occurred_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, nullable=False
    )

    notifications = relationship("Notification", back_populates="event")


class NotificationPolicy(Base):
    __tablename__ = "notification_policies"
    __table_args__ = (
        UniqueConstraint(
            "organization_id",
            "event_type",
            "channel",
            name="uq_notification_policies_org_event_channel",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    organization_id: Mapped[int] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    event_type: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    channel: Mapped[NotificationChannel] = mapped_column(
        _channel_column(), nullable=False, index=True
    )
    enabled: Mapped[bool] = mapped_column(default=True, nullable=False)
    max_attempts: Mapped[int] = mapped_column(Integer, default=5, nullable=False)
    configuration: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False
    )

    notifications = relationship("Notification", back_populates="policy")


class Notification(Base):
    __tablename__ = "notifications"
    __table_args__ = (
        UniqueConstraint(
            "event_id",
            "policy_id",
            "recipient_user_id",
            name="uq_notifications_event_policy_recipient",
        ),
        UniqueConstraint(
            "idempotency_key", name="uq_notifications_idempotency_key"
        ),
        Index("ix_notifications_delivery_due", "status", "next_retry_at"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    event_id: Mapped[int] = mapped_column(
        ForeignKey("domain_events.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    policy_id: Mapped[int] = mapped_column(
        ForeignKey("notification_policies.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    recipient_user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    channel: Mapped[NotificationChannel] = mapped_column(
        _channel_column(), nullable=False, index=True
    )
    destination: Mapped[Optional[str]] = mapped_column(String(512), nullable=True)
    status: Mapped[NotificationStatus] = mapped_column(
        _status_column(), nullable=False, index=True
    )
    subject: Mapped[str] = mapped_column(String(255), nullable=False)
    body: Mapped[str] = mapped_column(Text, nullable=False)
    payload: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    idempotency_key: Mapped[str] = mapped_column(String(64), nullable=False)
    attempt_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    last_error: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    next_retry_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime, nullable=True, index=True
    )
    delivered_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    read_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, nullable=False
    )

    event = relationship("DomainEvent", back_populates="notifications")
    policy = relationship("NotificationPolicy", back_populates="notifications")
    recipient = relationship("User")


def _prevent_event_change(mapper, connection, target) -> None:
    raise ImmutableRecordError("Domain events are insert-only")


event.listen(DomainEvent, "before_update", _prevent_event_change)
event.listen(DomainEvent, "before_delete", _prevent_event_change)
