from __future__ import annotations

from datetime import datetime, timedelta
from decimal import Decimal

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.analysis.base import stable_hash
from app.core.config import settings
from app.db.session import SessionLocal
from app.models.authorization import Organization
from app.models.bounty_domain import (
    ClaimStatus,
    Payout,
    PayoutAttempt,
    PayoutAttemptState,
    PayoutState,
)
from app.models.payout_integration import (
    LedgerEntryType,
    PayoutLedgerEntry,
    PayoutReconciliation,
    ReconciliationOutcome,
    TreasuryAccount,
    TreasuryApproval,
    TreasuryApprovalDecision,
    TreasuryBalanceSnapshot,
    TreasuryEnvironment,
    TreasuryStatus,
)
from app.services.bounty_service import (
    BountyConflictError,
    confirm_payout,
    mark_attempt_failed,
    mark_attempt_submitted,
    start_payout_attempt,
)
from app.services.notification_service import emit_domain_event
from app.services.payout_providers import (
    PayoutProvider,
    PayoutProviderStatus,
    PayoutSubmissionRequest,
    PayoutSubmissionResult,
    ProviderTransferStatus,
    LedgerPayoutProvider,
    TreasuryBalanceProvider,
    TreasuryBalanceResult,
    payout_provider,
)


class PayoutControlError(BountyConflictError):
    pass


class PayoutProviderUnavailable(RuntimeError):
    pass


def _positive_amount(value: Decimal, label: str) -> Decimal:
    normalized = Decimal(value)
    if normalized <= 0:
        raise PayoutControlError(f"{label} must be positive")
    return normalized


def create_treasury_account(
    db: Session,
    *,
    organization: Organization,
    provider_key: str,
    environment: TreasuryEnvironment,
    chain: str,
    currency: str,
    treasury_address: str,
    asset_contract_address: str | None,
    asset_decimals: int,
    custody_model: str,
    opening_balance: Decimal,
    per_payout_limit: Decimal,
    daily_spending_limit: Decimal,
    manual_approval_threshold: Decimal | None,
    standard_required_approvals: int,
    high_value_required_approvals: int,
    required_confirmations: int,
    simulation_required: bool,
    provider_config: dict,
    created_by_user_id: int,
    providers: dict[str, PayoutProvider] | None = None,
) -> TreasuryAccount:
    provider_key = provider_key.strip().lower()
    chain = chain.strip().lower()
    currency = currency.strip().upper()
    custody_model = custody_model.strip().lower()
    if provider_key == "ledger" and settings.APP_ENV.lower() == "production":
        raise PayoutControlError(
            "The deterministic ledger provider is not available in production"
        )
    if environment == TreasuryEnvironment.MAINNET and not settings.PAYOUTS_ALLOW_MAINNET:
        raise PayoutControlError("Mainnet payouts are disabled")
    if provider_key == "base_sepolia_custody":
        if environment != TreasuryEnvironment.TESTNET or chain != "base-sepolia":
            raise PayoutControlError(
                "Base Sepolia custody must use the Base Sepolia testnet"
            )
        if currency != "USDC":
            raise PayoutControlError("Base Sepolia custody only supports USDC")
        if asset_decimals != 6:
            raise PayoutControlError("Base Sepolia USDC must use 6 decimals")
        if (
            asset_contract_address or ""
        ).lower() != settings.BASE_SEPOLIA_USDC_CONTRACT.lower():
            raise PayoutControlError(
                "Unexpected Base Sepolia USDC contract address"
            )
        if custody_model != "multisig":
            raise PayoutControlError(
                "Blockchain treasury custody must be multisig"
            )
    try:
        provider_instance = payout_provider(provider_key, providers)
    except ValueError as exc:
        raise PayoutControlError(str(exc)) from exc
    treasury_validation = provider_instance.validate_destination(
        destination=treasury_address,
        chain=chain,
        currency=currency,
    )
    if not treasury_validation.valid:
        raise PayoutControlError(
            treasury_validation.reason or "Provider rejected treasury address"
        )
    sensitive_keys = {
        key.lower()
        for key in provider_config
        if any(
            marker in key.lower()
            for marker in ("secret", "token", "password", "private_key", "api_key")
        )
    }
    if sensitive_keys:
        raise PayoutControlError(
            "Provider configuration cannot contain secrets; use environment variables"
        )
    if custody_model not in {"multisig", "managed", "off_chain"}:
        raise PayoutControlError("Unsupported custody model")
    opening_balance = Decimal(opening_balance)
    if opening_balance < 0:
        raise PayoutControlError("Opening balance cannot be negative")
    per_payout_limit = _positive_amount(per_payout_limit, "Per-payout limit")
    daily_spending_limit = _positive_amount(
        daily_spending_limit, "Daily spending limit"
    )
    threshold = (
        _positive_amount(
            manual_approval_threshold, "Manual approval threshold"
        )
        if manual_approval_threshold is not None
        else None
    )
    if standard_required_approvals < 1:
        raise PayoutControlError("At least one treasury approval is required")
    if high_value_required_approvals < standard_required_approvals:
        raise PayoutControlError(
            "High-value approvals cannot be lower than standard approvals"
        )
    if required_confirmations < 1:
        raise PayoutControlError("At least one confirmation is required")
    if asset_decimals < 0 or asset_decimals > 18:
        raise PayoutControlError("Asset decimals must be between 0 and 18")
    treasury = TreasuryAccount(
        organization_id=organization.id,
        provider_key=provider_key,
        environment=environment,
        chain=chain,
        currency=currency,
        treasury_address=treasury_address.strip(),
        asset_contract_address=asset_contract_address,
        asset_decimals=asset_decimals,
        custody_model=custody_model,
        opening_balance=opening_balance,
        per_payout_limit=per_payout_limit,
        daily_spending_limit=daily_spending_limit,
        manual_approval_threshold=threshold,
        standard_required_approvals=standard_required_approvals,
        high_value_required_approvals=high_value_required_approvals,
        required_confirmations=required_confirmations,
        simulation_required=simulation_required,
        status=TreasuryStatus.PAUSED,
        provider_config=provider_config,
        paused_reason="New treasuries require explicit activation",
        created_by_user_id=created_by_user_id,
    )
    db.add(treasury)
    db.flush()
    return treasury


