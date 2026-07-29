from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session

from app.api.authz import authorize_repository, get_current_user
from app.db.session import get_db
from app.models.authorization import (
    AuthorizationRole,
    Organization,
    OrganizationMembership,
)
from app.models.bounty_domain import Payout
from app.models.payout_integration import (
    PayoutLedgerEntry,
    PayoutReconciliation,
    TreasuryAccount,
    TreasuryBalanceSnapshot,
)
from app.models.user import User
from app.schemas.bounty_domain import PayoutAttemptRead, PayoutRead
from app.schemas.payout_integration import (
    LedgerEntryRead,
    PayoutSubmitRequest,
    ReconciliationRead,
    TreasuryApprovalCreate,
    TreasuryApprovalRead,
    TreasuryBalanceSnapshotRead,
    TreasuryCreate,
    TreasuryPauseRequest,
    TreasuryRead,
)
from app.services.audit_service import record_audit_event
from app.services.payout_integration_service import (
    PayoutControlError,
    PayoutProviderUnavailable,
    approve_treasury_payout,
    create_treasury_account,
    reconcile_payout,
    reconcile_treasury_balance,
    set_treasury_pause,
    submit_payout,
    treasury_ledger_balances,
)


router = APIRouter(tags=["payout-integration"])


def _organization_role(
    db: Session,
    *,
    organization_id: int,
    user_id: int,
    allowed: set[AuthorizationRole],
) -> Organization:
    organization = db.get(Organization, organization_id)
    membership = (
        db.query(OrganizationMembership)
        .filter(
            OrganizationMembership.organization_id == organization_id,
            OrganizationMembership.user_id == user_id,
            OrganizationMembership.is_active.is_(True),
            OrganizationMembership.github_verified.is_(True),
        )
        .first()
    )
    if (
        organization is None
        or membership is None
        or membership.role not in allowed
    ):
        raise HTTPException(status_code=404, detail="Organization not found")
    return organization


def _treasury_read(db: Session, treasury: TreasuryAccount) -> dict:
    balances = treasury_ledger_balances(db, treasury)
    return {
        "id": treasury.id,
        "organization_id": treasury.organization_id,
        "provider_key": treasury.provider_key,
        "environment": treasury.environment,
        "chain": treasury.chain,
        "currency": treasury.currency,
        "treasury_address": treasury.treasury_address,
        "asset_contract_address": treasury.asset_contract_address,
        "asset_decimals": treasury.asset_decimals,
        "custody_model": treasury.custody_model,
        "opening_balance": treasury.opening_balance,
        "observed_balance": treasury.observed_balance,
        "available_balance": balances["available"],
        "reserved_balance": balances["reserved"],
        "settled_amount": balances["settled"],
        "per_payout_limit": treasury.per_payout_limit,
        "daily_spending_limit": treasury.daily_spending_limit,
        "manual_approval_threshold": treasury.manual_approval_threshold,
        "standard_required_approvals": treasury.standard_required_approvals,
        "high_value_required_approvals": treasury.high_value_required_approvals,
        "required_confirmations": treasury.required_confirmations,
        "simulation_required": treasury.simulation_required,
        "status": treasury.status,
        "paused_reason": treasury.paused_reason,
        "last_balance_checked_at": treasury.last_balance_checked_at,
        "created_by_user_id": treasury.created_by_user_id,
        "created_at": treasury.created_at,
        "updated_at": treasury.updated_at,
    }


def _payout(
    db: Session,
    payout_id: int,
    user: User,
    request: Request,
) -> Payout:
    payout = db.get(Payout, payout_id)
    if payout is None:
        raise HTTPException(status_code=404, detail="Payout not found")
    authorize_repository(
        db,
        user,
        payout.claim.bounty.repository,
        AuthorizationRole.ADMIN,
        request,
    )
    return payout


