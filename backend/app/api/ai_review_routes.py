from __future__ import annotations

from datetime import datetime, time

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.api.authz import authorize_repository, effective_repository_role, get_current_user
from app.core.config import settings
from app.db.session import get_db
from app.models.ai_review import AIReview, AIReviewStatus
from app.models.authorization import AuthorizationRole, Organization, OrganizationMembership
from app.models.pull_request import PullRequest
from app.models.repository import Repository
from app.models.user import User
from app.schemas.ai_review import (
    AIReviewCompletion,
    AIReviewFailure,
    AIReviewPolicyRead,
    AIReviewPolicyUpdate,
    AIReviewRead,
    AIReviewRequest,
)
from app.services.ai_review_service import (
    AIReviewConflictError,
    AIReviewPolicyError,
    ai_review_policy_for_repository,
    complete_ai_review,
    fail_ai_review,
    request_ai_review,
    set_ai_review_policy,
)
from app.services.audit_service import record_audit_event
from app.services.ai_review_provider_factory import (
    configured_ai_review_provider,
)
from app.worker.celery_app import celery_app


router = APIRouter(tags=["advisory-ai-review"])


def _authorized_repository_ids(
    db: Session,
    organization_id: int,
    user: User,
) -> list[int]:
    organization = db.get(Organization, organization_id)
    if organization is None:
        raise HTTPException(status_code=404, detail="Organization not found")
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
    membership = (
        db.query(OrganizationMembership)
        .filter(
            OrganizationMembership.organization_id == organization_id,
            OrganizationMembership.user_id == user.id,
            OrganizationMembership.is_active.is_(True),
            OrganizationMembership.github_verified.is_(True),
        )
        .first()
    )
    if not repository_ids and membership is None:
        raise HTTPException(status_code=404, detail="Organization not found")
    return repository_ids


def _page(items: list, total: int, limit: int, offset: int, aggregates: dict):
    return {
        "items": items,
        "total": total,
        "limit": limit,
        "offset": offset,
        "has_more": offset + len(items) < total,
        "aggregates": aggregates,
    }


def _repository(db: Session, repository_id: int) -> Repository:
    repository = db.get(Repository, repository_id)
    if repository is None:
        raise HTTPException(status_code=404, detail="Repository not found")
    return repository


def _review(db: Session, review_id: int) -> AIReview:
    review = db.get(AIReview, review_id)
    if review is None:
        raise HTTPException(status_code=404, detail="AI review not found")
    return review


def _audit(
    db: Session,
    request: Request,
    user: User,
    review: AIReview,
    *,
    action: str,
    metadata: dict,
) -> None:
    repository = review.pull_request.repository
    record_audit_event(
        db,
        action=action,
        resource_type="ai_review",
        actor_user_id=user.id,
        organization_id=repository.organization_id,
        repository_id=repository.id,
        resource_id=review.id,
        event_metadata=metadata,
        request=request,
    )


def _require_manual_ai_state_enabled() -> None:
    if (
        not settings.ALLOW_MANUAL_AI_REVIEW_STATE
        or settings.APP_ENV.lower() == "production"
    ):
        raise HTTPException(status_code=404, detail="Not found")