def set_treasury_pause(
    db: Session,
    *,
    treasury: TreasuryAccount,
    paused: bool,
    reason: str,
) -> TreasuryAccount:
    if not reason.strip():
        raise PayoutControlError("A pause-state reason is required")
    treasury.status = (
        TreasuryStatus.PAUSED if paused else TreasuryStatus.ACTIVE
    )
    treasury.paused_reason = reason.strip() if paused else None
    db.flush()
    return treasury


def treasury_ledger_balances(
    db: Session, treasury: TreasuryAccount
) -> dict[str, Decimal]:
    totals = (
        db.query(
            func.coalesce(func.sum(PayoutLedgerEntry.available_delta), 0),
            func.coalesce(func.sum(PayoutLedgerEntry.reserved_delta), 0),
            func.coalesce(func.sum(PayoutLedgerEntry.settled_delta), 0),
        )
        .filter(PayoutLedgerEntry.treasury_account_id == treasury.id)
        .one()
    )
    available_delta, reserved, settled = (Decimal(value) for value in totals)
    return {
        "available": Decimal(treasury.opening_balance) + available_delta,
        "reserved": reserved,
        "settled": settled,
    }


def _ledger_entry(
    db: Session,
    *,
    treasury: TreasuryAccount,
    payout: Payout,
    entry_type: LedgerEntryType,
    available_delta: Decimal,
    reserved_delta: Decimal,
    settled_delta: Decimal,
    idempotency_key: str,
    actor_user_id: int | None,
    metadata: dict,
) -> tuple[PayoutLedgerEntry, bool]:
    existing = (
        db.query(PayoutLedgerEntry)
        .filter(PayoutLedgerEntry.idempotency_key == idempotency_key)
        .first()
    )
    if existing is not None:
        if existing.payout_id != payout.id:
            raise PayoutControlError("Ledger idempotency key belongs elsewhere")
        return existing, False
    entry = PayoutLedgerEntry(
        treasury_account_id=treasury.id,
        payout_id=payout.id,
        entry_type=entry_type,
        currency=payout.currency,
        available_delta=available_delta,
        reserved_delta=reserved_delta,
        settled_delta=settled_delta,
        idempotency_key=idempotency_key,
        entry_metadata=metadata,
        created_by_user_id=actor_user_id,
    )
    db.add(entry)
    db.flush()
    return entry, True