@router.get("/payouts/{payout_id}", response_model=PayoutRead)
def get_payout(
    payout_id: int,
    request: Request,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return _payout(db, payout_id, user, request)


@router.get(
    "/organizations/{organization_id}/treasuries",
    response_model=list[TreasuryRead],
)
def list_treasuries(
    organization_id: int,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    _organization_role(
        db,
        organization_id=organization_id,
        user_id=user.id,
        allowed={AuthorizationRole.OWNER, AuthorizationRole.ADMIN},
    )
    treasuries = (
        db.query(TreasuryAccount)
        .filter(TreasuryAccount.organization_id == organization_id)
        .order_by(TreasuryAccount.created_at.desc(), TreasuryAccount.id.desc())
        .all()
    )
    return [_treasury_read(db, treasury) for treasury in treasuries]


@router.post(
    "/organizations/{organization_id}/treasuries",
    response_model=TreasuryRead,
    status_code=201,
)
def post_treasury(
    organization_id: int,
    payload: TreasuryCreate,
    request: Request,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    organization = _organization_role(
        db,
        organization_id=organization_id,
        user_id=user.id,
        allowed={AuthorizationRole.OWNER},
    )
    try:
        treasury = create_treasury_account(
            db,
            organization=organization,
            created_by_user_id=user.id,
            **payload.model_dump(),
        )
    except PayoutControlError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    record_audit_event(
        db,
        action="treasury.created",
        resource_type="treasury_account",
        actor_user_id=user.id,
        organization_id=organization_id,
        resource_id=treasury.id,
        event_metadata={
            "provider_key": treasury.provider_key,
            "environment": treasury.environment.value,
            "chain": treasury.chain,
            "currency": treasury.currency,
            "custody_model": treasury.custody_model,
        },
        request=request,
    )
    db.commit()
    return _treasury_read(db, treasury)


@router.post("/treasuries/{treasury_id}/pause", response_model=TreasuryRead)
def post_treasury_pause(
    treasury_id: int,
    payload: TreasuryPauseRequest,
    request: Request,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    treasury = db.get(TreasuryAccount, treasury_id)
    if treasury is None:
        raise HTTPException(status_code=404, detail="Treasury not found")
    _organization_role(
        db,
        organization_id=treasury.organization_id,
        user_id=user.id,
        allowed={AuthorizationRole.OWNER},
    )
    try:
        set_treasury_pause(
            db,
            treasury=treasury,
            paused=payload.paused,
            reason=payload.reason,
        )
    except PayoutControlError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    record_audit_event(
        db,
        action=(
            "treasury.paused" if payload.paused else "treasury.activated"
        ),
        resource_type="treasury_account",
        actor_user_id=user.id,
        organization_id=treasury.organization_id,
        resource_id=treasury.id,
        event_metadata={"reason": payload.reason},
        request=request,
    )
    db.commit()
    return _treasury_read(db, treasury)


@router.get(
    "/treasuries/{treasury_id}/ledger",
    response_model=list[LedgerEntryRead],
)
def get_treasury_ledger(
    treasury_id: int,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    treasury = db.get(TreasuryAccount, treasury_id)
    if treasury is None:
        raise HTTPException(status_code=404, detail="Treasury not found")
    _organization_role(
        db,
        organization_id=treasury.organization_id,
        user_id=user.id,
        allowed={AuthorizationRole.OWNER, AuthorizationRole.ADMIN},
    )
    return (
        db.query(PayoutLedgerEntry)
        .filter(PayoutLedgerEntry.treasury_account_id == treasury_id)
        .order_by(
            PayoutLedgerEntry.created_at.desc(),
            PayoutLedgerEntry.id.desc(),
        )
        .limit(500)
        .all()
    )


@router.post(
    "/treasuries/{treasury_id}/reconcile-balance",
    response_model=TreasuryBalanceSnapshotRead,
)
def post_treasury_balance_reconciliation(
    treasury_id: int,
    request: Request,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    treasury = db.get(TreasuryAccount, treasury_id)
    if treasury is None:
        raise HTTPException(status_code=404, detail="Treasury not found")
    _organization_role(
        db,
        organization_id=treasury.organization_id,
        user_id=user.id,
        allowed={AuthorizationRole.OWNER, AuthorizationRole.ADMIN},
    )
    try:
        snapshot = reconcile_treasury_balance(db, treasury=treasury)
    except PayoutControlError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    record_audit_event(
        db,
        action="treasury.balance_reconciled",
        resource_type="treasury_balance_snapshot",
        actor_user_id=user.id,
        organization_id=treasury.organization_id,
        resource_id=snapshot.id,
        event_metadata={
            "treasury_account_id": treasury.id,
            "observed_balance": str(snapshot.observed_balance),
            "currency": snapshot.currency,
        },
        request=request,
    )
    db.commit()
    return snapshot


@router.get(
    "/treasuries/{treasury_id}/balance-snapshots",
    response_model=list[TreasuryBalanceSnapshotRead],
)
def get_treasury_balance_snapshots(
    treasury_id: int,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    treasury = db.get(TreasuryAccount, treasury_id)
    if treasury is None:
        raise HTTPException(status_code=404, detail="Treasury not found")
    _organization_role(
        db,
        organization_id=treasury.organization_id,
        user_id=user.id,
        allowed={AuthorizationRole.OWNER, AuthorizationRole.ADMIN},
    )
    return (
        db.query(TreasuryBalanceSnapshot)
        .filter(TreasuryBalanceSnapshot.treasury_account_id == treasury_id)
        .order_by(
            TreasuryBalanceSnapshot.observed_at.desc(),
            TreasuryBalanceSnapshot.id.desc(),
        )
        .limit(500)
        .all()
    )


@router.post(
    "/payouts/{payout_id}/treasury-approvals",
    response_model=TreasuryApprovalRead,
    status_code=201,
)
def post_treasury_approval(
    payout_id: int,
    payload: TreasuryApprovalCreate,
    request: Request,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    payout = _payout(db, payout_id, user, request)
    try:
        approval, _ = approve_treasury_payout(
            db,
            payout=payout,
            approver_user_id=user.id,
            decision=payload.decision,
            reason=payload.reason,
        )
    except PayoutControlError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    record_audit_event(
        db,
        action=f"treasury_approval.{approval.decision.value}",
        resource_type="treasury_approval",
        actor_user_id=user.id,
        organization_id=payout.claim.bounty.organization_id,
        repository_id=payout.claim.bounty.repository_id,
        resource_id=approval.id,
        event_metadata={
            "payout_id": payout.id,
            "treasury_account_id": approval.treasury_account_id,
            "resulting_payout_state": payout.state.value,
        },
        request=request,
    )
    db.commit()
    return approval


@router.post(
    "/payouts/{payout_id}/submit",
    response_model=PayoutAttemptRead,
    status_code=202,
)
def post_provider_submission(
    payout_id: int,
    payload: PayoutSubmitRequest,
    request: Request,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    payout = _payout(db, payout_id, user, request)
    try:
        attempt, _ = submit_payout(
            db,
            payout=payout,
            idempotency_key=payload.idempotency_key,
        )
    except PayoutProviderUnavailable as exc:
        record_audit_event(
            db,
            action="payout.provider_unavailable",
            resource_type="payout",
            actor_user_id=user.id,
            organization_id=payout.claim.bounty.organization_id,
            repository_id=payout.claim.bounty.repository_id,
            resource_id=payout.id,
            event_metadata={"error": str(exc)},
            request=request,
        )
        db.commit()
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except PayoutControlError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    record_audit_event(
        db,
        action="payout.provider_submission",
        resource_type="payout_attempt",
        actor_user_id=user.id,
        organization_id=payout.claim.bounty.organization_id,
        repository_id=payout.claim.bounty.repository_id,
        resource_id=attempt.id,
        event_metadata={
            "payout_id": payout.id,
            "provider": attempt.provider,
            "provider_reference": attempt.provider_reference,
            "transaction_hash": attempt.transaction_hash,
        },
        request=request,
    )
    db.commit()
    return attempt


@router.post(
    "/payouts/{payout_id}/reconcile",
    response_model=ReconciliationRead,
)
def post_reconciliation(
    payout_id: int,
    request: Request,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    payout = _payout(db, payout_id, user, request)
    try:
        reconciliation = reconcile_payout(db, payout=payout)
    except PayoutControlError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    record_audit_event(
        db,
        action="payout.reconciled",
        resource_type="payout_reconciliation",
        actor_user_id=user.id,
        organization_id=payout.claim.bounty.organization_id,
        repository_id=payout.claim.bounty.repository_id,
        resource_id=reconciliation.id,
        event_metadata={
            "payout_id": payout.id,
            "outcome": reconciliation.outcome.value,
            "confirmations": reconciliation.confirmations,
        },
        request=request,
    )
    db.commit()
    return reconciliation


@router.get(
    "/payouts/{payout_id}/reconciliations",
    response_model=list[ReconciliationRead],
)
def get_reconciliations(
    payout_id: int,
    request: Request,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    payout = _payout(db, payout_id, user, request)
    return (
        db.query(PayoutReconciliation)
        .filter(PayoutReconciliation.payout_id == payout.id)
        .order_by(
            PayoutReconciliation.checked_at.desc(),
            PayoutReconciliation.id.desc(),
        )
        .all()
    )
