import hashlib
import hmac
import json
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.core.config import settings
from app.db.base import Base
from app.github import webhook
from app.main import app
from app.models.webhook_delivery import IngestionState, WebhookDelivery
from app.models.webhook_outbox import OutboxState, WebhookOutbox
from app.services import delivery_processor, outbox_service


def _signed_headers(body: bytes, delivery_id: str) -> dict[str, str]:
    signature = hmac.new(b"test-secret", body, hashlib.sha256).hexdigest()
    return {
        "X-Hub-Signature-256": f"sha256={signature}",
        "X-GitHub-Event": "pull_request",
        "X-GitHub-Delivery": delivery_id,
        "Content-Type": "application/json",
    }


def test_webhook_persists_delivery_and_outbox_then_deduplicates(
    monkeypatch,
    session_factory,
):
    monkeypatch.setattr(settings, "GITHUB_WEBHOOK_SECRET", "test-secret")
    monkeypatch.setattr(webhook, "SessionLocal", session_factory)
    body = json.dumps(
        {
            "action": "opened",
            "installation": {"id": 11},
            "repository": {"id": 22, "full_name": "acme/widgets"},
            "pull_request": {"number": 7},
        },
        separators=(",", ":"),
    ).encode()

    client = TestClient(app)
    first = client.post(
        "/webhook/github",
        content=body,
        headers=_signed_headers(body, "delivery-1"),
    )
    duplicate = client.post(
        "/webhook/github",
        content=body,
        headers=_signed_headers(body, "delivery-1"),
    )

    assert first.status_code == 202
    assert first.json() == {"status": "accepted", "delivery_id": "delivery-1"}
    assert duplicate.status_code == 200
    assert duplicate.json() == {"status": "duplicate", "delivery_id": "delivery-1"}

    db = session_factory()
    try:
        delivery = db.query(WebhookDelivery).one()
        outbox = db.query(WebhookOutbox).one()
        assert delivery.delivery_id == "delivery-1"
        assert delivery.status == IngestionState.RECEIVED
        assert delivery.payload_hash == hashlib.sha256(body).hexdigest()
        assert outbox.delivery_pk == delivery.id
        assert outbox.status == OutboxState.PENDING
    finally:
        db.close()


def test_invalid_signature_is_not_persisted(monkeypatch, session_factory):
    monkeypatch.setattr(settings, "GITHUB_WEBHOOK_SECRET", "test-secret")
    monkeypatch.setattr(webhook, "SessionLocal", session_factory)

    response = TestClient(app).post(
        "/webhook/github",
        content=b"{}",
        headers={
            "X-Hub-Signature-256": "sha256=bad",
            "X-GitHub-Event": "ping",
            "X-GitHub-Delivery": "delivery-invalid",
        },
    )

    assert response.status_code == 401
    db = session_factory()
    try:
        assert db.query(WebhookDelivery).count() == 0
    finally:
        db.close()


def test_simultaneous_duplicate_deliveries_create_one_effective_job(
    monkeypatch,
    tmp_path,
):
    engine = create_engine(
        f"sqlite:///{tmp_path / 'concurrent-webhooks.db'}",
        connect_args={"check_same_thread": False, "timeout": 10},
    )
    Base.metadata.create_all(engine)
    concurrent_sessions = sessionmaker(
        bind=engine,
        autocommit=False,
        autoflush=False,
    )
    monkeypatch.setattr(settings, "GITHUB_WEBHOOK_SECRET", "test-secret")
    monkeypatch.setattr(webhook, "SessionLocal", concurrent_sessions)
    body = json.dumps(
        {
            "action": "opened",
            "installation": {"id": 11},
            "repository": {"id": 22, "full_name": "acme/widgets"},
            "pull_request": {"number": 7},
        },
        separators=(",", ":"),
    ).encode()
    barrier = Barrier(2)

    def send_delivery():
        barrier.wait()
        return TestClient(app).post(
            "/webhook/github",
            content=body,
            headers=_signed_headers(body, "delivery-concurrent"),
        )

    try:
        with ThreadPoolExecutor(max_workers=2) as executor:
            responses = list(executor.map(lambda _: send_delivery(), range(2)))

        assert sorted(response.status_code for response in responses) == [200, 202]
        db = concurrent_sessions()
        try:
            assert db.query(WebhookDelivery).count() == 1
            assert db.query(WebhookOutbox).count() == 1
        finally:
            db.close()
    finally:
        Base.metadata.drop_all(engine)
        engine.dispose()


