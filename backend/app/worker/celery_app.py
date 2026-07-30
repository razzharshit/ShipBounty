from celery import Celery

from app.core.config import settings


celery_app = Celery(
    "github_bounty_dispenser",
    broker=settings.CELERY_BROKER_URL,
    include=["app.worker.tasks"],
)
celery_app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    task_ignore_result=True,
    task_acks_late=True,
    task_reject_on_worker_lost=True,
    worker_prefetch_multiplier=1,
    task_time_limit=settings.CELERY_TASK_TIME_LIMIT,
    task_soft_time_limit=settings.CELERY_TASK_SOFT_TIME_LIMIT,
    broker_connection_retry_on_startup=True,
    broker_transport_options={"visibility_timeout": settings.CELERY_TASK_TIME_LIMIT + 60},
    task_routes={
        "app.worker.tasks.process_webhook_delivery": {"queue": "github_ingestion"},
        "app.worker.tasks.dispatch_webhook_outbox": {"queue": "outbox_dispatch"},
        "app.worker.tasks.record_worker_heartbeat": {"queue": "operations"},
        "app.worker.tasks.dispatch_notifications": {"queue": "notifications"},
        "app.worker.tasks.dispatch_ai_reviews": {"queue": "ai_review"},
        "app.worker.tasks.execute_ai_review": {"queue": "ai_review"},
        "app.worker.tasks.reconcile_payouts": {"queue": "payouts"},
        "app.worker.tasks.reconcile_treasury_balances": {"queue": "payouts"},
    },
    beat_schedule={
        "dispatch-github-webhook-outbox": {
            "task": "app.worker.tasks.dispatch_webhook_outbox",
            "schedule": 2.0,
        },
        "record-worker-heartbeat": {
            "task": "app.worker.tasks.record_worker_heartbeat",
            "schedule": 30.0,
        },
        "dispatch-notifications": {
            "task": "app.worker.tasks.dispatch_notifications",
            "schedule": 10.0,
        },
        "dispatch-ai-reviews": {
            "task": "app.worker.tasks.dispatch_ai_reviews",
            "schedule": 30.0,
        },
        "reconcile-payouts": {
            "task": "app.worker.tasks.reconcile_payouts",
            "schedule": 30.0,
        },
        "reconcile-treasury-balances": {
            "task": "app.worker.tasks.reconcile_treasury_balances",
            "schedule": 60.0,
        },
    },
)
