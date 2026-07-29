import logging
import random
from datetime import datetime, timedelta
from typing import Callable

from sqlalchemy.orm import Session

from app.core.config import settings
from app.db.session import SessionLocal
from app.models.webhook_delivery import IngestionState
from app.models.webhook_outbox import OutboxState, WebhookOutbox


logger = logging.getLogger(__name__)
TaskProducer = Callable[..., object]


def _retry_delay(attempt_count: int) -> int:
    exponential_seconds = min(5 * (2 ** max(attempt_count - 1, 0)), 300)
    return exponential_seconds + random.randint(0, max(exponential_seconds // 4, 1))


def _dispatch_one(outbox_id: int, producer: TaskProducer) -> bool:
    db: Session = SessionLocal()
    try:
        message = (
            db.query(WebhookOutbox)
            .filter(WebhookOutbox.id == outbox_id)
            .with_for_update(skip_locked=True)
            .one_or_none()
        )
        if message is None or message.status == OutboxState.PUBLISHED:
            return False
        if message.available_at > datetime.utcnow():
            return False

        message.attempt_count += 1
        try:
            producer(
                message.task_name,
                args=[message.delivery_pk],
                task_id=f"github-delivery-{message.delivery.delivery_id}",
                queue="github_ingestion",
            )
        except Exception as exc:
            delay = _retry_delay(message.attempt_count)
            message.status = OutboxState.FAILED
            message.last_error = str(exc)[:4000]
            message.available_at = datetime.utcnow() + timedelta(seconds=delay)
            message.delivery.last_error = f"Queue publish failed: {exc}"[:4000]
            message.delivery.next_retry_at = message.available_at
            db.commit()
            logger.exception("Failed to publish webhook outbox row %s", message.id)
            return False

        now = datetime.utcnow()
        message.status = OutboxState.PUBLISHED
        message.published_at = now
        message.last_error = None
        message.delivery.status = IngestionState.QUEUED
        message.delivery.last_error = None
        message.delivery.next_retry_at = None
        db.commit()
        return True
    finally:
        db.close()


def dispatch_pending_outbox(producer: TaskProducer) -> int:
    db: Session = SessionLocal()
    try:
        candidate_ids = [
            row[0]
            for row in (
                db.query(WebhookOutbox.id)
                .filter(
                    WebhookOutbox.status.in_([OutboxState.PENDING, OutboxState.FAILED]),
                    WebhookOutbox.available_at <= datetime.utcnow(),
                )
                .order_by(WebhookOutbox.created_at)
                .limit(settings.OUTBOX_DISPATCH_BATCH_SIZE)
                .all()
            )
        ]
    finally:
        db.close()

    return sum(_dispatch_one(outbox_id, producer) for outbox_id in candidate_ids)