def test_outbox_publish_marks_delivery_queued(monkeypatch, session_factory):
    monkeypatch.setattr(outbox_service, "SessionLocal", session_factory)
    db = session_factory()
    delivery = WebhookDelivery(
        delivery_id="delivery-2",
        event_type="pull_request",
        action="opened",
        payload={},
        payload_hash="a" * 64,
        status=IngestionState.RECEIVED,
    )
    delivery.outbox_message = WebhookOutbox(status=OutboxState.PENDING)
    db.add(delivery)
    db.commit()
    delivery_pk = delivery.id
    db.close()

    published: list[tuple[str, dict]] = []

    def producer(task_name, **options):
        published.append((task_name, options))

    assert outbox_service.dispatch_pending_outbox(producer) == 1
    assert published[0][1]["args"] == [delivery_pk]
    assert published[0][1]["queue"] == "github_ingestion"

    db = session_factory()
    try:
        stored_delivery = db.get(WebhookDelivery, delivery_pk)
        assert stored_delivery.status == IngestionState.QUEUED
        assert stored_delivery.outbox_message.status == OutboxState.PUBLISHED
    finally:
        db.close()


def test_delivery_processing_is_idempotent(monkeypatch, session_factory):
    monkeypatch.setattr(delivery_processor, "SessionLocal", session_factory)
    db = session_factory()
    delivery = WebhookDelivery(
        delivery_id="delivery-3",
        event_type="ping",
        action=None,
        payload={},
        payload_hash="b" * 64,
        status=IngestionState.QUEUED,
    )
    db.add(delivery)
    db.commit()
    delivery_pk = delivery.id
    db.close()

    assert (
        delivery_processor.process_delivery_once(
            delivery_pk,
            next_retry_seconds=10,
        )
        == "ignored"
    )
    assert (
        delivery_processor.process_delivery_once(
            delivery_pk,
            next_retry_seconds=10,
        )
        == "complete"
    )

    db = session_factory()
    try:
        stored = db.get(WebhookDelivery, delivery_pk)
        assert stored.status == IngestionState.COMPLETE
        assert stored.attempt_count == 1
        assert stored.completed_at is not None
    finally:
        db.close()


def test_incomplete_delivery_is_terminal(monkeypatch, session_factory):
    monkeypatch.setattr(delivery_processor, "SessionLocal", session_factory)
    db = session_factory()
    delivery = WebhookDelivery(
        delivery_id="delivery-4",
        event_type="pull_request",
        action="opened",
        payload={},
        payload_hash="c" * 64,
        status=IngestionState.QUEUED,
    )
    db.add(delivery)
    db.commit()
    delivery_pk = delivery.id
    db.close()

    assert (
        delivery_processor.process_delivery_once(
            delivery_pk,
            next_retry_seconds=10,
        )
        == "incomplete"
    )

    db = session_factory()
    try:
        stored = db.get(WebhookDelivery, delivery_pk)
        assert stored.status == IngestionState.INCOMPLETE
        assert "installation.id" in stored.last_error
        assert stored.next_retry_at is None
    finally:
        db.close()


def test_processing_failure_records_retry_state(monkeypatch, session_factory):
    monkeypatch.setattr(delivery_processor, "SessionLocal", session_factory)

    def fail_sync(db, delivery):
        raise RuntimeError("temporary GitHub failure")

    monkeypatch.setattr(delivery_processor, "synchronize_webhook_delivery", fail_sync)
    db = session_factory()
    delivery = WebhookDelivery(
        delivery_id="delivery-5",
        event_type="pull_request",
        action="opened",
        payload={},
        payload_hash="d" * 64,
        status=IngestionState.QUEUED,
    )
    db.add(delivery)
    db.commit()
    delivery_pk = delivery.id
    db.close()

    with pytest.raises(RuntimeError, match="temporary GitHub failure"):
        delivery_processor.process_delivery_once(
            delivery_pk,
            next_retry_seconds=10,
        )

    db = session_factory()
    try:
        stored = db.get(WebhookDelivery, delivery_pk)
        assert stored.status == IngestionState.FAILED
        assert stored.last_error == "temporary GitHub failure"
        assert stored.next_retry_at is not None
    finally:
        db.close()
