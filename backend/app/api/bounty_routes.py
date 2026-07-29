from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.api.authz import authorize_repository, effective_repository_role, get_current_user
from app.core.config import settings
from app.db.session import get_db
from app.models.authorization import AuthorizationRole, Organization, OrganizationMembership
from app.models.bounty_domain import (
    Bounty,
    BountyStatus,
    BountyAssignment,
    Claim,
    Issue,
    Payout,
    PayoutState,
    PayoutAttempt,
    Wallet,
)
from app.models.pull_request import PullRequest
from app.models.repository import Repository
from app.models.review_domain import EligibilityDecision
from app.models.user import User
from app.schemas.bounty_domain import (
    AssignmentCreate,
    AssignmentLink,
    AssignmentRead,
    AttemptCreate,
    AttemptFailed,
    AttemptSubmitted,
    BountyCreate,
    BountyPolicyRead,
    BountyPolicyUpdate,
    BountyRead,
    ClaimCreate,
    ClaimRead,
    IssueCreate,
    IssueRead,
    PayoutCreateRequest,
    PayoutAttemptRead,
    PayoutRead,
    WalletCreate,
    WalletRead,
)
from app.services.audit_service import record_audit_event
from app.services.notification_service import emit_domain_event
from app.services.bounty_service import (
    BountyConflictError,
    BountyPolicyError,
    approve_claim,
    assign_bounty,
    authorize_payout,
    bounty_policy_for_repository,
    confirm_payout,
    create_bounty,
    create_issue,
    create_payout,
    create_wallet,
    mark_attempt_failed,
    mark_attempt_submitted,
    mark_bounty_funded,
    link_assignment_to_pull_request,
    set_bounty_policy,
    start_payout_attempt,
    verify_wallet_for_bounty,
)


router = APIRouter(tags=["bounties-and-payouts"])


RESERVED_PAYOUT_STATES = (
    PayoutState.CREATED,
    PayoutState.AUTHORIZED,
    PayoutState.SUBMITTING,
    PayoutState.SUBMISSION_UNKNOWN,
    PayoutState.SUBMITTED,
)


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


def _currency_sums(rows) -> dict[str, str]:
    return {
        currency: str(amount)
        for currency, amount in rows
        if currency is not None
    }


def _require_manual_payout_state_enabled() -> None:
    if (
        not settings.ALLOW_MANUAL_PAYOUT_STATE
        or settings.APP_ENV.lower() == "production"
    ):
        raise HTTPException(status_code=404, detail="Not found")


def _repository(db: Session, repository_id: int) -> Repository:
    repository = db.get(Repository, repository_id)
    if repository is None:
        raise HTTPException(status_code=404, detail="Repository not found")
    return repository


def _conflict(exc: Exception, status_code: int = 409) -> HTTPException:
    return HTTPException(status_code=status_code, detail=str(exc))


def _audit(
    db: Session,
    request: Request,
    user: User,
    repository: Repository,
    *,
    action: str,
    resource_type: str,
    resource_id: int,
    metadata: dict,
) -> None:
    record_audit_event(
        db,
        action=action,
        resource_type=resource_type,
        actor_user_id=user.id,
        organization_id=repository.organization_id,
        repository_id=repository.id,
        resource_id=resource_id,
        event_metadata=metadata,
        request=request,
    )


