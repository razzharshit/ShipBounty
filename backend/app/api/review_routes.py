from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy import func
from sqlalchemy.orm import selectinload
from sqlalchemy.orm import Session

from app.api.authz import authorize_repository, effective_repository_role, get_current_user
from app.db.session import get_db
from app.models.authorization import AuthorizationRole, Organization, OrganizationMembership
from app.models.pull_request import PullRequest
from app.models.repository import Repository
from app.models.review_domain import EligibilityDecision, EligibilityDecisionStatus
from app.models.user import User
from app.schemas.review_domain import (
    ApprovalRead,
    ApprovalSubmit,
    EligibilityDecisionRead,
    RepositoryPolicyRead,
    RepositoryPolicyUpdate,
    ReviewRead,
    ReviewSubmit,
)
from app.services.audit_service import record_audit_event
from app.services.notification_service import (
    emit_domain_event,
    repository_reviewer_user_ids,
)
from app.services.eligibility_service import (
    EligibilityConflictError,
    RepositoryPolicyError,
    evaluate_eligibility,
    policy_for_repository,
    set_repository_policy,
    submit_approval,
    submit_review,
)


router = APIRouter(tags=["review-and-approval"])


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


def _decision(
    db: Session,
    decision_id: int,
) -> EligibilityDecision:
    decision = db.get(EligibilityDecision, decision_id)
    if decision is None:
        raise HTTPException(status_code=404, detail="Eligibility decision not found")
    return decision


def _decision_for_update(
    db: Session,
    decision_id: int,
) -> EligibilityDecision:
    decision = (
        db.query(EligibilityDecision)
        .filter(EligibilityDecision.id == decision_id)
        .with_for_update()
        .populate_existing()
        .one_or_none()
    )
    if decision is None:
        raise HTTPException(status_code=404, detail="Eligibility decision not found")
    return decision


def _conflict(exc: EligibilityConflictError) -> HTTPException:
    return HTTPException(status_code=409, detail=str(exc))


