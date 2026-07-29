from __future__ import annotations

from datetime import datetime
from decimal import Decimal, InvalidOperation

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.analysis.base import stable_hash
from app.models.bounty_domain import (
    AssignmentStatus,
    Bounty,
    BountyAssignment,
    BountyPolicy,
    BountyStatus,
    Claim,
    ClaimStatus,
    FundingStatus,
    Issue,
    IssueState,
    Payout,
    PayoutAttempt,
    PayoutAttemptState,
    PayoutState,
    Wallet,
    WalletStatus,
)
from app.models.pull_request import EligibilityState, PullRequestState
from app.models.repository import Repository
from app.models.review_domain import Approval, ApprovalOutcome, EligibilityDecisionStatus


DEFAULT_BOUNTY_RULES = {
    "allowed_currencies": ["USDC"],
    "minimum_amount": 1.0,
    "maximum_amount": 10000.0,
    "require_funding": True,
    "require_assignment": True,
    "require_verified_wallet": True,
    "require_current_eligibility": True,
}


class BountyConflictError(RuntimeError):
    pass


class BountyPolicyError(ValueError):
    pass


def validate_bounty_policy(rules: dict) -> None:
    if set(rules) != set(DEFAULT_BOUNTY_RULES):
        raise BountyPolicyError(
            "Bounty policy must define exactly: "
            + ", ".join(sorted(DEFAULT_BOUNTY_RULES))
        )
    currencies = rules["allowed_currencies"]
    if (
        not isinstance(currencies, list)
        or not currencies
        or any(not isinstance(item, str) or not item.strip() for item in currencies)
        or len(currencies) != len(set(currencies))
    ):
        raise BountyPolicyError("allowed_currencies must be distinct currency codes")
    try:
        if isinstance(rules["minimum_amount"], bool) or isinstance(
            rules["maximum_amount"], bool
        ):
            raise InvalidOperation
        minimum = Decimal(str(rules["minimum_amount"]))
        maximum = Decimal(str(rules["maximum_amount"]))
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise BountyPolicyError("Bounty amount limits must be numeric") from exc
    if minimum <= 0 or maximum < minimum:
        raise BountyPolicyError("Bounty amount limits are invalid")
    for key in (
        "require_funding",
        "require_assignment",
        "require_verified_wallet",
        "require_current_eligibility",
    ):
        if not isinstance(rules[key], bool):
            raise BountyPolicyError(f"{key} must be a boolean")


def bounty_policy_for_repository(db: Session, repository: Repository) -> BountyPolicy:
    if repository.bounty_policy is not None:
        return repository.bounty_policy
    validate_bounty_policy(DEFAULT_BOUNTY_RULES)
    digest = stable_hash(DEFAULT_BOUNTY_RULES)
    policy = (
        db.query(BountyPolicy)
        .filter(
            BountyPolicy.repository_id == repository.id,
            BountyPolicy.policy_hash == digest,
        )
        .first()
    )
    if policy is None:
        policy = BountyPolicy(
            organization_id=repository.organization_id,
            repository_id=repository.id,
            version="default-v1",
            name="Default funded bounty policy",
            rules=DEFAULT_BOUNTY_RULES,
            policy_hash=digest,
        )
        db.add(policy)
        db.flush()
    repository.bounty_policy_id = policy.id
    repository.bounty_policy = policy
    db.flush()
    return policy


def set_bounty_policy(
    db: Session,
    *,
    repository: Repository,
    name: str,
    rules: dict,
    created_by_user_id: int,
) -> BountyPolicy:
    validate_bounty_policy(rules)
    digest = stable_hash(rules)
    policy = (
        db.query(BountyPolicy)
        .filter(
            BountyPolicy.repository_id == repository.id,
            BountyPolicy.policy_hash == digest,
        )
        .first()
    )
    if policy is None:
        policy = BountyPolicy(
            organization_id=repository.organization_id,
            repository_id=repository.id,
            version=f"policy-{digest[:16]}",
            name=name,
            rules=rules,
            policy_hash=digest,
            created_by_user_id=created_by_user_id,
        )
        db.add(policy)
        db.flush()
    repository.bounty_policy_id = policy.id
    repository.bounty_policy = policy
    db.flush()
    return policy


