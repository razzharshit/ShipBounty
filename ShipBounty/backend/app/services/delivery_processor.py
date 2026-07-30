from __future__ import annotations

import logging
from datetime import datetime, timedelta
from typing import Optional, Tuple

from sqlalchemy import text
from sqlalchemy.engine import Connection
from sqlalchemy.orm import Session

from app.db.session import SessionLocal
from app.models.webhook_delivery import IngestionState, WebhookDelivery
from app.models.pull_request import PullRequest
from app.services.notification_service import (
    emit_domain_event,
    organization_admin_user_ids,
)
from app.services.webhook_sync_service import (
    IncompleteDeliveryError,
    synchronize_webhook_delivery,
)


logger = logging.getLogger(__name__)


def _emit_analysis_event(
    db: Session,
    delivery: WebhookDelivery,
    *,
    event_type: str,
    error: str | None = None,
) -> None:
    if delivery.organization_id is None:
        return
    pull_request = (
        db.query(PullRequest)
        .filter(PullRequest.last_processed_delivery_id == delivery.delivery_id)
        .first()
    )
    recipients = (
        [pull_request.author_id]
        if pull_request is not None
        else organization_admin_user_ids(db, delivery.organization_id)
    )
    emit_domain_event(
        db,
        event_type=event_type,
        organization_id=delivery.organization_id,
        repository_id=delivery.repository_pk,
        aggregate_type="webhook_delivery",
        aggregate_id=delivery.id,
        event_identity=f"{delivery.delivery_id}:{event_type}",
        recipient_user_ids=recipients,
        payload={
            "delivery_id": delivery.delivery_id,
            "pull_request_id": pull_request.id if pull_request else None,
            "pull_request_title": pull_request.title if pull_request else None,
            "repository": (
                pull_request.repository.full_name if pull_request else None
            ),
            "error": error,
        },
    )


def _acquire_delivery_lock(
    db: Session,
    delivery_pk: int,
) -> Tuple[Optional[Connection], bool]:
    bind = db.get_bind()
    if bind.dialect.name != "postgresql":
        return None, True

    connection = bind.connect()
    acquired = bool(
        connection.execute(
            text("SELECT pg_try_advisory_lock(:delivery_pk)"),
            {"delivery_pk": delivery_pk},
        ).scalar()
    )
    connection.commit()
    if not acquired:
        connection.close()
        return None, False
    return connection, True


def _release_delivery_lock(connection: Connection, delivery_pk: int) -> None:
    try:
        connection.execute(
            text("SELECT pg_advisory_unlock(:delivery_pk)"),
            {"delivery_pk": delivery_pk},
        )
        connection.commit()
    finally:
        connection.close()


def process_delivery_once(
    delivery_pk: int,
    *,
    next_retry_seconds: int | None,
) -> str:
    db: Session = SessionLocal()
    lock_connection: Optional[Connection] = None
    try:
        lock_connection, lock_acquired = _acquire_delivery_lock(db, delivery_pk)
        if not lock_acquired:
            logger.info("Delivery %s is already being processed by another worker", delivery_pk)
            return "already_processing"

        delivery = db.get(WebhookDelivery, delivery_pk)
        if delivery is None:
            logger.warning("Webhook delivery %s no longer exists", delivery_pk)
            return "missing"
        if delivery.status in {IngestionState.COMPLETE, IngestionState.INCOMPLETE}:
            return delivery.status.value

        delivery.status = IngestionState.PROCESSING
        delivery.attempt_count += 1
        delivery.started_at = datetime.utcnow()
        delivery.completed_at = None
        delivery.last_error = None
        delivery.incomplete_reason = None
        delivery.next_retry_at = None
        db.commit()

        try:
            result = synchronize_webhook_delivery(db, delivery)
        except IncompleteDeliveryError as exc:
            delivery = db.get(WebhookDelivery, delivery_pk)
            delivery.status = IngestionState.INCOMPLETE
            delivery.last_error = str(exc)[:4000]
            delivery.incomplete_reason = exc.reason.value
            delivery.completed_at = datetime.utcnow()
            delivery.next_retry_at = None
            _emit_analysis_event(
                db,
                delivery,
                event_type="pr.analysis_failed",
                error=str(exc)[:4000],
            )
            db.commit()
            return "incomplete"
        except Exception as exc:
            db.rollback()
            delivery = db.get(WebhookDelivery, delivery_pk)
            delivery.status = IngestionState.FAILED
            delivery.last_error = str(exc)[:4000]
            delivery.next_retry_at = (
                datetime.utcnow() + timedelta(seconds=next_retry_seconds)
                if next_retry_seconds is not None
                else None
            )
            _emit_analysis_event(
                db,
                delivery,
                event_type="pr.analysis_failed",
                error=str(exc)[:4000],
            )
            db.commit()
            raise

        delivery = db.get(WebhookDelivery, delivery_pk)
        delivery.status = IngestionState.COMPLETE
        delivery.completed_at = datetime.utcnow()
        delivery.last_error = None
        delivery.incomplete_reason = None
        delivery.next_retry_at = None
        _emit_analysis_event(
            db, delivery, event_type="pr.analysis_completed"
        )
        db.commit()
        return result
    finally:
        if lock_connection is not None:
            try:
                _release_delivery_lock(lock_connection, delivery_pk)
            except Exception:
                logger.exception("Failed to release advisory lock for delivery %s", delivery_pk)
        db.close()