def release_payout_reservation(
    db: Session,
    *,
    payout: Payout,
    reason: str,
    actor_user_id: int | None = None,
) -> tuple[PayoutLedgerEntry | None, bool]:
    """Release a reserved amount once, but never unwind a settlement."""
    treasury = payout.treasury_account
    if treasury is None:
        return None, False
    reservation = (
        db.query(PayoutLedgerEntry)
        .filter(
            PayoutLedgerEntry.payout_id == payout.id,
            PayoutLedgerEntry.entry_type == LedgerEntryType.RESERVATION,
        )
        .first()
    )
    if reservation is None:
        return None, False
    settlement = (
        db.query(PayoutLedgerEntry)
        .filter(
            PayoutLedgerEntry.payout_id == payout.id,
            PayoutLedgerEntry.entry_type == LedgerEntryType.SETTLEMENT,
        )
        .first()
    )
    if settlement is not None:
        raise PayoutControlError("A settled payout reservation cannot be released")
    return _ledger_entry(
        db,
        treasury=treasury,
        payout=payout,
        entry_type=LedgerEntryType.RELEASE,
        available_delta=payout.amount,
        reserved_delta=-payout.amount,
        settled_delta=Decimal("0"),
        idempotency_key=f"payout:{payout.id}:release",
        actor_user_id=actor_user_id,
        metadata={"reason": reason},
    )


def _required_approvals(treasury: TreasuryAccount, payout: Payout) -> int:
    if (
        treasury.manual_approval_threshold is not None
        and payout.amount >= treasury.manual_approval_threshold
    ):
        return treasury.high_value_required_approvals
    return treasury.standard_required_approvals


def _daily_reserved_amount(db: Session, treasury_id: int) -> Decimal:
    day_start = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
    value = (
        db.query(
            func.coalesce(func.sum(-PayoutLedgerEntry.available_delta), 0)
        )
        .filter(
            PayoutLedgerEntry.treasury_account_id == treasury_id,
            PayoutLedgerEntry.entry_type == LedgerEntryType.RESERVATION,
            PayoutLedgerEntry.created_at >= day_start,
        )
        .scalar()
    )
    return Decimal(value or 0)


def approve_treasury_payout(
    db: Session,
    *,
    payout: Payout,
    approver_user_id: int,
    decision: TreasuryApprovalDecision,
    reason: str | None,
    providers: dict[str, PayoutProvider] | None = None,
) -> tuple[TreasuryApproval, bool]:
    if payout.treasury_account is None or payout.provider_key is None:
        raise PayoutControlError(
            "Payout was not created with a treasury snapshot"
        )
    treasury = (
        db.query(TreasuryAccount)
        .filter(TreasuryAccount.id == payout.treasury_account_id)
        .with_for_update()
        .one()
    )
    if payout.claim.status != ClaimStatus.APPROVED:
        raise PayoutControlError("Claim is no longer payable")
    if payout.claim.approval_id != payout.approval_id:
        raise PayoutControlError("Payout approval snapshot does not match claim")
    if approver_user_id == payout.claim.claimant_user_id:
        raise PayoutControlError("Claimants cannot approve their own payout")
    existing = (
        db.query(TreasuryApproval)
        .filter(
            TreasuryApproval.payout_id == payout.id,
            TreasuryApproval.approver_user_id == approver_user_id,
        )
        .first()
    )
    if existing is not None:
        return existing, False
    if payout.state != PayoutState.CREATED:
        raise PayoutControlError("Payout is not awaiting treasury approval")
    approval = TreasuryApproval(
        payout_id=payout.id,
        treasury_account_id=treasury.id,
        approver_user_id=approver_user_id,
        decision=decision,
        reason=reason,
        amount=payout.amount,
        currency=payout.currency,
    )
    db.add(approval)
    db.flush()
    if decision == TreasuryApprovalDecision.REJECTED:
        payout.state = PayoutState.CANCELLED
        payout.failure_reason = reason or "Treasury approval rejected"
        release_payout_reservation(
            db,
            payout=payout,
            reason=payout.failure_reason,
            actor_user_id=approver_user_id,
        )
        db.flush()
        return approval, True
    if settings.PAYOUTS_EMERGENCY_PAUSED:
        raise PayoutControlError("Global payout emergency pause is active")
    if treasury.status != TreasuryStatus.ACTIVE:
        raise PayoutControlError("Treasury is paused")
    if payout.amount > treasury.per_payout_limit:
        raise PayoutControlError("Payout exceeds the treasury per-payout limit")
    provider = payout_provider(payout.provider_key, providers)
    validation = provider.validate_destination(
        destination=payout.destination_address,
        chain=payout.destination_chain,
        currency=payout.currency,
    )
    if not validation.valid:
        raise PayoutControlError(
            validation.reason or "Provider rejected payout destination"
        )
    approvals = (
        db.query(TreasuryApproval)
        .filter(
            TreasuryApproval.payout_id == payout.id,
            TreasuryApproval.decision == TreasuryApprovalDecision.APPROVED,
        )
        .count()
    )
    if approvals < _required_approvals(treasury, payout):
        return approval, True
    balances = treasury_ledger_balances(db, treasury)
    if balances["available"] < payout.amount:
        raise PayoutControlError("Treasury has insufficient available balance")
    if (
        _daily_reserved_amount(db, treasury.id) + payout.amount
        > treasury.daily_spending_limit
    ):
        raise PayoutControlError("Treasury daily spending limit exceeded")
    payout.state = PayoutState.AUTHORIZED
    payout.authorized_by_user_id = approver_user_id
    payout.authorized_at = datetime.utcnow()
    _ledger_entry(
        db,
        treasury=treasury,
        payout=payout,
        entry_type=LedgerEntryType.RESERVATION,
        available_delta=-payout.amount,
        reserved_delta=payout.amount,
        settled_delta=Decimal("0"),
        idempotency_key=f"payout:{payout.id}:reservation",
        actor_user_id=approver_user_id,
        metadata={
            "required_approvals": _required_approvals(treasury, payout),
            "approval_id": payout.approval_id,
        },
    )
    db.flush()
    return approval, True