def create_issue(
    db: Session,
    *,
    repository: Repository,
    github_issue_id: int,
    number: int,
    title: str,
    url: str | None,
    description: str | None = None,
    state: IssueState = IssueState.OPEN,
) -> Issue:
    issue = (
        db.query(Issue)
        .filter(
            Issue.repository_id == repository.id,
            Issue.github_issue_id == github_issue_id,
        )
        .first()
    )
    if issue is None:
        issue = Issue(
            organization_id=repository.organization_id,
            repository_id=repository.id,
            github_issue_id=github_issue_id,
            number=number,
            title=title,
            description=description,
            url=url,
            state=state,
        )
        db.add(issue)
    else:
        issue.number = number
        issue.title = title
        issue.description = description
        issue.url = url
        issue.state = state
    db.flush()
    return issue


def create_bounty(
    db: Session,
    *,
    repository: Repository,
    issue: Issue,
    amount: Decimal,
    currency: str,
    expires_at: datetime | None,
    created_by_user_id: int,
) -> Bounty:
    if issue.repository_id != repository.id or issue.state != IssueState.OPEN:
        raise BountyConflictError("Bounty requires an open issue in this repository")
    policy = bounty_policy_for_repository(db, repository)
    if repository.eligibility_policy_id is None:
        from app.services.eligibility_service import policy_for_repository

        policy_for_repository(db, repository)
    normalized_currency = currency.upper()
    if normalized_currency not in policy.rules["allowed_currencies"]:
        raise BountyConflictError("Currency is not permitted by the bounty policy")
    if amount < Decimal(str(policy.rules["minimum_amount"])) or amount > Decimal(
        str(policy.rules["maximum_amount"])
    ):
        raise BountyConflictError("Amount is outside the bounty policy limits")
    if expires_at is not None and expires_at <= datetime.utcnow():
        raise BountyConflictError("Bounty expiration must be in the future")
    bounty = Bounty(
        organization_id=repository.organization_id,
        repository_id=repository.id,
        issue_id=issue.id,
        bounty_policy_id=policy.id,
        eligibility_policy_id=repository.eligibility_policy_id,
        amount=amount,
        currency=normalized_currency,
        status=BountyStatus.DRAFT,
        funding_status=FundingStatus.UNFUNDED,
        expires_at=expires_at,
        created_by_user_id=created_by_user_id,
    )
    db.add(bounty)
    db.flush()
    return bounty


def mark_bounty_funded(db: Session, bounty: Bounty) -> Bounty:
    if bounty.status != BountyStatus.DRAFT:
        raise BountyConflictError("Only draft bounties can be funded")
    bounty.funding_status = FundingStatus.FUNDED
    bounty.status = BountyStatus.OPEN
    db.flush()
    return bounty


def assign_bounty(
    db: Session,
    *,
    bounty: Bounty,
    assignee_user_id: int,
    assigned_by_user_id: int,
    pull_request=None,
) -> BountyAssignment:
    if bounty.status != BountyStatus.OPEN:
        raise BountyConflictError("Bounty is not open for assignment")
    if bounty.funding_status != FundingStatus.FUNDED:
        raise BountyConflictError("Bounty must be funded before assignment")
    if pull_request is not None and (
        pull_request.repo_id != bounty.repository_id
        or pull_request.author_id != assignee_user_id
    ):
        raise BountyConflictError(
            "Linked pull request must belong to the bounty repository and assignee"
        )
    assignment = BountyAssignment(
        bounty_id=bounty.id,
        assignee_user_id=assignee_user_id,
        pull_request_id=pull_request.id if pull_request is not None else None,
        status=AssignmentStatus.ACTIVE,
        assigned_by_user_id=assigned_by_user_id,
    )
    db.add(assignment)
    bounty.status = BountyStatus.ASSIGNED
    db.flush()
    return assignment