@router.get(
    "/repositories/{repository_id}/ai-review-policy",
    response_model=AIReviewPolicyRead,
)
def get_ai_review_policy(
    repository_id: int,
    request: Request,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    repository = _repository(db, repository_id)
    authorize_repository(db, user, repository, AuthorizationRole.VIEWER, request)
    policy = ai_review_policy_for_repository(db, repository)
    db.commit()
    return policy


@router.put(
    "/repositories/{repository_id}/ai-review-policy",
    response_model=AIReviewPolicyRead,
)
def put_ai_review_policy(
    repository_id: int,
    payload: AIReviewPolicyUpdate,
    request: Request,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    repository = _repository(db, repository_id)
    authorize_repository(db, user, repository, AuthorizationRole.ADMIN, request)
    try:
        policy = set_ai_review_policy(
            db,
            repository=repository,
            name=payload.name,
            rules=payload.rules,
            created_by_user_id=user.id,
        )
    except AIReviewPolicyError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    record_audit_event(
        db,
        action="ai_review.policy_changed",
        resource_type="ai_review_policy",
        actor_user_id=user.id,
        organization_id=repository.organization_id,
        repository_id=repository.id,
        resource_id=policy.id,
        event_metadata={
            "version": policy.version,
            "policy_hash": policy.policy_hash,
        },
        request=request,
    )
    db.commit()
    return policy


@router.post(
    "/prs/{pr_id}/ai-reviews",
    response_model=AIReviewRead,
    status_code=201,
)
def post_ai_review(
    pr_id: int,
    payload: AIReviewRequest,
    request: Request,
    force: bool = Query(default=False),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    pull_request = db.get(PullRequest, pr_id)
    if pull_request is None:
        raise HTTPException(status_code=404, detail="Pull request not found")
    authorize_repository(
        db, user, pull_request.repository, AuthorizationRole.MAINTAINER, request
    )
    try:
        provider = configured_ai_review_provider()
    except RuntimeError as exc:
        raise HTTPException(
            status_code=503,
            detail="The advisory AI provider is not configured",
        ) from exc
    try:
        review, created = request_ai_review(
            db,
            pull_request=pull_request,
            provider=provider.name,
            model=provider.model,
            provider_kind=provider.kind,
            requested_by_user_id=user.id,
            force_retry=force,
        )
    except AIReviewConflictError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    if created:
        _audit(
            db,
            request,
            user,
            review,
            action=(
                "ai_review.blocked"
                if review.status.value == "blocked"
                else "ai_review.requested"
            ),
            metadata={
                "provider": review.provider,
                "model": review.model,
                "provider_kind": review.provider_kind.value,
                "prompt_version": review.prompt_version,
                "input_commit_sha": review.input_commit_sha,
                "privacy_decision": review.privacy_decision,
            },
        )
    db.commit()
    if review.status.value == "pending":
        task_sent = False
        try:
            celery_app.send_task(
                "app.worker.tasks.execute_ai_review",
                args=[review.id],
                queue="ai_review",
            )
            task_sent = True
        except Exception:
            pass
        if not task_sent or settings.APP_ENV.lower() in {"development", "test"}:
            from app.services.ai_review_service import execute_ai_review_by_id

            execute_ai_review_by_id(review.id)
            db.refresh(review)
    return review


@router.post(
    "/ai-reviews/{review_id}/retry",
    response_model=AIReviewRead,
    status_code=201,
)
def post_ai_review_retry(
    review_id: int,
    request: Request,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    target_review = _review(db, review_id)
    pull_request = target_review.pull_request
    authorize_repository(
        db, user, pull_request.repository, AuthorizationRole.MAINTAINER, request
    )
    try:
        provider = configured_ai_review_provider()
    except RuntimeError as exc:
        raise HTTPException(
            status_code=503,
            detail="The advisory AI provider is not configured",
        ) from exc
    try:
        review, created = request_ai_review(
            db,
            pull_request=pull_request,
            provider=provider.name,
            model=provider.model,
            provider_kind=provider.kind,
            requested_by_user_id=user.id,
            force_retry=True,
        )
    except AIReviewConflictError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    db.commit()
    if review.status.value == "pending":
        task_sent = False
        try:
            celery_app.send_task(
                "app.worker.tasks.execute_ai_review",
                args=[review.id],
                queue="ai_review",
            )
            task_sent = True
        except Exception:
            pass
        if not task_sent or settings.APP_ENV.lower() in {"development", "test"}:
            from app.services.ai_review_service import execute_ai_review_by_id

            execute_ai_review_by_id(review.id)
            db.refresh(review)
    return review


@router.get("/prs/{pr_id}/ai-reviews", response_model=list[AIReviewRead])
def get_ai_reviews(
    pr_id: int,
    request: Request,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    pull_request = db.get(PullRequest, pr_id)
    if pull_request is None:
        raise HTTPException(status_code=404, detail="Pull request not found")
    authorize_repository(
        db, user, pull_request.repository, AuthorizationRole.VIEWER, request
    )
    return (
        db.query(AIReview)
        .filter(AIReview.pr_id == pr_id)
        .order_by(AIReview.created_at.desc(), AIReview.id.desc())
        .all()
    )


@router.get("/organizations/{organization_id}/ai-reviews")
def get_organization_ai_reviews(
    organization_id: int,
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=50, ge=1, le=100),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    repository_ids = _authorized_repository_ids(db, organization_id, user)
    if not repository_ids:
        return _page(
            [],
            0,
            limit,
            offset,
            {
                "status_counts": {},
                "total_tokens": 0,
                "cost_by_currency": {},
                "today_request_count": 0,
                "configured_daily_limit": settings.AI_REVIEW_DAILY_LIMIT,
            },
        )

    base_query = (
        db.query(AIReview)
        .join(PullRequest, PullRequest.id == AIReview.pr_id)
        .filter(PullRequest.repo_id.in_(repository_ids))
    )
    total = base_query.count()
    status_counts = {
        row_status.value: count
        for row_status, count in db.query(AIReview.status, func.count(AIReview.id))
        .join(PullRequest, PullRequest.id == AIReview.pr_id)
        .filter(PullRequest.repo_id.in_(repository_ids))
        .group_by(AIReview.status)
        .all()
    }
    total_tokens = (
        db.query(func.coalesce(func.sum(AIReview.total_tokens), 0))
        .join(PullRequest, PullRequest.id == AIReview.pr_id)
        .filter(PullRequest.repo_id.in_(repository_ids))
        .scalar()
    )
    cost_rows = (
        db.query(AIReview.cost_currency, func.coalesce(func.sum(AIReview.cost_amount), 0))
        .join(PullRequest, PullRequest.id == AIReview.pr_id)
        .filter(
            PullRequest.repo_id.in_(repository_ids),
            AIReview.cost_currency.isnot(None),
        )
        .group_by(AIReview.cost_currency)
        .all()
    )
    today_start = datetime.combine(datetime.utcnow().date(), time.min)
    today_request_count = (
        db.query(func.count(AIReview.id))
        .join(PullRequest, PullRequest.id == AIReview.pr_id)
        .filter(
            PullRequest.repo_id.in_(repository_ids),
            AIReview.created_at >= today_start,
            AIReview.status != AIReviewStatus.BLOCKED,
        )
        .scalar()
    )
    items = (
        base_query.order_by(AIReview.created_at.desc(), AIReview.id.desc())
        .offset(offset)
        .limit(limit)
        .all()
    )
    return _page(
        items,
        total,
        limit,
        offset,
        {
            "status_counts": status_counts,
            "total_tokens": total_tokens or 0,
            "cost_by_currency": {
                currency: str(amount)
                for currency, amount in cost_rows
                if currency is not None
            },
            "today_request_count": today_request_count or 0,
            "configured_daily_limit": settings.AI_REVIEW_DAILY_LIMIT,
        },
    )


@router.post(
    "/ai-reviews/{review_id}/complete",
    response_model=AIReviewRead,
)
def post_ai_review_complete(
    review_id: int,
    payload: AIReviewCompletion,
    request: Request,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    _require_manual_ai_state_enabled()
    review = _review(db, review_id)
    authorize_repository(
        db,
        user,
        review.pull_request.repository,
        AuthorizationRole.ADMIN,
        request,
    )
    try:
        complete_ai_review(
            db,
            review=review,
            output=payload.output,
            provider_request_id=payload.provider_request_id,
            token_usage=payload.token_usage,
            cost_amount=payload.cost_amount,
            cost_currency=payload.cost_currency,
            moderation_result=payload.moderation_result,
        )
    except AIReviewConflictError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    _audit(
        db,
        request,
        user,
        review,
        action=(
            "ai_review.safety_failed"
            if review.failure_reason
            and review.failure_reason.startswith("MODERATION_")
            else "ai_review.completed"
        ),
        metadata={
            "provider_request_id": review.provider_request_id,
            "total_tokens": review.total_tokens,
            "cost_amount": str(review.cost_amount),
            "cost_currency": review.cost_currency,
            "moderation": review.moderation_result,
            "advisory_only": True,
        },
    )
    db.commit()
    return review


@router.post(
    "/ai-reviews/{review_id}/failed",
    response_model=AIReviewRead,
)
def post_ai_review_failed(
    review_id: int,
    payload: AIReviewFailure,
    request: Request,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    _require_manual_ai_state_enabled()
    review = _review(db, review_id)
    authorize_repository(
        db,
        user,
        review.pull_request.repository,
        AuthorizationRole.ADMIN,
        request,
    )
    try:
        fail_ai_review(
            db,
            review=review,
            failure_reason=payload.failure_reason,
            provider_request_id=payload.provider_request_id,
            moderation_result=payload.moderation_result,
        )
    except AIReviewConflictError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    _audit(
        db,
        request,
        user,
        review,
        action="ai_review.failed",
        metadata={
            "provider_request_id": review.provider_request_id,
            "failure_reason": review.failure_reason,
            "moderation": review.moderation_result,
        },
    )
    db.commit()
    return review
