from __future__ import annotations

from datetime import datetime
from decimal import Decimal, InvalidOperation

from sqlalchemy.orm import Session

from app.analysis.base import stable_hash
from app.models.authorization import AuthorizationRole
from app.models.pull_request import EligibilityState, PullRequest, PullRequestState
from app.models.repository import Repository
from app.models.review_domain import (
    Approval,
    ApprovalOutcome,
    EligibilityDecision,
    EligibilityDecisionStatus,
    FindingSeverity,
    HumanReviewStatus,
    RepositoryPolicy,
    Review,
    ReviewFinding,
    ReviewRecommendation,
)
from app.models.score import Score
from app.models.user import User


DEFAULT_ELIGIBILITY_RULES = {
    "require_merged": True,
    "require_authoritative_score": True,
    "minimum_score": 70.0,
    "human_review_required": True,
    "required_approvals": 1,
    "review_roles": ["owner", "admin", "maintainer", "reviewer"],
    "approval_roles": ["owner", "admin"],
    "separation_of_duties": True,
    "allow_author_review": False,
    "allow_author_approval": False,
}
REQUIRED_RULE_KEYS = frozenset(DEFAULT_ELIGIBILITY_RULES)


class EligibilityConflictError(RuntimeError):
    pass


class RepositoryPolicyError(ValueError):
    pass


def validate_repository_policy(rules: dict) -> None:
    if set(rules) != REQUIRED_RULE_KEYS:
        raise RepositoryPolicyError(
            "Repository policy rules must define exactly: "
            + ", ".join(sorted(REQUIRED_RULE_KEYS))
        )
    boolean_keys = (
        "require_merged",
        "require_authoritative_score",
        "human_review_required",
        "separation_of_duties",
        "allow_author_review",
        "allow_author_approval",
    )
    if any(not isinstance(rules[key], bool) for key in boolean_keys):
        raise RepositoryPolicyError("Policy gate flags must be booleans")
    try:
        if isinstance(rules["minimum_score"], bool):
            raise InvalidOperation
        minimum_score = Decimal(str(rules["minimum_score"]))
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise RepositoryPolicyError("minimum_score must be numeric") from exc
    if minimum_score < 0 or minimum_score > 100:
        raise RepositoryPolicyError("minimum_score must be between 0 and 100")
    required_approvals = rules["required_approvals"]
    if (
        not isinstance(required_approvals, int)
        or isinstance(required_approvals, bool)
        or required_approvals < 1
    ):
        raise RepositoryPolicyError("required_approvals must be at least 1")
    valid_roles = {role.value for role in AuthorizationRole}
    for key in ("review_roles", "approval_roles"):
        roles = rules[key]
        if (
            not isinstance(roles, list)
            or not roles
            or any(role not in valid_roles for role in roles)
            or len(roles) != len(set(roles))
        ):
            raise RepositoryPolicyError(
                f"{key} must contain distinct authorization roles"
            )


def repository_policy_hash(rules: dict) -> str:
    validate_repository_policy(rules)
    return stable_hash(rules)


def policy_for_repository(db: Session, repository: Repository) -> RepositoryPolicy:
    if repository.eligibility_policy is not None:
        return repository.eligibility_policy
    digest = repository_policy_hash(DEFAULT_ELIGIBILITY_RULES)
    policy = (
        db.query(RepositoryPolicy)
        .filter(
            RepositoryPolicy.repository_id == repository.id,
            RepositoryPolicy.policy_hash == digest,
        )
        .first()
    )
    if policy is None:
        policy = RepositoryPolicy(
            repository_id=repository.id,
            version="default-v1",
            name="Default review and approval policy",
            description=(
                "Merged, authoritative scores require human review and admin approval."
            ),
            rules=DEFAULT_ELIGIBILITY_RULES,
            policy_hash=digest,
        )
        db.add(policy)
        db.flush()
    repository.eligibility_policy_id = policy.id
    repository.eligibility_policy = policy
    db.flush()
    return policy