def link_assignment_to_pull_request(
    db: Session, *, assignment: BountyAssignment, pull_request
) -> BountyAssignment:
    if assignment.status != AssignmentStatus.ACTIVE:
        raise BountyConflictError("Only an active assignment can be linked")
    if (
        pull_request.repo_id != assignment.bounty.repository_id
        or pull_request.author_id != assignment.assignee_user_id
    ):
        raise BountyConflictError(
            "Linked pull request must belong to the bounty repository and assignee"
        )
    if (
        assignment.pull_request_id is not None
        and assignment.pull_request_id != pull_request.id
    ):
        raise BountyConflictError("Assignment is already linked to another pull request")
    assignment.pull_request_id = pull_request.id
    db.flush()
    return assignment


def create_wallet(
    db: Session, *, user_id: int, chain: str, address: str
) -> Wallet:
    normalized = address.strip().lower()
    if not normalized:
        raise BountyConflictError("Wallet address is required")
    existing = (
        db.query(Wallet)
        .filter(
            Wallet.user_id == user_id,
            Wallet.chain == chain.lower(),
            Wallet.normalized_address == normalized,
        )
        .first()
    )
    if existing is not None:
        return existing
    wallet = Wallet(
        user_id=user_id,
        chain=chain.lower(),
        address=address.strip(),
        normalized_address=normalized,
        status=WalletStatus.ACTIVE,
        verified=False,
    )
    db.add(wallet)
    db.flush()
    return wallet


def verify_wallet_for_bounty(
    db: Session, *, bounty: Bounty, wallet: Wallet
) -> Wallet:
    assignment = (
        db.query(BountyAssignment)
        .filter(
            BountyAssignment.bounty_id == bounty.id,
            BountyAssignment.assignee_user_id == wallet.user_id,
            BountyAssignment.status == AssignmentStatus.ACTIVE,
        )
        .first()
    )
    if assignment is None:
        raise BountyConflictError(
            "Wallet owner is not the bounty's active assignee"
        )
    if wallet.status != WalletStatus.ACTIVE:
        raise BountyConflictError("Only an active wallet can be verified")
    wallet.verified = True
    db.flush()
    return wallet


