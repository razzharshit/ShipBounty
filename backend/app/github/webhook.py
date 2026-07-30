from __future__ import annotations

import hashlib
import hmac
import json
import logging

from fastapi import APIRouter, Header, HTTPException, Request, Response, status
from sqlalchemy.exc import IntegrityError, SQLAlchemyError

from app.core.config import settings
from app.db.session import SessionLocal
from app.models.webhook_delivery import IngestionState, WebhookDelivery
from app.models.webhook_outbox import OutboxState, WebhookOutbox
from app.models.repository import Repository
from app.models.authorization import GitHubInstallation


logger = logging.getLogger(__name__)
router = APIRouter()


def verify_signature(payload_body: bytes, signature: str) -> bool:
    if not signature or not signature.startswith("sha256="):
        return False
    if not settings.GITHUB_WEBHOOK_SECRET:
        logger.error("GITHUB_WEBHOOK_SECRET is missing.")
        return False

    mac = hmac.new(
        settings.GITHUB_WEBHOOK_SECRET.encode("utf-8"),
        msg=payload_body,
        digestmod=hashlib.sha256,
    )
    expected_signature = f"sha256={mac.hexdigest()}"
    return hmac.compare_digest(expected_signature, signature)


@router.post("/webhook/github", status_code=status.HTTP_202_ACCEPTED)
async def github_webhook(
    request: Request,
    response: Response,
    x_hub_signature_256: str | None = Header(default=None),
    x_github_event: str | None = Header(default=None),
    x_github_delivery: str | None = Header(default=None),
) -> dict[str, str]:
    body = await request.body()

    if not verify_signature(body, x_hub_signature_256 or ""):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid signature")
    if not x_github_delivery or not x_github_event:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="X-GitHub-Delivery and X-GitHub-Event are required",
        )

    try:
        payload = json.loads(body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid JSON payload",
        ) from exc
    if not isinstance(payload, dict):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="GitHub webhook payload must be a JSON object",
        )

    payload_hash = hashlib.sha256(body).hexdigest()
    db = SessionLocal()
    try:
        repository_payload = payload.get("repository") or {}
        github_repository_id = repository_payload.get("id")
        known_repository = (
            db.query(Repository)
            .filter(Repository.github_repo_id == github_repository_id)
            .first()
            if github_repository_id is not None
            else None
        )
        installation_id = (payload.get("installation") or {}).get("id")
        known_installation = (
            db.query(GitHubInstallation)
            .filter(GitHubInstallation.installation_id == installation_id)
            .first()
            if known_repository is None and installation_id is not None
            else None
        )
        delivery = WebhookDelivery(
            delivery_id=x_github_delivery,
            event_type=x_github_event,
            action=payload.get("action"),
            installation_id=installation_id,
            repository_id=github_repository_id,
            repository_full_name=repository_payload.get("full_name"),
            repository_owner_login=(
                repository_payload.get("owner") or {}
            ).get("login"),
            organization_id=(
                known_repository.organization_id
                if known_repository
                else (
                    known_installation.organization_id
                    if known_installation
                    else None
                )
            ),
            repository_pk=known_repository.id if known_repository else None,
            payload=payload,
            payload_hash=payload_hash,
            status=IngestionState.RECEIVED,
        )
        delivery.outbox_message = WebhookOutbox(status=OutboxState.PENDING)
        db.add(delivery)
        db.commit()
    except IntegrityError:
        db.rollback()
        existing = (
            db.query(WebhookDelivery)
            .filter(WebhookDelivery.delivery_id == x_github_delivery)
            .first()
        )
        if existing is None:
            logger.exception("Webhook delivery insert failed for a non-deduplication conflict")
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Unable to persist webhook delivery",
            )
        if existing.payload_hash != payload_hash:
            logger.warning(
                "Duplicate GitHub delivery ID arrived with a different payload hash: %s",
                x_github_delivery,
            )
        response.status_code = status.HTTP_200_OK
        return {"status": "duplicate", "delivery_id": x_github_delivery}
    except SQLAlchemyError as exc:
        db.rollback()
        logger.exception("Unable to persist GitHub delivery %s", x_github_delivery)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Unable to persist webhook delivery",
        ) from exc
    finally:
        db.close()

    logger.info(
        "Accepted GitHub delivery: delivery_id=%s event=%s action=%s",
        x_github_delivery,
        x_github_event,
        payload.get("action"),
    )
    return {"status": "accepted", "delivery_id": x_github_delivery}
