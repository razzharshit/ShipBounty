from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from app.models.notification import (
    DomainEvent,
    Notification,
    NotificationChannel,
    NotificationStatus,
)
from app.models.operations import GitHubRateLimitSnapshot, WorkerHeartbeat
from app.models.score import ImmutableRecordError
from app.models.webhook_delivery import IngestionState, WebhookDelivery
from app.models.webhook_outbox import OutboxState, WebhookOutbox
from app.services.dashboard_service import operations_dashboard, product_analytics
from app.services.notification_service import (
    deliver_notification_once,
    emit_domain_event,
)
from test_bounty_domain import _approved_claim_graph
from test_review_approval_domain import _domain_fixture


class _SuccessfulAdapter:
    channel = NotificationChannel.IN_APP

    def deliver(self, notification: Notification) -> None:
        return None


class _FailingAdapter:
    channel = NotificationChannel.EMAIL

    def deliver(self, notification: Notification) -> None:
        raise RuntimeError("temporary mail outage")


def test_domain_event_is_idempotent_and_creates_channel_deliveries(session_factory):
    db = session_factory()
    try:
        graph = _domain_fixture(db)
        graph["author"].email = "author@example.com"
        arguments = {
            "event_type": "pr.analysis_completed",
            "organization_id": graph["repository"].organization_id,
            "repository_id": graph["repository"].id,
            "aggregate_type": "pull_request",
            "aggregate_id": graph["pull_request"].id,
            "event_identity": graph["pull_request"].head_sha,
            "recipient_user_ids": [graph["author"].id, graph["author"].id],
            "payload": {
                "repository": graph["repository"].full_name,
                "pull_request_title": graph["pull_request"].title,
            },
        }

        event, created = emit_domain_event(db, **arguments)
        duplicate, duplicate_created = emit_domain_event(db, **arguments)
        notifications = (
            db.query(Notification)
            .filter(Notification.event_id == event.id)
            .order_by(Notification.channel)
            .all()
        )

        assert created is True
        assert duplicate_created is False
        assert duplicate.id == event.id
        assert {item.channel for item in notifications} == {
            NotificationChannel.IN_APP,
            NotificationChannel.EMAIL,
        }
        assert len(notifications) == 2
        assert all(item.status == NotificationStatus.PENDING for item in notifications)
        assert next(
            item for item in notifications
            if item.channel == NotificationChannel.EMAIL
        ).destination == "author@example.com"
    finally:
        db.close()


def test_notification_delivery_tracks_success_and_retryable_failure(session_factory):
    db = session_factory()
    try:
        graph = _domain_fixture(db)
        graph["author"].email = "author@example.com"
        event, _ = emit_domain_event(
            db,
            event_type="review.requested",
            organization_id=graph["repository"].organization_id,
            repository_id=graph["repository"].id,
            aggregate_type="pull_request",
            aggregate_id=graph["pull_request"].id,
            event_identity="decision-1",
            recipient_user_ids=[graph["author"].id],
            payload={"repository": graph["repository"].full_name},
        )
        notifications = {
            item.channel: item
            for item in db.query(Notification)
            .filter(Notification.event_id == event.id)
            .all()
        }

        assert deliver_notification_once(
            db,
            notifications[NotificationChannel.IN_APP],
            adapters={NotificationChannel.IN_APP: _SuccessfulAdapter()},
        )
        assert (
            notifications[NotificationChannel.IN_APP].status
            == NotificationStatus.DELIVERED
        )

        assert not deliver_notification_once(
            db,
            notifications[NotificationChannel.EMAIL],
            adapters={NotificationChannel.EMAIL: _FailingAdapter()},
        )
        failed = notifications[NotificationChannel.EMAIL]
        assert failed.status == NotificationStatus.FAILED
        assert failed.attempt_count == 1
        assert failed.last_error == "temporary mail outage"
        assert failed.next_retry_at is not None
        assert failed.next_retry_at > datetime.utcnow()
    finally:
        db.close()