def approve_claim(
    db: Session,
    *,
    bounty: Bounty,
    assignment: BountyAssignment,
    pull_request,
    decision,
    claimant_user_id: int,
    wallet: Wallet,
) -> Claim:
    now = datetime.utcnow()
    if bounty.status != BountyStatus.ASSIGNED:
        raise BountyConflictError("Bounty is not assigned")
    if bounty.expires_at is not None and bounty.expires_at <= now:
        raise BountyConflictError("Bounty has expired")
    rules = bounty.bounty_policy.rules
    if rules["require_funding"] and bounty.funding_status != FundingStatus.FUNDED:
        raise BountyConflictError("Bounty is not funded")
    if (
        assignment.bounty_id != bounty.id
        or assignment.status != AssignmentStatus.ACTIVE
        or assignment.assignee_user_id != claimant_user_id
    ):
        raise BountyConflictError("Active bounty assignment does not match claimant")
    if pull_request.id != assignment.pull_request_id and assignment.pull_request_id is not None:
        raise BountyConflictError("Assignment is linked to a different pull request")
    if (
        pull_request.author_id != claimant_user_id
        or pull_request.state != PullRequestState.MERGED
    ):
        raise BountyConflictError("Claimant must author the merged pull request")
    if (
        decision.pr_id != pull_request.id
        or decision.status != EligibilityDecisionStatus.ELIGIBLE
        or (rules["require_current_eligibility"] and not decision.is_current)
        or decision.repository_policy_id != bounty.eligibility_policy_id
    ):
        raise BountyConflictError("Current eligible decision does not match bounty policy")
    approval = (
        db.query(Approval)
        .filter(
            Approval.eligibility_decision_id == decision.id,
            Approval.outcome == ApprovalOutcome.APPROVED,
        )
        .order_by(Approval.created_at.desc())
        .first()
    )
    if approval is None:
        raise BountyConflictError("Eligibility decision has no immutable approval")
    if (
        wallet.user_id != claimant_user_id
        or wallet.status != WalletStatus.ACTIVE
        or (rules["require_verified_wallet"] and not wallet.verified)
    ):
        raise BountyConflictError("An active verified claimant wallet is required")
    existing = (
        db.query(Claim)
        .filter(
            Claim.bounty_id == bounty.id,
            Claim.status.in_([ClaimStatus.APPROVED, ClaimStatus.PAID]),
        )
        .first()
    )
    if existing is not None:
        return existing
    assignment.pull_request_id = pull_request.id
    assignment.status = AssignmentStatus.COMPLETED
    assignment.completed_at = now
    bounty.status = BountyStatus.CLOSED
    claim = Claim(
        bounty_id=bounty.id,
        assignment_id=assignment.id,
        pull_request_id=pull_request.id,
        eligibility_decision_id=decision.id,
        approval_id=approval.id,
        claimant_user_id=claimant_user_id,
        wallet_id=wallet.id,
        amount=bounty.amount,
        currency=bounty.currency,
        destination_chain=wallet.chain,
        destination_address=wallet.address,
        status=ClaimStatus.APPROVED,
    )
    db.add(claim)
    db.flush()
    return claim


def create_payout(
    db: Session,
    *,
    claim: Claim,
    idempotency_key: str,
    treasury_account,
) -> tuple[Payout, bool]:
    existing_key = (
        db.query(Payout)
        .filter(Payout.idempotency_key == idempotency_key)
        .first()
    )
    if existing_key is not None:
        if existing_key.claim_id != claim.id:
            raise BountyConflictError("Idempotency key belongs to another payout")
        return existing_key, False
    existing_claim = db.query(Payout).filter(Payout.claim_id == claim.id).first()
    if existing_claim is not None:
        return existing_claim, False
    if claim.status != ClaimStatus.APPROVED:
        raise BountyConflictError("Only an approved claim can create a payout")
    if treasury_account is None:
        raise BountyConflictError("A treasury account is required")
    if treasury_account.organization_id != claim.bounty.organization_id:
        raise BountyConflictError("Treasury belongs to another organization")
    if (
        treasury_account.chain.lower() != claim.destination_chain.lower()
        or treasury_account.currency.upper() != claim.currency.upper()
    ):
        raise BountyConflictError(
            "Treasury chain and currency must match the approved claim"
        )
    payout = Payout(
        claim_id=claim.id,
        approval_id=claim.approval_id,
        amount=claim.amount,
        currency=claim.currency,
        destination_chain=claim.destination_chain,
        destination_address=claim.destination_address,
        idempotency_key=idempotency_key,
        treasury_account_id=treasury_account.id,
        provider_key=treasury_account.provider_key,
        required_confirmations=treasury_account.required_confirmations,
        state=PayoutState.CREATED,
    )
    db.add(payout)
    db.flush()
    return payout, True


def authorize_payout(db: Session, payout: Payout, user_id: int) -> Payout:
    if payout.state != PayoutState.CREATED:
        raise BountyConflictError("Payout is not awaiting authorization")
    payout.state = PayoutState.AUTHORIZED
    payout.authorized_by_user_id = user_id
    payout.authorized_at = datetime.utcnow()
    db.flush()
    return payout