def _submission_request(
    payout: Payout, attempt: PayoutAttempt
) -> PayoutSubmissionRequest:
    treasury = payout.treasury_account
    if treasury is None:
        raise PayoutControlError("Payout has no treasury snapshot")
    return PayoutSubmissionRequest(
        payout_id=payout.id,
        idempotency_key=attempt.idempotency_key,
        amount=payout.amount,
        currency=payout.currency,
        chain=payout.destination_chain,
        destination=payout.destination_address,
        treasury_address=treasury.treasury_address,
        asset_contract_address=treasury.asset_contract_address,
        asset_decimals=treasury.asset_decimals,
        simulation_required=treasury.simulation_required,
        provider_config=treasury.provider_config,
    )


def _schedule_reconciliation(payout: Payout) -> None:
    payout.next_reconciliation_at = datetime.utcnow() + timedelta(
        seconds=settings.PAYOUT_RECONCILIATION_INTERVAL_SECONDS
    )


def _emit_provider_payout_event(
    db: Session,
    *,
    payout: Payout,
    event_type: str,
    event_identity: str,
    error: str | None = None,
) -> None:
    repository = payout.claim.bounty.repository
    emit_domain_event(
        db,
        event_type=event_type,
        organization_id=repository.organization_id,
        repository_id=repository.id,
        aggregate_type="payout",
        aggregate_id=payout.id,
        event_identity=event_identity,
        recipient_user_ids=[payout.claim.claimant_user_id],
        payload={
            "pull_request_title": payout.claim.pull_request.title,
            "repository": repository.full_name,
            "payout_id": payout.id,
            "provider_reference": payout.provider_reference,
            "transaction_hash": payout.transaction_hash,
            "explorer_url": payout.explorer_url,
            "error": error,
        },
    )


