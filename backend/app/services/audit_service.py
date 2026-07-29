from __future__ import annotations

from typing import Any

from fastapi import Request
from sqlalchemy.orm import Session

from app.models.authorization import AuditLog


def record_audit_event(
    db: Session,
    *,
    action: str,
    resource_type: str,
    actor_user_id: int | None = None,
    organization_id: int | None = None,
    repository_id: int | None = None,
    resource_id: str | int | None = None,
    event_metadata: dict[str, Any] | None = None,
    request: Request | None = None,
) -> AuditLog:
    event = AuditLog(
        action=action,
        resource_type=resource_type,
        actor_user_id=actor_user_id,
        organization_id=organization_id,
        repository_id=repository_id,
        resource_id=str(resource_id) if resource_id is not None else None,
        event_metadata=event_metadata or {},
        request_id=request.headers.get("X-Request-ID") if request else None,
        ip_address=(
            request.client.host if request and request.client else None
        ),
        user_agent=(
            (request.headers.get("User-Agent") or "")[:512] or None
            if request
            else None
        ),
    )
    db.add(event)
    return event