@router.get(
    "/repositories/{repository_id}/bounty-policy",
    response_model=BountyPolicyRead,
)
def get_bounty_policy(
    repository_id: int,
    request: Request,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    repository = _repository(db, repository_id)
    authorize_repository(db, user, repository, AuthorizationRole.VIEWER, request)
    policy = bounty_policy_for_repository(db, repository)
    db.commit()
    return policy


@router.put(
    "/repositories/{repository_id}/bounty-policy",
    response_model=BountyPolicyRead,
)
def put_bounty_policy(
    repository_id: int,
    payload: BountyPolicyUpdate,
    request: Request,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    repository = _repository(db, repository_id)
    authorize_repository(db, user, repository, AuthorizationRole.ADMIN, request)
    try:
        policy = set_bounty_policy(
            db,
            repository=repository,
            name=payload.name,
            rules=payload.rules,
            created_by_user_id=user.id,
        )
    except BountyPolicyError as exc:
        raise _conflict(exc, 422) from exc
    _audit(
        db,
        request,
        user,
        repository,
        action="bounty.policy_changed",
        resource_type="bounty_policy",
        resource_id=policy.id,
        metadata={"version": policy.version, "policy_hash": policy.policy_hash},
    )
    db.commit()
    return policy


@router.post(
    "/repositories/{repository_id}/issues",
    response_model=IssueRead,
    status_code=201,
)
def post_issue(
    repository_id: int,
    payload: IssueCreate,
    request: Request,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    repository = _repository(db, repository_id)
    authorize_repository(db, user, repository, AuthorizationRole.MAINTAINER, request)
    issue = create_issue(db, repository=repository, **payload.model_dump())
    _audit(
        db, request, user, repository,
        action="bounty.issue_recorded", resource_type="issue",
        resource_id=issue.id, metadata={"github_issue_id": issue.github_issue_id},
    )
    db.commit()
    return issue


@router.post("/issues/{issue_id}/bounties", response_model=BountyRead, status_code=201)
def post_bounty(
    issue_id: int,
    payload: BountyCreate,
    request: Request,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    issue = db.get(Issue, issue_id)
    if issue is None:
        raise HTTPException(status_code=404, detail="Issue not found")
    repository = issue.repository
    authorize_repository(db, user, repository, AuthorizationRole.ADMIN, request)
    try:
        bounty = create_bounty(
            db,
            repository=repository,
            issue=issue,
            amount=payload.amount,
            currency=payload.currency,
            expires_at=payload.expires_at,
            created_by_user_id=user.id,
        )
    except BountyConflictError as exc:
        raise _conflict(exc) from exc
    _audit(
        db, request, user, repository,
        action="bounty.created", resource_type="bounty", resource_id=bounty.id,
        metadata={
            "amount": str(bounty.amount), "currency": bounty.currency,
            "issue_id": bounty.issue_id, "bounty_policy_id": bounty.bounty_policy_id,
            "eligibility_policy_id": bounty.eligibility_policy_id,
        },
    )
    db.commit()
    return bounty


@router.post("/bounties/{bounty_id}/fund", response_model=BountyRead)
def fund_bounty(
    bounty_id: int,
    request: Request,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    bounty = db.get(Bounty, bounty_id)
    if bounty is None:
        raise HTTPException(status_code=404, detail="Bounty not found")
    authorize_repository(db, user, bounty.repository, AuthorizationRole.ADMIN, request)
    try:
        mark_bounty_funded(db, bounty)
    except BountyConflictError as exc:
        raise _conflict(exc) from exc
    _audit(
        db, request, user, bounty.repository,
        action="bounty.funded", resource_type="bounty", resource_id=bounty.id,
        metadata={"funding_status": bounty.funding_status.value},
    )
    db.commit()
    return bounty


@router.post(
    "/bounties/{bounty_id}/assign",
    response_model=AssignmentRead,
    status_code=201,
)
def post_assignment(
    bounty_id: int,
    payload: AssignmentCreate,
    request: Request,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    bounty = db.get(Bounty, bounty_id)
    if bounty is None:
        raise HTTPException(status_code=404, detail="Bounty not found")
    authorize_repository(db, user, bounty.repository, AuthorizationRole.MAINTAINER, request)
    if db.get(User, payload.assignee_user_id) is None:
        raise HTTPException(status_code=404, detail="Assignee not found")
    pull_request = (
        db.get(PullRequest, payload.pull_request_id)
        if payload.pull_request_id is not None
        else None
    )
    if payload.pull_request_id is not None and pull_request is None:
        raise HTTPException(status_code=404, detail="Pull request not found")
    try:
        assignment = assign_bounty(
            db, bounty=bounty, assignee_user_id=payload.assignee_user_id,
            assigned_by_user_id=user.id,
            pull_request=pull_request,
        )
    except BountyConflictError as exc:
        raise _conflict(exc) from exc
    _audit(
        db, request, user, bounty.repository,
        action="bounty.assigned", resource_type="bounty_assignment",
        resource_id=assignment.id,
        metadata={"bounty_id": bounty.id, "assignee_user_id": assignment.assignee_user_id},
    )
    db.commit()
    return assignment


@router.post(
    "/bounty-assignments/{assignment_id}/link-pr",
    response_model=AssignmentRead,
)
def post_assignment_pull_request(
    assignment_id: int,
    payload: AssignmentLink,
    request: Request,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    assignment = db.get(BountyAssignment, assignment_id)
    pull_request = db.get(PullRequest, payload.pull_request_id)
    if assignment is None or pull_request is None:
        raise HTTPException(
            status_code=404, detail="Assignment or pull request not found"
        )
    repository = assignment.bounty.repository
    authorize_repository(
        db, user, repository, AuthorizationRole.MAINTAINER, request
    )
    try:
        link_assignment_to_pull_request(
            db, assignment=assignment, pull_request=pull_request
        )
    except BountyConflictError as exc:
        raise _conflict(exc) from exc
    _audit(
        db,
        request,
        user,
        repository,
        action="bounty.assignment_pr_linked",
        resource_type="bounty_assignment",
        resource_id=assignment.id,
        metadata={
            "bounty_id": assignment.bounty_id,
            "pull_request_id": assignment.pull_request_id,
        },
    )
    db.commit()
    return assignment


@router.post("/wallets", response_model=WalletRead, status_code=201)
def post_wallet(
    payload: WalletCreate,
    request: Request,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    try:
        wallet = create_wallet(db, user_id=user.id, **payload.model_dump())
    except BountyConflictError as exc:
        raise _conflict(exc, 422) from exc
    record_audit_event(
        db,
        action="wallet.registered",
        resource_type="wallet",
        actor_user_id=user.id,
        resource_id=wallet.id,
        event_metadata={"chain": wallet.chain},
        request=request,
    )
    db.commit()
    return wallet


@router.post("/bounties/{bounty_id}/wallets/{wallet_id}/verify", response_model=WalletRead)
def verify_wallet(
    bounty_id: int,
    wallet_id: int,
    request: Request,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    bounty = db.get(Bounty, bounty_id)
    wallet = db.get(Wallet, wallet_id)
    if bounty is None or wallet is None:
        raise HTTPException(status_code=404, detail="Bounty or wallet not found")
    authorize_repository(db, user, bounty.repository, AuthorizationRole.ADMIN, request)
    try:
        verify_wallet_for_bounty(db, bounty=bounty, wallet=wallet)
    except BountyConflictError as exc:
        raise _conflict(exc) from exc
    _audit(
        db, request, user, bounty.repository,
        action="wallet.verified", resource_type="wallet", resource_id=wallet.id,
        metadata={"wallet_user_id": wallet.user_id, "chain": wallet.chain},
    )
    db.commit()
    return wallet


@router.post("/bounties/{bounty_id}/claims", response_model=ClaimRead, status_code=201)
def post_claim(
    bounty_id: int,
    payload: ClaimCreate,
    request: Request,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    bounty = db.get(Bounty, bounty_id)
    if bounty is None:
        raise HTTPException(status_code=404, detail="Bounty not found")
    authorize_repository(db, user, bounty.repository, AuthorizationRole.CONTRIBUTOR, request)
    assignment = db.get(BountyAssignment, payload.assignment_id)
    pull_request = db.get(PullRequest, payload.pull_request_id)
    decision = db.get(EligibilityDecision, payload.eligibility_decision_id)
    wallet = db.get(Wallet, payload.wallet_id)
    if not all((assignment, pull_request, decision, wallet)):
        raise HTTPException(status_code=404, detail="Claim dependency not found")
    try:
        claim = approve_claim(
            db, bounty=bounty, assignment=assignment, pull_request=pull_request,
            decision=decision, claimant_user_id=user.id, wallet=wallet,
        )
    except BountyConflictError as exc:
        raise _conflict(exc) from exc
    _audit(
        db, request, user, bounty.repository,
        action="claim.approved", resource_type="claim", resource_id=claim.id,
        metadata={
            "bounty_id": bounty.id, "approval_id": claim.approval_id,
            "eligibility_decision_id": claim.eligibility_decision_id,
            "amount": str(claim.amount), "currency": claim.currency,
            "destination_chain": claim.destination_chain,
        },
    )
    emit_domain_event(
        db,
        event_type="claim.approved",
        organization_id=bounty.organization_id,
        repository_id=bounty.repository_id,
        aggregate_type="claim",
        aggregate_id=claim.id,
        event_identity=f"{claim.id}:approved",
        recipient_user_ids=[claim.claimant_user_id],
        actor_user_id=user.id,
        payload={
            "pull_request_id": claim.pull_request_id,
            "pull_request_title": claim.pull_request.title,
            "repository": bounty.repository.full_name,
            "claim_id": claim.id,
            "amount": str(claim.amount),
            "currency": claim.currency,
        },
    )
    db.commit()
    return claim


@router.get("/organizations/{organization_id}/bounties")
def list_organization_bounties(
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
            {"status_counts": {}, "active_value_by_currency": {}},
        )
    base_query = db.query(Bounty).filter(Bounty.repository_id.in_(repository_ids))
    total = base_query.count()
    status_counts = {
        row_status.value: count
        for row_status, count in db.query(Bounty.status, func.count(Bounty.id))
        .filter(Bounty.repository_id.in_(repository_ids))
        .group_by(Bounty.status)
        .all()
    }
    active_value = _currency_sums(
        db.query(Bounty.currency, func.coalesce(func.sum(Bounty.amount), 0))
        .filter(
            Bounty.repository_id.in_(repository_ids),
            Bounty.status.in_((BountyStatus.OPEN, BountyStatus.ASSIGNED)),
        )
        .group_by(Bounty.currency)
        .all()
    )
    items = (
        base_query.order_by(Bounty.created_at.desc(), Bounty.id.desc())
        .offset(offset)
        .limit(limit)
        .all()
    )
    return _page(
        items,
        total,
        limit,
        offset,
        {"status_counts": status_counts, "active_value_by_currency": active_value},
    )


@router.get("/organizations/{organization_id}/claims")
def list_organization_claims(
    organization_id: int,
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=50, ge=1, le=100),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    repository_ids = _authorized_repository_ids(db, organization_id, user)
    if not repository_ids:
        return _page([], 0, limit, offset, {"status_counts": {}})
    base_query = (
        db.query(Claim)
        .join(Bounty, Bounty.id == Claim.bounty_id)
        .filter(Bounty.repository_id.in_(repository_ids))
    )
    total = base_query.count()
    status_counts = {
        row_status.value: count
        for row_status, count in db.query(Claim.status, func.count(Claim.id))
        .join(Bounty, Bounty.id == Claim.bounty_id)
        .filter(Bounty.repository_id.in_(repository_ids))
        .group_by(Claim.status)
        .all()
    }
    items = (
        base_query.order_by(Claim.created_at.desc(), Claim.id.desc())
        .offset(offset)
        .limit(limit)
        .all()
    )
    return _page(items, total, limit, offset, {"status_counts": status_counts})


@router.post("/claims/{claim_id}/payouts", response_model=PayoutRead, status_code=201)
def post_payout(
    claim_id: int,
    payload: PayoutCreateRequest,
    request: Request,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    claim = db.get(Claim, claim_id)
    if claim is None:
        raise HTTPException(status_code=404, detail="Claim not found")
    authorize_repository(db, user, claim.bounty.repository, AuthorizationRole.ADMIN, request)
    if not settings.PAYOUTS_ENABLED:
        raise HTTPException(status_code=503, detail="Payouts are disabled")
    from app.models.payout_integration import TreasuryAccount

    treasury_account = db.get(TreasuryAccount, payload.treasury_account_id)
    if (
        treasury_account is None
        or treasury_account.organization_id != claim.bounty.organization_id
    ):
        raise HTTPException(status_code=404, detail="Treasury not found")
    try:
        payout, created = create_payout(
            db,
            claim=claim,
            idempotency_key=payload.idempotency_key,
            treasury_account=treasury_account,
        )
    except BountyConflictError as exc:
        raise _conflict(exc) from exc
    if created:
        _audit(
            db, request, user, claim.bounty.repository,
            action="payout.created", resource_type="payout", resource_id=payout.id,
            metadata={
                "claim_id": claim.id, "approval_id": payout.approval_id,
                "amount": str(payout.amount), "currency": payout.currency,
                "destination_chain": payout.destination_chain,
                "destination_address": payout.destination_address,
                "idempotency_key": payout.idempotency_key,
                "treasury_account_id": payout.treasury_account_id,
                "provider_key": payout.provider_key,
            },
        )
    db.commit()
    return payout


@router.get("/organizations/{organization_id}/payouts")
def list_organization_payouts(
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
                "state_counts": {},
                "reserved_value_by_currency": {},
                "confirmed_value_by_currency": {},
            },
        )
    base_query = (
        db.query(Payout)
        .join(Claim, Claim.id == Payout.claim_id)
        .join(Bounty, Bounty.id == Claim.bounty_id)
        .filter(Bounty.repository_id.in_(repository_ids))
    )
    total = base_query.count()
    state_counts = {
        row_state.value: count
        for row_state, count in db.query(Payout.state, func.count(Payout.id))
        .join(Claim, Claim.id == Payout.claim_id)
        .join(Bounty, Bounty.id == Claim.bounty_id)
        .filter(Bounty.repository_id.in_(repository_ids))
        .group_by(Payout.state)
        .all()
    }
    reserved_value = _currency_sums(
        db.query(Payout.currency, func.coalesce(func.sum(Payout.amount), 0))
        .join(Claim, Claim.id == Payout.claim_id)
        .join(Bounty, Bounty.id == Claim.bounty_id)
        .filter(
            Bounty.repository_id.in_(repository_ids),
            Payout.state.in_(RESERVED_PAYOUT_STATES),
        )
        .group_by(Payout.currency)
        .all()
    )
    confirmed_value = _currency_sums(
        db.query(Payout.currency, func.coalesce(func.sum(Payout.amount), 0))
        .join(Claim, Claim.id == Payout.claim_id)
        .join(Bounty, Bounty.id == Claim.bounty_id)
        .filter(
            Bounty.repository_id.in_(repository_ids),
            Payout.state == PayoutState.CONFIRMED,
        )
        .group_by(Payout.currency)
        .all()
    )
    items = (
        base_query.order_by(Payout.updated_at.desc(), Payout.id.desc())
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
            "state_counts": state_counts,
            "reserved_value_by_currency": reserved_value,
            "confirmed_value_by_currency": confirmed_value,
        },
    )


@router.post("/payouts/{payout_id}/authorize", response_model=PayoutRead)
def post_authorize_payout(
    payout_id: int,
    request: Request,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    _require_manual_payout_state_enabled()
    payout = db.get(Payout, payout_id)
    if payout is None:
        raise HTTPException(status_code=404, detail="Payout not found")
    repository = payout.claim.bounty.repository
    authorize_repository(db, user, repository, AuthorizationRole.ADMIN, request)
    if payout.treasury_account_id is not None:
        raise HTTPException(
            status_code=409,
            detail="Integrated payouts require treasury approvals",
        )
    try:
        authorize_payout(db, payout, user.id)
    except BountyConflictError as exc:
        raise _conflict(exc) from exc
    _audit(
        db, request, user, repository,
        action="payout.authorized", resource_type="payout", resource_id=payout.id,
        metadata={"approval_id": payout.approval_id},
    )
    db.commit()
    return payout


@router.post(
    "/payouts/{payout_id}/attempts",
    response_model=PayoutAttemptRead,
    status_code=201,
)
def post_payout_attempt(
    payout_id: int,
    payload: AttemptCreate,
    request: Request,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    _require_manual_payout_state_enabled()
    payout = db.get(Payout, payout_id)
    if payout is None:
        raise HTTPException(status_code=404, detail="Payout not found")
    repository = payout.claim.bounty.repository
    authorize_repository(db, user, repository, AuthorizationRole.ADMIN, request)
    if payout.treasury_account_id is not None:
        raise HTTPException(
            status_code=409,
            detail="Integrated payouts must use the configured provider",
        )
    try:
        attempt, created = start_payout_attempt(
            db, payout=payout, idempotency_key=payload.idempotency_key,
            provider=payload.provider,
        )
    except BountyConflictError as exc:
        raise _conflict(exc) from exc
    if created:
        _audit(
            db, request, user, repository,
            action="payout.submission_started", resource_type="payout_attempt",
            resource_id=attempt.id,
            metadata={
                "payout_id": payout.id, "attempt_number": attempt.attempt_number,
                "idempotency_key": attempt.idempotency_key,
                "request_hash": attempt.request_hash,
            },
        )
    db.commit()
    return attempt


@router.post("/payout-attempts/{attempt_id}/submitted", response_model=PayoutAttemptRead)
def post_attempt_submitted(
    attempt_id: int,
    payload: AttemptSubmitted,
    request: Request,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    _require_manual_payout_state_enabled()
    attempt = db.get(PayoutAttempt, attempt_id)
    if attempt is None:
        raise HTTPException(status_code=404, detail="Payout attempt not found")
    repository = attempt.payout.claim.bounty.repository
    authorize_repository(db, user, repository, AuthorizationRole.ADMIN, request)
    if attempt.payout.treasury_account_id is not None:
        raise HTTPException(
            status_code=409,
            detail="Integrated payout state is provider-controlled",
        )
    try:
        mark_attempt_submitted(
            db, attempt=attempt, transaction_hash=payload.transaction_hash
        )
    except BountyConflictError as exc:
        raise _conflict(exc) from exc
    _audit(
        db, request, user, repository,
        action="payout.submitted", resource_type="payout_attempt",
        resource_id=attempt.id,
        metadata={"payout_id": attempt.payout_id, "transaction_hash": attempt.transaction_hash},
    )
    emit_domain_event(
        db,
        event_type="payout.submitted",
        organization_id=repository.organization_id,
        repository_id=repository.id,
        aggregate_type="payout",
        aggregate_id=attempt.payout_id,
        event_identity=f"{attempt.id}:submitted",
        recipient_user_ids=[attempt.payout.claim.claimant_user_id],
        actor_user_id=user.id,
        payload={
            "pull_request_title": attempt.payout.claim.pull_request.title,
            "repository": repository.full_name,
            "payout_id": attempt.payout_id,
            "transaction_hash": attempt.transaction_hash,
        },
    )
    db.commit()
    return attempt


@router.post("/payout-attempts/{attempt_id}/failed", response_model=PayoutAttemptRead)
def post_attempt_failed(
    attempt_id: int,
    payload: AttemptFailed,
    request: Request,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    _require_manual_payout_state_enabled()
    attempt = db.get(PayoutAttempt, attempt_id)
    if attempt is None:
        raise HTTPException(status_code=404, detail="Payout attempt not found")
    repository = attempt.payout.claim.bounty.repository
    authorize_repository(db, user, repository, AuthorizationRole.ADMIN, request)
    if attempt.payout.treasury_account_id is not None:
        raise HTTPException(
            status_code=409,
            detail="Integrated payout state is provider-controlled",
        )
    try:
        mark_attempt_failed(db, attempt=attempt, error=payload.error)
    except BountyConflictError as exc:
        raise _conflict(exc) from exc
    _audit(
        db, request, user, repository,
        action="payout.failed", resource_type="payout_attempt", resource_id=attempt.id,
        metadata={"payout_id": attempt.payout_id, "error": payload.error},
    )
    emit_domain_event(
        db,
        event_type="payout.failed",
        organization_id=repository.organization_id,
        repository_id=repository.id,
        aggregate_type="payout",
        aggregate_id=attempt.payout_id,
        event_identity=f"{attempt.id}:failed",
        recipient_user_ids=[attempt.payout.claim.claimant_user_id],
        actor_user_id=user.id,
        payload={
            "pull_request_title": attempt.payout.claim.pull_request.title,
            "repository": repository.full_name,
            "payout_id": attempt.payout_id,
            "error": payload.error,
        },
    )
    db.commit()
    return attempt


@router.post("/payouts/{payout_id}/confirm", response_model=PayoutRead)
def post_confirm_payout(
    payout_id: int,
    payload: AttemptSubmitted,
    request: Request,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    _require_manual_payout_state_enabled()
    payout = db.get(Payout, payout_id)
    if payout is None:
        raise HTTPException(status_code=404, detail="Payout not found")
    repository = payout.claim.bounty.repository
    authorize_repository(db, user, repository, AuthorizationRole.ADMIN, request)
    if payout.treasury_account_id is not None:
        raise HTTPException(
            status_code=409,
            detail="Integrated payouts are confirmed by reconciliation",
        )
    try:
        confirm_payout(
            db, payout=payout, transaction_hash=payload.transaction_hash
        )
    except BountyConflictError as exc:
        raise _conflict(exc) from exc
    _audit(
        db, request, user, repository,
        action="payout.confirmed", resource_type="payout", resource_id=payout.id,
        metadata={
            "claim_id": payout.claim_id, "transaction_hash": payout.transaction_hash,
            "amount": str(payout.amount), "currency": payout.currency,
        },
    )
    emit_domain_event(
        db,
        event_type="payout.confirmed",
        organization_id=repository.organization_id,
        repository_id=repository.id,
        aggregate_type="payout",
        aggregate_id=payout.id,
        event_identity=f"{payout.id}:confirmed",
        recipient_user_ids=[payout.claim.claimant_user_id],
        actor_user_id=user.id,
        payload={
            "pull_request_title": payout.claim.pull_request.title,
            "repository": repository.full_name,
            "payout_id": payout.id,
            "amount": str(payout.amount),
            "currency": payout.currency,
            "transaction_hash": payout.transaction_hash,
        },
    )
    db.commit()
    return payout