def submit_payout(
    db: Session,
    *,
    payout: Payout,
    idempotency_key: str,
    providers: dict[str, PayoutProvider] | None = None,
) -> tuple[PayoutAttempt, bool]:
    if not settings.PAYOUTS_ENABLED:
        raise PayoutControlError("Payout submission is disabled")
    if settings.PAYOUTS_EMERGENCY_PAUSED:
        raise PayoutControlError("Global payout emergency pause is active")
    if payout.treasury_account is None or payout.provider_key is None:
        raise PayoutControlError("Payout has no treasury provider")
    if payout.treasury_account.status != TreasuryStatus.ACTIVE:
        raise PayoutControlError("Treasury is paused")
    if (
        payout.treasury_account.environment == TreasuryEnvironment.MAINNET
        and not settings.PAYOUTS_ALLOW_MAINNET
    ):
        raise PayoutControlError("Mainnet payouts are disabled")
    attempt, created = start_payout_attempt(
        db,
        payout=payout,
        idempotency_key=idempotency_key,
        provider=payout.provider_key,
    )
    if not created and attempt.state not in {
        PayoutAttemptState.SUBMITTING,
        PayoutAttemptState.SUBMISSION_UNKNOWN,
    }:
        return attempt, False
    provider = payout_provider(payout.provider_key, providers)
    recovered_status = None
    if attempt.state == PayoutAttemptState.SUBMISSION_UNKNOWN:
        try:
            recovered_status = provider.find_by_idempotency_key(
                attempt.idempotency_key
            )
        except Exception:
            recovered_status = None
    try:
        if recovered_status is None:
            result = provider.submit(_submission_request(payout, attempt))
        else:
            result = PayoutSubmissionResult(
                provider_reference=recovered_status.provider_reference,
                status=recovered_status.status,
                transaction_hash=recovered_status.transaction_hash,
                confirmations=recovered_status.confirmations,
                explorer_url=(
                    provider.build_explorer_url(
                        recovered_status.transaction_hash
                    )
                    if recovered_status.transaction_hash
                    else None
                ),
                raw_response=recovered_status.raw_response,
                error=recovered_status.error,
            )
    except Exception as exc:
        attempt.error = str(exc)[:4000]
        attempt.state = PayoutAttemptState.SUBMISSION_UNKNOWN
        attempt.recovery_attempt_count += 1
        payout.state = PayoutState.SUBMISSION_UNKNOWN
        payout.failure_reason = None
        _schedule_reconciliation(payout)
        if (
            attempt.recovery_attempt_count
            >= settings.PAYOUT_SUBMISSION_RECOVERY_MAX_ATTEMPTS
        ):
            mark_attempt_failed(
                db,
                attempt=attempt,
                error="Provider submission could not be resolved after retries",
            )
            release_payout_reservation(
                db,
                payout=payout,
                reason=attempt.error or "Submission recovery exhausted",
            )
        db.flush()
        raise PayoutProviderUnavailable(str(exc)) from exc
    attempt.provider_reference = result.provider_reference
    attempt.simulation_result = result.simulation_result
    attempt.provider_response = result.raw_response
    payout.provider_reference = result.provider_reference
    payout.observed_confirmations = result.confirmations
    payout.last_status_checked_at = datetime.utcnow()
    if result.status == ProviderTransferStatus.FAILED:
        mark_attempt_failed(
            db,
            attempt=attempt,
            error=result.error or "Provider rejected payout",
        )
        release_payout_reservation(
            db,
            payout=payout,
            reason=attempt.error or "Provider rejected payout",
        )
        _emit_provider_payout_event(
            db,
            payout=payout,
            event_type="payout.failed",
            event_identity=f"{attempt.id}:failed",
            error=attempt.error,
        )
    elif result.status in {
        ProviderTransferStatus.SUBMITTED,
        ProviderTransferStatus.CONFIRMED,
    }:
        transaction_hash = result.transaction_hash
        explorer_url = result.explorer_url or (
            provider.build_explorer_url(transaction_hash)
            if transaction_hash
            else None
        )
        mark_attempt_submitted(
            db,
            attempt=attempt,
            transaction_hash=transaction_hash,
            provider_reference=result.provider_reference,
            explorer_url=explorer_url,
            provider_response=result.raw_response,
        )
        _emit_provider_payout_event(
            db,
            payout=payout,
            event_type="payout.submitted",
            event_identity=f"{attempt.id}:submitted",
        )
        _schedule_reconciliation(payout)
        if (
            result.status == ProviderTransferStatus.CONFIRMED
            and result.confirmations >= payout.required_confirmations
        ):
            _record_reconciliation(
                db,
                payout=payout,
                attempt=attempt,
                status=PayoutProviderStatus(
                    provider_reference=result.provider_reference,
                    status=result.status,
                    transaction_hash=result.transaction_hash,
                    confirmations=result.confirmations,
                    raw_response=result.raw_response,
                    error=result.error,
                ),
            )
            _settle_confirmed_payout(
                db,
                payout=payout,
                transaction_hash=transaction_hash,
                actor_user_id=None,
            )
    else:
        _schedule_reconciliation(payout)
    db.flush()
    return attempt, created


