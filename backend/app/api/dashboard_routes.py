from __future__ import annotations

from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session

from app.api.authz import effective_repository_role, get_current_user
from app.core.config import settings
from app.db.session import get_db
from app.models.authorization import (
    AuthorizationRole,
    Organization,
    OrganizationMembership,
)
from app.models.notification import Notification
from app.models.operations import WorkerHeartbeat
from app.models.repository import Repository
from app.models.user import User
from app.models.webhook_delivery import WebhookDelivery
from app.schemas.dashboard import (
    NotificationRead,
    OperationsDashboardRead,
    PlatformWorkerHeartbeatRead,
    ProductAnalyticsRead,
    UnresolvedDeliveryRead,
)
from app.services.dashboard_service import operations_dashboard, product_analytics
from app.services.audit_service import record_audit_event


router = APIRouter(tags=["dashboards-and-notifications"])


def _require_platform_admin(user: User) -> None:
    allowed_ids = {
        value.strip()
        for value in settings.PLATFORM_ADMIN_GITHUB_IDS.split(",")
        if value.strip()
    }
    if str(user.github_id) not in allowed_ids:
        # Do not disclose that the platform operations surface exists.
        raise HTTPException(status_code=404, detail="Not found")


def _membership(
    db: Session, organization_id: int, user_id: int
) -> OrganizationMembership | None:
    return (
        db.query(OrganizationMembership)
        .filter(
            OrganizationMembership.organization_id == organization_id,
            OrganizationMembership.user_id == user_id,
            OrganizationMembership.is_active.is_(True),
            OrganizationMembership.github_verified.is_(True),
        )
        .first()
    )


def _organization(db: Session, organization_id: int) -> Organization:
    organization = db.get(Organization, organization_id)
    if organization is None:
        raise HTTPException(status_code=404, detail="Organization not found")
    return organization


@router.get(
    "/organizations/{organization_id}/operations-dashboard",
    response_model=OperationsDashboardRead,
)
def get_operations_dashboard(
    organization_id: int,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    _organization(db, organization_id)
    membership = _membership(db, organization_id, user.id)
    if membership is None or membership.role not in {
        AuthorizationRole.OWNER,
        AuthorizationRole.ADMIN,
    }:
        raise HTTPException(status_code=404, detail="Organization not found")
    return operations_dashboard(db, organization_id)


@router.get(
    "/organizations/{organization_id}/product-analytics",
    response_model=ProductAnalyticsRead,
)
def get_product_analytics(
    organization_id: int,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    organization = _organization(db, organization_id)
    repositories = (
        db.query(Repository)
        .filter(Repository.organization_id == organization_id)
        .all()
    )
    repository_ids = [
        repository.id
        for repository in repositories
        if effective_repository_role(db, user.id, repository) is not None
    ]
    if not repository_ids and _membership(db, organization_id, user.id) is None:
        raise HTTPException(status_code=404, detail="Organization not found")
    return product_analytics(db, organization, repository_ids)


@router.get(
    "/platform/operations/unresolved-deliveries",
    response_model=list[UnresolvedDeliveryRead],
)
def get_unresolved_deliveries(
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    _require_platform_admin(user)
    deliveries = (
        db.query(WebhookDelivery)
        .filter(WebhookDelivery.organization_id.is_(None))
        .order_by(
            WebhookDelivery.received_at.desc(),
            WebhookDelivery.id.desc(),
        )
        .limit(250)
        .all()
    )
    return [
        {
            "id": item.id,
            "delivery_id": item.delivery_id,
            "event_type": item.event_type,
            "action": item.action,
            "installation_id": item.installation_id,
            "repository_id": item.repository_id,
            "repository_full_name": item.repository_full_name,
            "repository_owner_login": item.repository_owner_login,
            "status": item.status.value,
            "received_at": item.received_at,
            "last_error": item.last_error,
        }
        for item in deliveries
    ]


@router.get(
    "/platform/operations/workers",
    response_model=list[PlatformWorkerHeartbeatRead],
)
def get_platform_workers(
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    _require_platform_admin(user)
    stale_cutoff = datetime.utcnow() - timedelta(seconds=90)
    workers = (
        db.query(WorkerHeartbeat)
        .order_by(
            WorkerHeartbeat.last_seen_at.desc(),
            WorkerHeartbeat.worker_id,
        )
        .all()
    )
    return [
        {
            "worker_id": item.worker_id,
            "queues": item.queues,
            "status": item.status,
            "active_tasks": item.active_tasks,
            "last_seen_at": item.last_seen_at,
            "is_stale": item.last_seen_at < stale_cutoff,
            "worker_metadata": item.worker_metadata,
            "first_seen_at": item.first_seen_at,
        }
        for item in workers
    ]


@router.get("/notifications", response_model=list[NotificationRead])
def get_notifications(
    unread_only: bool = False,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    query = db.query(Notification).filter(
        Notification.recipient_user_id == user.id
    )
    if unread_only:
        query = query.filter(Notification.read_at.is_(None))
    return query.order_by(
        Notification.created_at.desc(), Notification.id.desc()
    ).limit(100).all()


@router.post(
    "/notifications/{notification_id}/read",
    response_model=NotificationRead,
)
def mark_notification_read(
    notification_id: int,
    request: Request,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    notification = db.get(Notification, notification_id)
    if (
        notification is None
        or notification.recipient_user_id != user.id
    ):
        raise HTTPException(status_code=404, detail="Notification not found")
    if notification.read_at is None:
        notification.read_at = datetime.utcnow()
        record_audit_event(
            db,
            action="notification.read",
            resource_type="notification",
            actor_user_id=user.id,
            organization_id=notification.event.organization_id,
            repository_id=notification.event.repository_id,
            resource_id=notification.id,
            event_metadata={"channel": notification.channel.value},
            request=request,
        )
        db.commit()
    return notification