def set_repository_policy(
    db: Session,
    *,
    repository: Repository,
    name: str,
    description: str | None,
    rules: dict,
    created_by_user_id: int,
) -> RepositoryPolicy:
    digest = repository_policy_hash(rules)
    policy = (
        db.query(RepositoryPolicy)
        .filter(
            RepositoryPolicy.repository_id == repository.id,
            RepositoryPolicy.policy_hash == digest,
        )
        .first()
    )
    if policy is None:
        policy = RepositoryPolicy(
            repository_id=repository.id,
            version=f"policy-{digest[:16]}",
            name=name,
            description=description,
            rules=rules,
            policy_hash=digest,
            created_by_user_id=created_by_user_id,
        )
        db.add(policy)
        db.flush()
    if repository.eligibility_policy_id != policy.id:
        repository.eligibility_policy_id = policy.id
        repository.eligibility_policy = policy
        for pull_request in repository.pull_requests:
            supersede_current_decision(db, pull_request)
        db.flush()
    return policy


def current_decision(
    db: Session, pull_request_id: int
) -> EligibilityDecision | None:
    return (
        db.query(EligibilityDecision)
        .filter(
            EligibilityDecision.pr_id == pull_request_id,
            EligibilityDecision.is_current.is_(True),
        )
        .first()
    )


def supersede_current_decision(
    db: Session, pull_request: PullRequest
) -> EligibilityDecision | None:
    decision = (
        db.query(EligibilityDecision)
        .filter(
            EligibilityDecision.pr_id == pull_request.id,
            EligibilityDecision.is_current.is_(True),
        )
        .with_for_update()
        .one_or_none()
    )
    if decision is None:
        if pull_request.eligibility_state not in {
            EligibilityState.CLAIMED,
            EligibilityState.PAID,
        }:
            pull_request.eligibility_state = EligibilityState.NOT_EVALUATED
        return None
    decision.is_current = False
    if decision.status in {
        EligibilityDecisionStatus.PENDING_REVIEW,
        EligibilityDecisionStatus.CHANGES_REQUESTED,
        EligibilityDecisionStatus.PENDING_APPROVAL,
    }:
        decision.status = EligibilityDecisionStatus.SUPERSEDED
        decision.finalized_at = datetime.utcnow()
    if pull_request.eligibility_state not in {
        EligibilityState.CLAIMED,
        EligibilityState.PAID,
    }:
        pull_request.eligibility_state = EligibilityState.NOT_EVALUATED
    db.flush()
    return decision


def _evaluate_rules(
    pull_request: PullRequest,
    score: Score,
    policy: RepositoryPolicy,
) -> tuple[dict, list[str]]:
    rules = policy.rules
    validate_repository_policy(rules)
    checks = {
        "merged": pull_request.state == PullRequestState.MERGED,
        "file_sync_complete": pull_request.file_sync_complete,
        "score_is_latest": pull_request.latest_score_id == score.id,
        "score_matches_head": score.head_sha == pull_request.head_sha,
        "score_input_complete": score.input_complete,
        "score_authoritative": score.is_authoritative,
        "minimum_score_met": (
            Decimal(score.final_score)
            >= Decimal(str(rules["minimum_score"]))
        ),
        "no_prior_payout": pull_request.eligibility_state
        not in {EligibilityState.CLAIMED, EligibilityState.PAID},
    }
    failures: list[str] = []
    if rules["require_merged"] and not checks["merged"]:
        failures.append("PULL_REQUEST_NOT_MERGED")
    if not checks["file_sync_complete"]:
        failures.append("FILE_SYNC_INCOMPLETE")
    if not checks["score_is_latest"] or not checks["score_matches_head"]:
        failures.append("STALE_SCORE")
    if not checks["score_input_complete"]:
        failures.append("SCORE_INPUT_INCOMPLETE")
    if rules["require_authoritative_score"] and not checks["score_authoritative"]:
        failures.append("SCORE_NOT_AUTHORITATIVE")
    if not checks["minimum_score_met"]:
        failures.append("MINIMUM_SCORE_NOT_MET")
    if not checks["no_prior_payout"]:
        failures.append("PRIOR_PAYOUT_EXISTS")
    return checks, failures