def _latest_attempt(db: Session, payout_id: int) -> PayoutAttempt | None:
    return (
        db.query(PayoutAttempt)
        .filter(PayoutAttempt.payout_id == payout_id)
        .order_by(PayoutAttempt.attempt_number.desc())
        .first()
    )


def _settle_confirmed_payout(
    db: Session,
    *,
    payout: Payout,
    transaction_hash: str | None,
    actor_user_id: int | None,
) -> None:
    if not transaction_hash:
        raise PayoutControlError("Confirmed payout has no transaction hash")
    if payout.state == PayoutState.CONFIRMED:
        return
    confirm_payout(db, payout=payout, transaction_hash=transaction_hash)
    treasury = payout.treasury_account
    if treasury is None:
        raise PayoutControlError("Confirmed payout has no treasury")
    _ledger_entry(
        db,
        treasury=treasury,
        payout=payout,
        entry_type=LedgerEntryType.SETTLEMENT,
        available_delta=Decimal("0"),
        reserved_delta=-payout.amount,
        settled_delta=payout.amount,
        idempotency_key=f"payout:{payout.id}:settlement",
        actor_user_id=actor_user_id,
        metadata={
            "transaction_hash": transaction_hash,
            "provider_reference": payout.provider_reference,
        },
    )
    payout.next_reconciliation_at = None
    repository = payout.claim.bounty.repository
    emit_domain_event(
        db,
        event_type="payout.confirmed",
        organization_id=repository.organization_id,
        repository_id=repository.id,
        aggregate_type="payout",
        aggregate_id=payout.id,
        event_identity=f"{payout.id}:confirmed",
        recipient_user_ids=[payout.claim.claimant_user_id],
        actor_user_id=actor_user_id,
        payload={
            "pull_request_title": payout.claim.pull_request.title,
            "repository": repository.full_name,
            "payout_id": payout.id,
            "amount": str(payout.amount),
            "currency": payout.currency,
            "transaction_hash": transaction_hash,
            "explorer_url": payout.explorer_url,
        },
    )


def _record_reconciliation(
    db: Session,
    *,
    payout: Payout,
    attempt: PayoutAttempt | None,
    status: PayoutProviderStatus,
    outcome: ReconciliationOutcome | None = None,
) -> tuple[PayoutReconciliation, bool]:
    resolved_outcome = outcome or ReconciliationOutcome(status.status.value)
    digest = stable_hash(
        {
            "provider_reference": status.provider_reference,
            "status": status.status.value,
            "transaction_hash": status.transaction_hash,
            "confirmations": status.confirmations,
            "error": status.error,
        }
    )
    existing = (
        db.query(PayoutReconciliation)
        .filter(
            PayoutReconciliation.payout_id == payout.id,
            PayoutReconciliation.provider_status_hash == digest,
        )
        .first()
    )
    if existing is not None:
        return existing, False
    record = PayoutReconciliation(
        payout_id=payout.id,
        payout_attempt_id=attempt.id if attempt else None,
        provider_key=payout.provider_key,
        provider_reference=status.provider_reference,
        outcome=resolved_outcome,
        confirmations=status.confirmations,
        transaction_hash=status.transaction_hash,
        provider_status_hash=digest,
        provider_response=status.raw_response,
        error=status.error,
    )
    db.add(record)
    db.flush()
    return record, True