def start_payout_attempt(
    db: Session,
    *,
    payout: Payout,
    idempotency_key: str,
    provider: str,
) -> tuple[PayoutAttempt, bool]:
    existing = (
        db.query(PayoutAttempt)
        .filter(PayoutAttempt.idempotency_key == idempotency_key)
        .first()
    )
    if existing is not None:
        if existing.payout_id != payout.id:
            raise BountyConflictError("Attempt idempotency key belongs to another payout")
        return existing, False
    if payout.state not in {PayoutState.AUTHORIZED, PayoutState.FAILED}:
        raise BountyConflictError("Payout is not ready for submission")
    attempt_number = (
        db.query(func.max(PayoutAttempt.attempt_number))
        .filter(PayoutAttempt.payout_id == payout.id)
        .scalar()
        or 0
    ) + 1
    request_hash = stable_hash(
        {
            "payout_id": payout.id,
            "approval_id": payout.approval_id,
            "amount": str(payout.amount),
            "currency": payout.currency,
            "destination_chain": payout.destination_chain,
            "destination_address": payout.destination_address,
            "attempt_number": attempt_number,
            "provider": provider,
        }
    )
    attempt = PayoutAttempt(
        payout_id=payout.id,
        attempt_number=attempt_number,
        idempotency_key=idempotency_key,
        state=PayoutAttemptState.SUBMITTING,
        provider=provider,
        request_hash=request_hash,
    )
    db.add(attempt)
    payout.state = PayoutState.SUBMITTING
    payout.failure_reason = None
    db.flush()
    return attempt, True


def mark_attempt_submitted(
    db: Session,
    *,
    attempt: PayoutAttempt,
    transaction_hash: str | None,
    provider_reference: str | None = None,
    explorer_url: str | None = None,
    provider_response: dict | None = None,
) -> PayoutAttempt:
    if (
        attempt.state not in {
            PayoutAttemptState.SUBMITTING,
            PayoutAttemptState.SUBMISSION_UNKNOWN,
        }
        or attempt.payout.state not in {
            PayoutState.SUBMITTING,
            PayoutState.SUBMISSION_UNKNOWN,
        }
    ):
        raise BountyConflictError("Attempt is not currently submitting")
    attempt.state = PayoutAttemptState.SUBMITTED
    attempt.transaction_hash = transaction_hash
    attempt.provider_reference = provider_reference or attempt.provider_reference
    attempt.explorer_url = explorer_url
    attempt.provider_response = provider_response or attempt.provider_response
    attempt.submitted_at = datetime.utcnow()
    attempt.payout.state = PayoutState.SUBMITTED
    attempt.payout.transaction_hash = transaction_hash
    attempt.payout.provider_reference = (
        provider_reference or attempt.payout.provider_reference
    )
    attempt.payout.explorer_url = explorer_url
    db.flush()
    return attempt


def mark_attempt_failed(
    db: Session, *, attempt: PayoutAttempt, error: str
) -> PayoutAttempt:
    if attempt.state not in {
        PayoutAttemptState.SUBMITTING,
        PayoutAttemptState.SUBMISSION_UNKNOWN,
    }:
        raise BountyConflictError("Only an unresolved attempt can fail")
    now = datetime.utcnow()
    attempt.state = PayoutAttemptState.FAILED
    attempt.error = error
    attempt.completed_at = now
    attempt.payout.state = PayoutState.FAILED
    attempt.payout.failure_reason = error
    db.flush()
    return attempt


def confirm_payout(
    db: Session, *, payout: Payout, transaction_hash: str
) -> Payout:
    if payout.state != PayoutState.SUBMITTED:
        raise BountyConflictError("Payout must be submitted before confirmation")
    if payout.transaction_hash != transaction_hash:
        raise BountyConflictError("Confirmation transaction hash does not match")
    now = datetime.utcnow()
    payout.state = PayoutState.CONFIRMED
    payout.confirmed_at = now
    payout.claim.status = ClaimStatus.PAID
    payout.claim.bounty.status = BountyStatus.PAID
    payout.claim.bounty.funding_status = FundingStatus.EXHAUSTED
    payout.claim.pull_request.eligibility_state = EligibilityState.PAID
    db.flush()
    return payout