def evaluate_eligibility(
    db: Session,
    *,
    pull_request: PullRequest,
    actor_user_id: int | None,
) -> tuple[EligibilityDecision, bool]:
    score = pull_request.latest_score
    if score is None:
        raise EligibilityConflictError("No current deterministic score is available")
    policy = policy_for_repository(db, pull_request.repository)
    checks, failures = _evaluate_rules(pull_request, score, policy)
    evaluation_hash = stable_hash(
        {
            "pull_request_id": pull_request.id,
            "head_sha": pull_request.head_sha,
            "score_id": score.id,
            "score_hash": score.deterministic_hash,
            "score_version_id": score.score_version_id,
            "repository_policy_id": policy.id,
            "repository_policy_version": policy.version,
            "repository_policy_hash": policy.policy_hash,
            "checks": checks,
            "failures": failures,
        }
    )
    existing = current_decision(db, pull_request.id)
    if existing is not None and existing.evaluation_hash == evaluation_hash:
        return existing, False
    if existing is not None:
        supersede_current_decision(db, pull_request)

    if failures:
        status = EligibilityDecisionStatus.INELIGIBLE
    elif policy.rules["human_review_required"]:
        status = EligibilityDecisionStatus.PENDING_REVIEW
    else:
        status = EligibilityDecisionStatus.PENDING_APPROVAL
    decision = EligibilityDecision(
        pr_id=pull_request.id,
        score_id=score.id,
        score_version_id=score.score_version_id,
        repository_policy_id=policy.id,
        status=status,
        is_current=True,
        evaluation_result={
            "checks": checks,
            "score": {
                "id": score.id,
                "version_id": score.score_version_id,
                "head_sha": score.head_sha,
                "final_score": float(score.final_score),
                "confidence": float(score.confidence),
                "deterministic_hash": score.deterministic_hash,
            },
            "policy": {
                "id": policy.id,
                "version": policy.version,
                "policy_hash": policy.policy_hash,
                "rules": policy.rules,
            },
        },
        failure_reasons=failures,
        requires_human_review=bool(policy.rules["human_review_required"]),
        required_approvals=int(policy.rules["required_approvals"]),
        evaluation_hash=evaluation_hash,
        evaluated_by_user_id=actor_user_id,
        finalized_at=datetime.utcnow() if failures else None,
    )
    db.add(decision)
    if failures:
        pull_request.eligibility_state = EligibilityState.INELIGIBLE
    else:
        pull_request.eligibility_state = EligibilityState.NOT_EVALUATED
    db.flush()
    return decision, True


def _require_current_inputs(decision: EligibilityDecision) -> None:
    pull_request = decision.pull_request
    if not decision.is_current:
        raise EligibilityConflictError("Eligibility decision has been superseded")
    if (
        pull_request.latest_score_id != decision.score_id
        or pull_request.repository.eligibility_policy_id
        != decision.repository_policy_id
    ):
        raise EligibilityConflictError(
            "Score or repository policy changed; evaluate eligibility again"
        )


