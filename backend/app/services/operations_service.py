from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app.db.session import SessionLocal
from app.models.operations import GitHubRateLimitSnapshot, WorkerHeartbeat
from app.models.webhook_delivery import IngestionState, WebhookDelivery


def record_worker_heartbeat(
    worker_id: str,
    *,
    queues: list[str],
    worker_metadata: dict | None = None,
) -> WorkerHeartbeat:
    db: Session = SessionLocal()
    try:
        heartbeat = (
            db.query(WorkerHeartbeat)
            .filter(WorkerHeartbeat.worker_id == worker_id)
            .first()
        )
        active_tasks = (
            db.query(WebhookDelivery)
            .filter(WebhookDelivery.status == IngestionState.PROCESSING)
            .count()
        )
        if heartbeat is None:
            heartbeat = WorkerHeartbeat(
                worker_id=worker_id,
                queues=queues,
                status="online",
                active_tasks=active_tasks,
                worker_metadata=worker_metadata or {},
            )
            db.add(heartbeat)
        else:
            heartbeat.queues = queues
            heartbeat.status = "online"
            heartbeat.active_tasks = active_tasks
            heartbeat.worker_metadata = worker_metadata or heartbeat.worker_metadata
            heartbeat.last_seen_at = datetime.utcnow()
        db.commit()
        db.refresh(heartbeat)
        return heartbeat
    finally:
        db.close()


def record_github_rate_limit(
    *,
    installation_id: int,
    organization_id: int | None,
    repository_id: int | None,
    headers,
) -> None:
    required = (
        headers.get("X-RateLimit-Limit"),
        headers.get("X-RateLimit-Remaining"),
        headers.get("X-RateLimit-Used"),
        headers.get("X-RateLimit-Reset"),
    )
    if any(value is None for value in required):
        return
    resource = headers.get("X-RateLimit-Resource") or "core"
    try:
        limit, remaining, used, reset_epoch = (int(value) for value in required)
    except (TypeError, ValueError):
        return
    db: Session = SessionLocal()
    try:
        snapshot = (
            db.query(GitHubRateLimitSnapshot)
            .filter(
                GitHubRateLimitSnapshot.installation_id == installation_id,
                GitHubRateLimitSnapshot.resource == resource,
            )
            .first()
        )
        if snapshot is None:
            snapshot = GitHubRateLimitSnapshot(
                installation_id=installation_id,
                resource=resource,
                limit=limit,
                remaining=remaining,
                used=used,
                reset_at=datetime.fromtimestamp(reset_epoch, tz=timezone.utc),
                organization_id=organization_id,
                repository_id=repository_id,
            )
            db.add(snapshot)
        else:
            snapshot.limit = limit
            snapshot.remaining = remaining
            snapshot.used = used
            snapshot.reset_at = datetime.fromtimestamp(
                reset_epoch, tz=timezone.utc
            )
            snapshot.organization_id = organization_id
            snapshot.repository_id = repository_id
            snapshot.observed_at = datetime.now(timezone.utc)
        db.commit()
    finally:
        db.close()