@router.get(
    "/repositories/{repository_id}/eligibility-policy",
    response_model=RepositoryPolicyRead,
)
def get_eligibility_policy(
    repository_id: int,
    request: Request,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> RepositoryPolicyRead:
    repository = db.get(Repository, repository_id)
    if repository is None:
        raise HTTPException(status_code=404, detail="Repository not found")
    authorize_repository(
        db, user, repository, AuthorizationRole.VIEWER, request
    )
    policy = policy_for_repository(db, repository)
    db.commit()
    return policy


@router.put(
    "/repositories/{repository_id}/eligibility-policy",
    response_model=RepositoryPolicyRead,
)
def update_eligibility_policy(
    repository_id: int,
    payload: RepositoryPolicyUpdate,
    request: Request,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> RepositoryPolicyRead:
    repository = db.get(Repository, repository_id)
    if repository is None:
        raise HTTPException(status_code=404, detail="Repository not found")
    authorize_repository(
        db, user, repository, AuthorizationRole.ADMIN, request
    )
    previous_policy_id = repository.eligibility_policy_id
    try:
        policy = set_repository_policy(
            db,
            repository=repository,
            name=payload.name,
            description=payload.description,
            rules=payload.rules,
            created_by_user_id=user.id,
        )
    except RepositoryPolicyError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    record_audit_event(
        db,
        action="repository.eligibility_policy_changed",
        resource_type="repository_policy",
        actor_user_id=user.id,
        organization_id=repository.organization_id,
        repository_id=repository.id,
        resource_id=policy.id,
        event_metadata={
            "previous_policy_id": previous_policy_id,
            "new_policy_id": policy.id,
            "policy_version": policy.version,
            "policy_hash": policy.policy_hash,
        },
        request=request,
    )
    db.commit()
    return policy


@router.post(
    "/prs/{pr_id}/eligibility-decisions",
    response_model=EligibilityDecisionRead,
)
def post_eligibility_decision(
    pr_id: int,
    request: Request,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> EligibilityDecisionRead:
    pull_request = db.get(PullRequest, pr_id)
    if pull_request is None:
        raise HTTPException(status_code=404, detail="Pull request not found")
    authorize_repository(
        db, user, pull_request.repository, AuthorizationRole.REVIEWER, request
    )
    try:
        decision, created = evaluate_eligibility(
            db,
            pull_request=pull_request,
            actor_user_id=user.id,
        )
    except EligibilityConflictError as exc:
        raise _conflict(exc) from exc
    if created:
        record_audit_event(
            db,
            action="eligibility.policy_evaluated",
            resource_type="eligibility_decision",
            actor_user_id=user.id,
            organization_id=pull_request.repository.organization_id,
            repository_id=pull_request.repo_id,
            resource_id=decision.id,
            event_metadata={
                "status": decision.status.value,
                "score_id": decision.score_id,
                "score_version_id": decision.score_version_id,
                "repository_policy_id": decision.repository_policy_id,
                "evaluation_hash": decision.evaluation_hash,
                "failure_reasons": decision.failure_reasons,
            },
            request=request,
        )
        if decision.status.value == "pending_review":
            emit_domain_event(
                db,
                event_type="review.requested",
                organization_id=pull_request.repository.organization_id,
                repository_id=pull_request.repo_id,
                aggregate_type="eligibility_decision",
                aggregate_id=decision.id,
                event_identity=decision.evaluation_hash,
                recipient_user_ids=repository_reviewer_user_ids(
                    db, pull_request.repository
                ),
                actor_user_id=user.id,
                payload={
                    "pull_request_id": pull_request.id,
                    "pull_request_title": pull_request.title,
                    "repository": pull_request.repository.full_name,
                    "decision_id": decision.id,
                },
            )
    db.commit()
    return decision


@router.get(
    "/prs/{pr_id}/eligibility-decisions",
    response_model=list[EligibilityDecisionRead],
)
def list_eligibility_decisions(
    pr_id: int,
    request: Request,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> list[EligibilityDecisionRead]:
    pull_request = db.get(PullRequest, pr_id)
    if pull_request is None:
        raise HTTPException(status_code=404, detail="Pull request not found")
    authorize_repository(
        db, user, pull_request.repository, AuthorizationRole.VIEWER, request
    )
    return (
        db.query(EligibilityDecision)
        .filter(EligibilityDecision.pr_id == pr_id)
        .order_by(EligibilityDecision.created_at.desc(), EligibilityDecision.id.desc())
        .all()
    )


@router.get("/organizations/{organization_id}/review-queue")
def list_organization_review_queue(
    organization_id: int,
    status: EligibilityDecisionStatus | None = None,
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=50, ge=1, le=100),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    repository_ids = _authorized_repository_ids(db, organization_id, user)
    if not repository_ids:
        return _page([], 0, limit, offset, {"status_counts": {}})

    base_query = (
        db.query(EligibilityDecision)
        .join(PullRequest, PullRequest.id == EligibilityDecision.pr_id)
        .filter(
            PullRequest.repo_id.in_(repository_ids),
            EligibilityDecision.is_current.is_(True),
        )
    )
    status_counts = {
        row_status.value: count
        for row_status, count in db.query(
            EligibilityDecision.status,
            func.count(EligibilityDecision.id),
        )
        .join(PullRequest, PullRequest.id == EligibilityDecision.pr_id)
        .filter(
            PullRequest.repo_id.in_(repository_ids),
            EligibilityDecision.is_current.is_(True),
        )
        .group_by(EligibilityDecision.status)
        .all()
    }
    if status is not None:
        base_query = base_query.filter(EligibilityDecision.status == status)
    total = base_query.count()
    items = (
        base_query.options(
            selectinload(EligibilityDecision.reviews),
            selectinload(EligibilityDecision.approvals),
        )
        .order_by(EligibilityDecision.created_at.desc(), EligibilityDecision.id.desc())
        .offset(offset)
        .limit(limit)
        .all()
    )
    return _page(items, total, limit, offset, {"status_counts": status_counts})


@router.post(
    "/eligibility-decisions/{decision_id}/reviews",
    response_model=ReviewRead,
)
def post_review(
    decision_id: int,
    payload: ReviewSubmit,
    request: Request,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> ReviewRead:
    decision = _decision(db, decision_id)
    role = authorize_repository(
        db,
        user,
        decision.pull_request.repository,
        AuthorizationRole.VIEWER,
        request,
    )
    decision = _decision_for_update(db, decision_id)
    try:
        review = submit_review(
            db,
            decision=decision,
            reviewer=user,
            reviewer_role=role,
            recommendation=payload.recommendation,
            summary=payload.summary,
            findings=[
                item.model_dump(mode="json") for item in payload.findings
            ],
        )
    except EligibilityConflictError as exc:
        raise _conflict(exc) from exc
    record_audit_event(
        db,
        action="eligibility.human_review_submitted",
        resource_type="review",
        actor_user_id=user.id,
        organization_id=decision.pull_request.repository.organization_id,
        repository_id=decision.pull_request.repo_id,
        resource_id=review.id,
        event_metadata={
            "eligibility_decision_id": decision.id,
            "recommendation": payload.recommendation.value,
            "finding_count": len(payload.findings),
            "score_id": decision.score_id,
            "score_version_id": decision.score_version_id,
            "repository_policy_id": decision.repository_policy_id,
        },
        request=request,
    )
    if payload.recommendation.value == "request_changes":
        emit_domain_event(
            db,
            event_type="review.changes_requested",
            organization_id=decision.pull_request.repository.organization_id,
            repository_id=decision.pull_request.repo_id,
            aggregate_type="review",
            aggregate_id=review.id,
            event_identity=f"{review.id}:changes_requested",
            recipient_user_ids=[decision.pull_request.author_id],
            actor_user_id=user.id,
            payload={
                "pull_request_id": decision.pull_request.id,
                "pull_request_title": decision.pull_request.title,
                "repository": decision.pull_request.repository.full_name,
                "review_id": review.id,
            },
        )
    db.commit()
    return review


@router.post(
    "/eligibility-decisions/{decision_id}/approvals",
    response_model=ApprovalRead,
)
def post_approval(
    decision_id: int,
    payload: ApprovalSubmit,
    request: Request,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> ApprovalRead:
    decision = _decision(db, decision_id)
    role = authorize_repository(
        db,
        user,
        decision.pull_request.repository,
        AuthorizationRole.VIEWER,
        request,
    )
    decision = _decision_for_update(db, decision_id)
    try:
        approval = submit_approval(
            db,
            decision=decision,
            approver=user,
            approver_role=role,
            outcome=payload.outcome,
            reason=payload.reason,
        )
    except EligibilityConflictError as exc:
        raise _conflict(exc) from exc
    record_audit_event(
        db,
        action="eligibility.approval_submitted",
        resource_type="approval",
        actor_user_id=user.id,
        organization_id=decision.pull_request.repository.organization_id,
        repository_id=decision.pull_request.repo_id,
        resource_id=approval.id,
        event_metadata={
            "eligibility_decision_id": decision.id,
            "outcome": payload.outcome.value,
            "resulting_status": decision.status.value,
            "score_id": approval.score_id,
            "score_version_id": approval.score_version_id,
            "repository_policy_id": approval.repository_policy_id,
        },
        request=request,
    )
    if decision.status.value == "eligible":
        emit_domain_event(
            db,
            event_type="bounty.eligible",
            organization_id=decision.pull_request.repository.organization_id,
            repository_id=decision.pull_request.repo_id,
            aggregate_type="eligibility_decision",
            aggregate_id=decision.id,
            event_identity=f"{decision.id}:eligible",
            recipient_user_ids=[decision.pull_request.author_id],
            actor_user_id=user.id,
            payload={
                "pull_request_id": decision.pull_request.id,
                "pull_request_title": decision.pull_request.title,
                "repository": decision.pull_request.repository.full_name,
                "decision_id": decision.id,
            },
        )
    db.commit()
    return approval
