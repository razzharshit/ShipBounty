from __future__ import annotations

import random
import smtplib
from datetime import datetime, timedelta
from email.message import EmailMessage
from typing import Protocol

from sqlalchemy.orm import Session

from app.analysis.base import stable_hash
from app.core.config import settings
from app.db.session import SessionLocal
from app.models.notification import (
    DomainEvent,
    Notification,
    NotificationChannel,
    NotificationPolicy,
    NotificationStatus,
)
from app.models.authorization import (
    AuthorizationRole,
    OrganizationMembership,
    RepositoryPermission,
)
from app.models.repository import Repository
from app.models.user import User


SUPPORTED_NOTIFICATION_EVENTS = {
    "pr.analysis_completed",
    "pr.analysis_failed",
    "review.requested",
    "review.changes_requested",
    "bounty.eligible",
    "ai_review.completed",
    "ai_review.failed",
    "claim.approved",
    "payout.submitted",
    "payout.confirmed",
    "payout.failed",
}


class NotificationAdapter(Protocol):
    channel: NotificationChannel

    def deliver(self, notification: Notification) -> None:
        ...


class InAppNotificationAdapter:
    channel = NotificationChannel.IN_APP

    def deliver(self, notification: Notification) -> None:
        return None


class EmailNotificationAdapter:
    channel = NotificationChannel.EMAIL

    def deliver(self, notification: Notification) -> None:
        if not settings.SMTP_HOST or not settings.SMTP_FROM_EMAIL:
            raise RuntimeError("Email delivery is not configured")
        if not notification.destination:
            raise RuntimeError("Recipient has no email address")
        message = EmailMessage()
        message["From"] = settings.SMTP_FROM_EMAIL
        message["To"] = notification.destination
        message["Subject"] = notification.subject
        message.set_content(notification.body)
        with smtplib.SMTP(
            settings.SMTP_HOST, settings.SMTP_PORT, timeout=20
        ) as client:
            if settings.SMTP_USE_TLS:
                client.starttls()
            if settings.SMTP_USERNAME:
                client.login(settings.SMTP_USERNAME, settings.SMTP_PASSWORD)
            client.send_message(message)


ADAPTERS: dict[NotificationChannel, NotificationAdapter] = {
    NotificationChannel.IN_APP: InAppNotificationAdapter(),
    NotificationChannel.EMAIL: EmailNotificationAdapter(),
}


def organization_admin_user_ids(db: Session, organization_id: int) -> list[int]:
    return [
        row[0]
        for row in (
            db.query(OrganizationMembership.user_id)
            .filter(
                OrganizationMembership.organization_id == organization_id,
                OrganizationMembership.is_active.is_(True),
                OrganizationMembership.github_verified.is_(True),
                OrganizationMembership.role.in_(
                    [AuthorizationRole.OWNER, AuthorizationRole.ADMIN]
                ),
            )
            .all()
        )
    ]


def repository_reviewer_user_ids(
    db: Session, repository: Repository
) -> list[int]:
    direct = [
        row[0]
        for row in (
            db.query(RepositoryPermission.user_id)
            .filter(
                RepositoryPermission.repository_id == repository.id,
                RepositoryPermission.role.in_(
                    [
                        AuthorizationRole.REVIEWER,
                        AuthorizationRole.MAINTAINER,
                        AuthorizationRole.ADMIN,
                        AuthorizationRole.OWNER,
                    ]
                ),
            )
            .all()
        )
    ]
    return sorted(
        set(
            direct
            + organization_admin_user_ids(db, repository.organization_id)
        )
    )


def _default_policy(
    db: Session,
    *,
    organization_id: int,
    event_type: str,
    channel: NotificationChannel,
) -> NotificationPolicy:
    policy = (
        db.query(NotificationPolicy)
        .filter(
            NotificationPolicy.organization_id == organization_id,
            NotificationPolicy.event_type == event_type,
            NotificationPolicy.channel == channel,
        )
        .first()
    )
    if policy is None:
        policy = NotificationPolicy(
            organization_id=organization_id,
            event_type=event_type,
            channel=channel,
            enabled=True,
            max_attempts=settings.NOTIFICATION_MAX_RETRIES,
            configuration={},
        )
        db.add(policy)
        db.flush()
    return policy


