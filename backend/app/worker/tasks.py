import random

from app.core.config import settings
from app.services.delivery_processor import process_delivery_once
from app.services.notification_service import dispatch_pending_notifications
from app.services.operations_service import record_worker_heartbeat
from app.services.outbox_service import dispatch_pending_outbox
from app.services.payout_integration_service import (
    reconcile_due_payouts,
    reconcile_treasury_balances,
)
from app.services.ai_review_service import (
    dispatch_pending_ai_reviews,
    execute_ai_review_by_id,
)
from app.worker.celery_app import celery_app


def _processing_retry_delay(retry_number: int) -> int:
    base = min(5 * (2 ** retry_number), 300)
    return base + random.randint(0, max(base // 4, 1))


@celery_app.task(name="app.worker.tasks.dispatch_webhook_outbox")
def dispatch_webhook_outbox() -> int:
    return dispatch_pending_outbox(celery_app.send_task)


@celery_app.task(bind=True, name="app.worker.tasks.record_worker_heartbeat")
def worker_heartbeat(self) -> str:
    worker_id = self.request.hostname or "unknown-worker"
    record_worker_heartbeat(
        worker_id,
        queues=[
            "github_ingestion",
            "outbox_dispatch",
            "notifications",
            "ai_review",
            "operations",
            "payouts",
        ],
        worker_metadata={"task_id": self.request.id},
    )
    return worker_id


@celery_app.task(name="app.worker.tasks.dispatch_notifications")
def dispatch_notifications() -> int:
    return dispatch_pending_notifications()


@celery_app.task(name="app.worker.tasks.dispatch_ai_reviews")
def dispatch_ai_reviews() -> int:
    return dispatch_pending_ai_reviews(celery_app.send_task)


@celery_app.task(
    bind=True,
    name="app.worker.tasks.execute_ai_review",
    max_retries=settings.CELERY_MAX_RETRIES,
    acks_late=True,
    reject_on_worker_lost=True,
)
def execute_ai_review(self, review_id: int) -> str:
    try:
        return execute_ai_review_by_id(review_id)
    except Exception as exc:
        if self.request.retries >= settings.CELERY_MAX_RETRIES:
            raise
        raise self.retry(
            exc=RuntimeError(str(exc)),
            countdown=_processing_retry_delay(self.request.retries),
        ) from exc


@celery_app.task(name="app.worker.tasks.reconcile_payouts")
def reconcile_payouts() -> dict[str, int]:
    return reconcile_due_payouts()


@celery_app.task(name="app.worker.tasks.reconcile_treasury_balances")
def reconcile_balances() -> dict[str, int]:
    return reconcile_treasury_balances()


@celery_app.task(
    bind=True,
    name="app.worker.tasks.process_webhook_delivery",
    max_retries=settings.CELERY_MAX_RETRIES,
    acks_late=True,
    reject_on_worker_lost=True,
)
def process_webhook_delivery(self, delivery_pk: int) -> str:
    retry_delay = _processing_retry_delay(self.request.retries)
    has_retry_remaining = self.request.retries < settings.CELERY_MAX_RETRIES
    try:
        return process_delivery_once(
            delivery_pk,
            next_retry_seconds=retry_delay if has_retry_remaining else None,
        )
    except Exception as exc:
        if not has_retry_remaining:
            raise
        raise self.retry(
            exc=RuntimeError(str(exc)),
            countdown=retry_delay,
        ) from exc