def reconcile_payout(
    db: Session,
    *,
    payout: Payout,
    providers: dict[str, PayoutProvider] | None = None,
) -> PayoutReconciliation:
    if payout.state not in {
        PayoutState.SUBMITTING,
        PayoutState.SUBMISSION_UNKNOWN,
        PayoutState.SUBMITTED,
    }:
        raise PayoutControlError("Payout is not awaiting provider reconciliation")
    if not payout.provider_key:
        raise PayoutControlError("Payout has no provider")
    provider = payout_provider(payout.provider_key, providers)
    attempt = _latest_attempt(db, payout.id)
    if attempt is None:
        raise PayoutControlError("Payout has no provider attempt")
    try:
        if payout.provider_reference:
            status = provider.get_status(payout.provider_reference)
        else:
            status = provider.find_by_idempotency_key(attempt.idempotency_key)
            if status is None:
                raise LookupError(
                    "Provider has no transfer for the idempotency key"
                )
    except Exception as exc:
        now = datetime.utcnow()
        submission_unresolved = attempt.state in {
            PayoutAttemptState.SUBMITTING,
            PayoutAttemptState.SUBMISSION_UNKNOWN,
        }
        if submission_unresolved:
            attempt.recovery_attempt_count += 1
            attempt.last_checked_at = now
            attempt.state = PayoutAttemptState.SUBMISSION_UNKNOWN
            payout.state = PayoutState.SUBMISSION_UNKNOWN
        error_status = PayoutProviderStatus(
            provider_reference=(
                payout.provider_reference
                or f"idempotency:{attempt.idempotency_key}"
            ),
            status=ProviderTransferStatus.PENDING,
            confirmations=payout.observed_confirmations,
            raw_response={"checked_at": now.isoformat()},
            error=str(exc)[:4000],
        )
        record, _ = _record_reconciliation(
            db,
            payout=payout,
            attempt=attempt,
            status=error_status,
            outcome=ReconciliationOutcome.ERROR,
        )
        payout.last_status_checked_at = now
        if (
            submission_unresolved
            and
            attempt.recovery_attempt_count
            >= settings.PAYOUT_SUBMISSION_RECOVERY_MAX_ATTEMPTS
        ):
            mark_attempt_failed(
                db,
                attempt=attempt,
                error="Provider submission could not be resolved after retries",
            )
            payout.next_reconciliation_at = None
            release_payout_reservation(
                db,
                payout=payout,
                reason=attempt.error,
            )
        else:
            _schedule_reconciliation(payout)
        db.flush()
        return record
    if payout.provider_reference != status.provider_reference:
        payout.provider_reference = status.provider_reference
    if attempt.provider_reference != status.provider_reference:
        attempt.provider_reference = status.provider_reference
    record, _ = _record_reconciliation(
        db, payout=payout, attempt=attempt, status=status
    )
    payout.observed_confirmations = max(
        payout.observed_confirmations, status.confirmations
    )
    payout.last_status_checked_at = datetime.utcnow()
    if status.transaction_hash and not payout.transaction_hash:
        payout.transaction_hash = status.transaction_hash
        payout.explorer_url = provider.build_explorer_url(status.transaction_hash)
    if (
        attempt is not None
        and attempt.state == PayoutAttemptState.SUBMITTING
    ):
        attempt.last_checked_at = payout.last_status_checked_at
    if status.status == ProviderTransferStatus.FAILED:
        if attempt.state in {
            PayoutAttemptState.SUBMITTING,
            PayoutAttemptState.SUBMISSION_UNKNOWN,
        }:
            mark_attempt_failed(
                db,
                attempt=attempt,
                error=status.error or "Provider reported payout failure",
            )
        else:
            payout.state = PayoutState.FAILED
            payout.failure_reason = (
                status.error or "Provider reported payout failure"
            )
        payout.next_reconciliation_at = None
        release_payout_reservation(
            db,
            payout=payout,
            reason=payout.failure_reason or "Provider reported payout failure",
        )
        _emit_provider_payout_event(
            db,
            event_type="payout.failed",
            payout=payout,
            event_identity=f"provider_failed:{record.id}",
            error=payout.failure_reason,
        )
    elif status.status in {
        ProviderTransferStatus.SUBMITTED,
        ProviderTransferStatus.CONFIRMED,
    }:
        if attempt.state in {
            PayoutAttemptState.SUBMITTING,
            PayoutAttemptState.SUBMISSION_UNKNOWN,
        }:
            mark_attempt_submitted(
                db,
                attempt=attempt,
                transaction_hash=status.transaction_hash,
                provider_reference=status.provider_reference,
                explorer_url=(
                    provider.build_explorer_url(status.transaction_hash)
                    if status.transaction_hash
                    else None
                ),
                provider_response=status.raw_response,
            )
            _emit_provider_payout_event(
                db,
                payout=payout,
                event_type="payout.submitted",
                event_identity=f"{attempt.id}:submitted",
            )
        _schedule_reconciliation(payout)
        if (
            status.status == ProviderTransferStatus.CONFIRMED
            and status.confirmations >= payout.required_confirmations
        ):
            _settle_confirmed_payout(
                db,
                payout=payout,
                transaction_hash=status.transaction_hash,
                actor_user_id=None,
            )
    else:
        _schedule_reconciliation(payout)
    db.flush()
    return record