def _message(event_type: str, payload: dict) -> tuple[str, str]:
    repository = payload.get("repository") or "repository"
    pr_title = payload.get("pull_request_title")
    label = pr_title or payload.get("title") or repository
    messages = {
        "pr.analysis_completed": (
            "Pull request analysis completed",
            f"Deterministic analysis completed for {label}.",
        ),
        "pr.analysis_failed": (
            "Pull request analysis failed",
            f"Analysis failed for {label}: {payload.get('error') or 'Unknown error'}.",
        ),
        "review.requested": (
            "Review requested",
            f"A human review is requested for {label}.",
        ),
        "review.changes_requested": (
            "Changes requested",
            f"Changes were requested for {label}.",
        ),
        "bounty.eligible": (
            "Bounty eligible",
            f"{label} passed policy review and is eligible to claim.",
        ),
        "ai_review.completed": (
            "AI review completed",
            f"Advisory AI review completed for {label}.",
        ),
        "ai_review.failed": (
            "AI review failed",
            f"Advisory AI review failed for {label}: {payload.get('status') or 'Unknown error'}.",
        ),
        "claim.approved": (
            "Claim approved",
            f"Your claim for {label} was approved.",
        ),
        "payout.submitted": (
            "Payout submitted",
            f"The payout for {label} was submitted for confirmation.",
        ),
        "payout.confirmed": (
            "Payout confirmed",
            f"The payout for {label} was confirmed.",
        ),
        "payout.failed": (
            "Payout failed",
            f"The payout for {label} failed: {payload.get('error') or 'Unknown error'}.",
        ),
    }
    return messages[event_type]


def emit_domain_event(
    db: Session,
    *,
    event_type: str,
    organization_id: int,
    repository_id: int | None,
    aggregate_type: str,
    aggregate_id: int | str,
    event_identity: str,
    recipient_user_ids: list[int],
    payload: dict,
    actor_user_id: int | None = None,
) -> tuple[DomainEvent, bool]:
    if event_type not in SUPPORTED_NOTIFICATION_EVENTS:
        raise ValueError(f"Unsupported notification event: {event_type}")
    event_key = stable_hash(
        {
            "event_type": event_type,
            "aggregate_type": aggregate_type,
            "aggregate_id": str(aggregate_id),
            "event_identity": event_identity,
        }
    )
    existing = db.query(DomainEvent).filter(DomainEvent.event_key == event_key).first()
    if existing is not None:
        return existing, False
    domain_event = DomainEvent(
        event_type=event_type,
        organization_id=organization_id,
        repository_id=repository_id,
        aggregate_type=aggregate_type,
        aggregate_id=str(aggregate_id),
        actor_user_id=actor_user_id,
        payload=payload,
        event_key=event_key,
    )
    db.add(domain_event)
    db.flush()
    subject, body = _message(event_type, payload)
    users = (
        db.query(User)
        .filter(User.id.in_(sorted(set(recipient_user_ids))), User.is_active.is_(True))
        .all()
        if recipient_user_ids
        else []
    )
    for channel in NotificationChannel:
        policy = _default_policy(
            db,
            organization_id=organization_id,
            event_type=event_type,
            channel=channel,
        )
        if not policy.enabled:
            continue
        for user in users:
            destination = user.email if channel == NotificationChannel.EMAIL else None
            notification = Notification(
                event_id=domain_event.id,
                policy_id=policy.id,
                recipient_user_id=user.id,
                channel=channel,
                destination=destination,
                status=NotificationStatus.PENDING,
                subject=subject,
                body=body,
                payload=payload,
                idempotency_key=stable_hash(
                    {
                        "event_key": event_key,
                        "policy_id": policy.id,
                        "recipient_user_id": user.id,
                    }
                ),
                next_retry_at=datetime.utcnow(),
            )
            db.add(notification)
    db.flush()
    return domain_event, True


def _retry_delay(attempt_count: int) -> int:
    base = min(10 * (2 ** max(attempt_count - 1, 0)), 1800)
    return base + random.randint(0, max(base // 5, 1))


def deliver_notification_once(
    db: Session,
    notification: Notification,
    *,
    adapters: dict[NotificationChannel, NotificationAdapter] | None = None,
) -> bool:
    if notification.status == NotificationStatus.DELIVERED:
        return False
    adapter = (adapters or ADAPTERS)[notification.channel]
    notification.attempt_count += 1
    try:
        adapter.deliver(notification)
    except Exception as exc:
        notification.status = NotificationStatus.FAILED
        notification.last_error = str(exc)[:4000]
        notification.next_retry_at = (
            datetime.utcnow() + timedelta(
                seconds=_retry_delay(notification.attempt_count)
            )
            if notification.attempt_count < notification.policy.max_attempts
            else None
        )
        db.flush()
        return False
    notification.status = NotificationStatus.DELIVERED
    notification.last_error = None
    notification.next_retry_at = None
    notification.delivered_at = datetime.utcnow()
    db.flush()
    return True


def dispatch_pending_notifications() -> int:
    db: Session = SessionLocal()
    try:
        now = datetime.utcnow()
        candidates = (
            db.query(Notification)
            .filter(
                Notification.status.in_(
                    [NotificationStatus.PENDING, NotificationStatus.FAILED]
                ),
                Notification.next_retry_at.is_not(None),
                Notification.next_retry_at <= now,
            )
            .order_by(Notification.created_at)
            .limit(100)
            .with_for_update(skip_locked=True)
            .all()
        )
        delivered = sum(
            deliver_notification_once(db, notification)
            for notification in candidates
        )
        db.commit()
        return delivered
    finally:
        db.close()