def submit_review(
    db: Session,
    *,
    decision: EligibilityDecision,
    reviewer: User,
    reviewer_role: AuthorizationRole,
    recommendation: ReviewRecommendation,
    summary: str,
    findings: list[dict],
) -> Review:
    _require_current_inputs(decision)
    if decision.status not in {
        EligibilityDecisionStatus.PENDING_REVIEW,
        EligibilityDecisionStatus.CHANGES_REQUESTED,
    }:
        raise EligibilityConflictError("Decision is not awaiting human review")
    rules = decision.repository_policy.rules
    if reviewer_role.value not in rules["review_roles"]:
        raise EligibilityConflictError("Role is not allowed to review this decision")
    if not rules["allow_author_review"] and reviewer.id == decision.pull_request.author_id:
        raise EligibilityConflictError("Pull request authors cannot review themselves")

    now = datetime.utcnow()
    review = Review(
        eligibility_decision_id=decision.id,
        reviewer_user_id=reviewer.id,
        status=HumanReviewStatus.IN_PROGRESS,
        recommendation=recommendation,
        summary=summary,
        started_at=now,
    )
    db.add(review)
    db.flush()
    for item in findings:
        db.add(
            ReviewFinding(
                review_id=review.id,
                severity=FindingSeverity(item["severity"]),
                category=item["category"],
                code=item["code"],
                message=item["message"],
                evidence=item.get("evidence") or {},
            )
        )
    review.status = HumanReviewStatus.COMPLETED
    review.completed_at = now
    if recommendation == ReviewRecommendation.APPROVE:
        decision.status = EligibilityDecisionStatus.PENDING_APPROVAL
    elif recommendation == ReviewRecommendation.REQUEST_CHANGES:
        decision.status = EligibilityDecisionStatus.CHANGES_REQUESTED
    else:
        decision.status = EligibilityDecisionStatus.INELIGIBLE
        decision.failure_reasons = [
            *decision.failure_reasons,
            "HUMAN_REVIEW_REJECTED",
        ]
        decision.finalized_at = now
        decision.pull_request.eligibility_state = EligibilityState.INELIGIBLE
    db.flush()
    return review


def submit_approval(
    db: Session,
    *,
    decision: EligibilityDecision,
    approver: User,
    approver_role: AuthorizationRole,
    outcome: ApprovalOutcome,
    reason: str | None,
) -> Approval:
    decision = (
        db.query(EligibilityDecision)
        .filter(EligibilityDecision.id == decision.id)
        .with_for_update()
        .populate_existing()
        .one()
    )
    _require_current_inputs(decision)
    if decision.status != EligibilityDecisionStatus.PENDING_APPROVAL:
        raise EligibilityConflictError("Decision is not awaiting approval")
    rules = decision.repository_policy.rules
    if approver_role.value not in rules["approval_roles"]:
        raise EligibilityConflictError("Role is not allowed to approve this decision")
    if not rules["allow_author_approval"] and approver.id == decision.pull_request.author_id:
        raise EligibilityConflictError("Pull request authors cannot approve themselves")
    if rules["separation_of_duties"] and any(
        review.reviewer_user_id == approver.id
        and review.recommendation == ReviewRecommendation.APPROVE
        for review in decision.reviews
    ):
        raise EligibilityConflictError(
            "Reviewer and approver must be different users"
        )
    if any(item.approver_user_id == approver.id for item in decision.approvals):
        raise EligibilityConflictError("Approver has already decided this request")
    if outcome == ApprovalOutcome.REJECTED and not reason:
        raise EligibilityConflictError("A rejection reason is required")

    approval = Approval(
        eligibility_decision=decision,
        approver_user_id=approver.id,
        outcome=outcome,
        reason=reason,
        score_id=decision.score_id,
        score_version_id=decision.score_version_id,
        repository_policy_id=decision.repository_policy_id,
    )
    db.add(approval)
    db.flush()
    now = datetime.utcnow()
    if outcome == ApprovalOutcome.REJECTED:
        decision.status = EligibilityDecisionStatus.INELIGIBLE
        decision.failure_reasons = [
            *decision.failure_reasons,
            "APPROVAL_REJECTED",
        ]
        decision.finalized_at = now
        decision.pull_request.eligibility_state = EligibilityState.INELIGIBLE
    else:
        approved_count = (
            db.query(Approval)
            .filter(
                Approval.eligibility_decision_id == decision.id,
                Approval.outcome == ApprovalOutcome.APPROVED,
            )
            .count()
        )
        if approved_count >= decision.required_approvals:
            decision.status = EligibilityDecisionStatus.ELIGIBLE
            decision.finalized_at = now
            decision.final_approved_by_user_id = approver.id
            decision.pull_request.eligibility_state = EligibilityState.ELIGIBLE
    db.flush()
    return approval