def test_domain_events_are_immutable(session_factory):
    db = session_factory()
    try:
        graph = _domain_fixture(db)
        event, _ = emit_domain_event(
            db,
            event_type="payout.confirmed",
            organization_id=graph["repository"].organization_id,
            repository_id=graph["repository"].id,
            aggregate_type="payout",
            aggregate_id=7,
            event_identity="confirmation-7",
            recipient_user_ids=[graph["author"].id],
            payload={"repository": graph["repository"].full_name},
        )
        event.payload = {"tampered": True}

        with pytest.raises(ImmutableRecordError, match="insert-only"):
            db.flush()
    finally:
        db.rollback()
        db.close()


def test_operations_dashboard_uses_persisted_telemetry(session_factory):
    db = session_factory()
    try:
        graph = _domain_fixture(db)
        organization_id = graph["repository"].organization_id
        pull_request = graph["pull_request"]
        pull_request.file_sync_complete = False
        pull_request.incomplete_reason = "GITHUB_FILE_LIMIT"
        pull_request.synchronized_at = datetime.utcnow()
        delivery = WebhookDelivery(
            delivery_id="operations-delivery",
            event_type="pull_request",
            action="synchronize",
            installation_id=100,
            repository_id=graph["repository"].github_repo_id,
            organization_id=organization_id,
            repository_pk=graph["repository"].id,
            payload={},
            payload_hash="d" * 64,
            status=IngestionState.FAILED,
            attempt_count=3,
            last_error="GitHub unavailable",
            started_at=datetime.utcnow() - timedelta(seconds=8),
            completed_at=datetime.utcnow(),
        )
        db.add(delivery)
        db.flush()
        db.add(
            WebhookOutbox(
                delivery_pk=delivery.id,
                status=OutboxState.FAILED,
                attempt_count=2,
            )
        )
        db.add(
            WorkerHeartbeat(
                worker_id="worker-1",
                queues=["webhooks", "notifications"],
                active_tasks=2,
                last_seen_at=datetime.utcnow() - timedelta(minutes=3),
            )
        )
        db.add(
            GitHubRateLimitSnapshot(
                installation_id=100,
                organization_id=organization_id,
                repository_id=graph["repository"].id,
                resource="core",
                limit=5000,
                remaining=1250,
                used=3750,
                reset_at=datetime.now(timezone.utc) + timedelta(minutes=20),
                observed_at=datetime.now(timezone.utc),
            )
        )
        db.flush()

        dashboard = operations_dashboard(db, organization_id)

        assert dashboard["queue_depth"] == 1
        assert dashboard["awaiting_publish"] == 1
        assert dashboard["failed_jobs"] == 1
        assert dashboard["total_retry_attempts"] == 2
        assert dashboard["incomplete_ingestions"] == 1
        assert dashboard["average_processing_seconds"] >= 8
        assert dashboard["workers"][0]["is_stale"] is True
        assert dashboard["github_rate_limits"][0]["remaining"] == 1250
        assert dashboard["failure_logs"][0]["last_error"] == "GitHub unavailable"
    finally:
        db.close()


def test_product_analytics_reports_real_claim_and_merge_activity(session_factory):
    db = session_factory()
    try:
        graph = _approved_claim_graph(db)
        pull_request = graph["pull_request"]
        pull_request.github_created_at = datetime.now(timezone.utc) - timedelta(days=2)
        pull_request.merged_at = datetime.now(timezone.utc)
        db.flush()

        analytics = product_analytics(
            db,
            graph["repository"].organization,
            [graph["repository"].id],
        )

        assert analytics["eligible_claims"] == 1
        assert analytics["average_merge_seconds"] >= 172799
        assert analytics["organization"]["contributor_count"] == 1
        assert analytics["contributors"][0]["merged_pull_requests"] == 1
        assert analytics["repositories"][0]["health"] == "healthy"
    finally:
        db.close()