def reconcile_due_payouts(
    providers: dict[str, PayoutProvider] | None = None,
) -> dict[str, int]:
    db: Session = SessionLocal()
    checked = confirmed = failed = errors = 0
    try:
        now = datetime.utcnow()
        payout_ids = [
            row[0]
            for row in (
                db.query(Payout.id)
                .filter(
                    Payout.state.in_(
                        [
                            PayoutState.SUBMITTING,
                            PayoutState.SUBMISSION_UNKNOWN,
                            PayoutState.SUBMITTED,
                        ]
                    ),
                    Payout.next_reconciliation_at.is_not(None),
                    Payout.next_reconciliation_at <= now,
                )
                .order_by(Payout.next_reconciliation_at, Payout.id)
                .limit(100)
                .all()
            )
        ]
        for payout_id in payout_ids:
            payout = (
                db.query(Payout)
                .filter(Payout.id == payout_id)
                .with_for_update(skip_locked=True)
                .first()
            )
            if payout is None:
                continue
            try:
                reconcile_payout(db, payout=payout, providers=providers)
                checked += 1
                confirmed += payout.state == PayoutState.CONFIRMED
                failed += payout.state == PayoutState.FAILED
                db.commit()
            except Exception:
                errors += 1
                db.rollback()
        return {
            "checked": checked,
            "confirmed": confirmed,
            "failed": failed,
            "errors": errors,
        }
    finally:
        db.close()


def _record_balance_snapshot(
    db: Session,
    *,
    treasury: TreasuryAccount,
    result: TreasuryBalanceResult,
) -> tuple[TreasuryBalanceSnapshot, bool]:
    digest = stable_hash(
        {
            "treasury_account_id": treasury.id,
            "provider_key": treasury.provider_key,
            "currency": treasury.currency,
            "observed_balance": str(result.observed_balance),
        }
    )
    existing = (
        db.query(TreasuryBalanceSnapshot)
        .filter(
            TreasuryBalanceSnapshot.treasury_account_id == treasury.id,
            TreasuryBalanceSnapshot.balance_hash == digest,
        )
        .first()
    )
    if existing is not None:
        treasury.observed_balance = result.observed_balance
        treasury.last_balance_checked_at = datetime.utcnow()
        return existing, False
    snapshot = TreasuryBalanceSnapshot(
        treasury_account_id=treasury.id,
        provider_key=treasury.provider_key,
        currency=treasury.currency,
        observed_balance=result.observed_balance,
        balance_hash=digest,
        provider_response=result.raw_response,
    )
    db.add(snapshot)
    treasury.observed_balance = result.observed_balance
    treasury.last_balance_checked_at = datetime.utcnow()
    db.flush()
    return snapshot, True


def reconcile_treasury_balance(
    db: Session,
    *,
    treasury: TreasuryAccount,
    providers: dict[str, PayoutProvider] | None = None,
) -> TreasuryBalanceSnapshot:
    provider = payout_provider(treasury.provider_key, providers)
    if isinstance(provider, LedgerPayoutProvider):
        balances = treasury_ledger_balances(db, treasury)
        result = TreasuryBalanceResult(
            observed_balance=treasury.opening_balance - balances["settled"],
            raw_response={"source": "off_chain_ledger"},
        )
    elif isinstance(provider, TreasuryBalanceProvider):
        result = provider.get_balance(
            treasury_address=treasury.treasury_address,
            asset_contract_address=treasury.asset_contract_address,
            currency=treasury.currency,
        )
    else:
        raise PayoutControlError(
            "Configured provider does not expose treasury balance reconciliation"
        )
    snapshot, _ = _record_balance_snapshot(
        db, treasury=treasury, result=result
    )
    return snapshot


def reconcile_treasury_balances(
    providers: dict[str, PayoutProvider] | None = None,
) -> dict[str, int]:
    db: Session = SessionLocal()
    checked = errors = 0
    try:
        treasury_ids = [
            row[0]
            for row in (
                db.query(TreasuryAccount.id)
                .filter(TreasuryAccount.status == TreasuryStatus.ACTIVE)
                .order_by(TreasuryAccount.id)
                .all()
            )
        ]
        for treasury_id in treasury_ids:
            treasury = db.get(TreasuryAccount, treasury_id)
            if treasury is None:
                continue
            try:
                reconcile_treasury_balance(
                    db, treasury=treasury, providers=providers
                )
                db.commit()
                checked += 1
            except Exception:
                db.rollback()
                errors += 1
        return {"checked": checked, "errors": errors}
    finally:
        db.close()
