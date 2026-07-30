from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Protocol

from sqlalchemy.orm import Session

from app.analysis.base import stable_hash
from app.core.config import settings
from app.models.ai_review import (
    AIProviderKind,
    AIReview,
    AIReviewPolicy,
    AIReviewStatus,
)
from app.models.analysis_run import AnalysisRunStatus
from app.models.bounty_domain import Bounty, BountyAssignment, Claim
from app.models.pull_request import PullRequest
from app.models.pull_request_file import PullRequestFile
from app.models.repository import Repository
from app.schemas.ai_review import (
    AIReviewOutput,
    ModerationResult,
    ModerationStatus,
    TokenUsage,
)
from app.services.ai_review_provider_common import AIProviderSafetyBlocked
from app.services.eligibility_service import policy_for_repository
from app.services.notification_service import emit_domain_event


DEFAULT_AI_REVIEW_RULES = {
    "enabled": True,
    "allow_external_providers": True,
    "allow_private_repository_external": False,
    "include_patch_chunks": True,
    "max_patch_files": 12,
    "max_patch_characters": 12000,
    "max_summary_files": 250,
}
REQUIRED_RULE_KEYS = frozenset(DEFAULT_AI_REVIEW_RULES)


class AIReviewConflictError(RuntimeError):
    pass


class AIReviewPolicyError(ValueError):
    pass


@dataclass(frozen=True)
class AIProviderResponse:
    output: AIReviewOutput
    provider_request_id: str | None
    token_usage: TokenUsage
    cost_amount: Decimal | None
    cost_currency: str | None
    moderation_result: ModerationResult


class AIReviewProvider(Protocol):
    name: str
    model: str
    kind: AIProviderKind

    def review(
        self, *, input_snapshot: dict, prompt_version: str, idempotency_key: str
    ) -> AIProviderResponse:
        ...


def validate_ai_review_policy(rules: dict) -> None:
    if set(rules) != REQUIRED_RULE_KEYS:
        raise AIReviewPolicyError(
            "AI review policy must define exactly: "
            + ", ".join(sorted(REQUIRED_RULE_KEYS))
        )
    for key in (
        "enabled",
        "allow_external_providers",
        "allow_private_repository_external",
        "include_patch_chunks",
    ):
        if not isinstance(rules[key], bool):
            raise AIReviewPolicyError(f"{key} must be a boolean")
    limits = {
        "max_patch_files": (0, 50),
        "max_patch_characters": (0, 100000),
        "max_summary_files": (1, 1000),
    }
    for key, (minimum, maximum) in limits.items():
        value = rules[key]
        if (
            not isinstance(value, int)
            or isinstance(value, bool)
            or value < minimum
            or value > maximum
        ):
            raise AIReviewPolicyError(
                f"{key} must be an integer between {minimum} and {maximum}"
            )


def ai_review_policy_for_repository(
    db: Session, repository: Repository
) -> AIReviewPolicy:
    if repository.ai_review_policy is not None:
        return repository.ai_review_policy
    validate_ai_review_policy(DEFAULT_AI_REVIEW_RULES)
    digest = stable_hash(DEFAULT_AI_REVIEW_RULES)
    policy = (
        db.query(AIReviewPolicy)
        .filter(
            AIReviewPolicy.repository_id == repository.id,
            AIReviewPolicy.policy_hash == digest,
        )
        .first()
    )
    if policy is None:
        policy = AIReviewPolicy(
            repository_id=repository.id,
            version="default-v1",
            name="Default advisory AI and source privacy policy",
            rules=DEFAULT_AI_REVIEW_RULES,
            policy_hash=digest,
        )
        db.add(policy)
        db.flush()
    repository.ai_review_policy_id = policy.id
    repository.ai_review_policy = policy
    db.flush()
    return policy


def set_ai_review_policy(
    db: Session,
    *,
    repository: Repository,
    name: str,
    rules: dict,
    created_by_user_id: int,
) -> AIReviewPolicy:
    validate_ai_review_policy(rules)
    digest = stable_hash(rules)
    policy = (
        db.query(AIReviewPolicy)
        .filter(
            AIReviewPolicy.repository_id == repository.id,
            AIReviewPolicy.policy_hash == digest,
        )
        .first()
    )
    if policy is None:
        policy = AIReviewPolicy(
            repository_id=repository.id,
            version=f"policy-{digest[:16]}",
            name=name,
            rules=rules,
            policy_hash=digest,
            created_by_user_id=created_by_user_id,
        )
        db.add(policy)
        db.flush()
    repository.ai_review_policy_id = policy.id
    repository.ai_review_policy = policy
    db.flush()
    return policy


def _analysis_for_ai(pull_request: PullRequest):
    score = pull_request.latest_score
    if (
        score is None
        or score.analysis_run is None
        or pull_request.latest_score_id != score.id
        or not pull_request.head_sha
        or score.head_sha != pull_request.head_sha
        or score.analysis_run.head_sha != pull_request.head_sha
        or score.analysis_run.status != AnalysisRunStatus.COMPLETE
        or not score.analysis_run.input_complete
        or not pull_request.file_sync_complete
    ):
        raise AIReviewConflictError(
            "AI review requires a current, complete deterministic analysis"
        )
    return score, score.analysis_run


def _privacy_decision(
    repository: Repository,
    policy: AIReviewPolicy,
    provider_kind: AIProviderKind,
) -> dict:
    rules = policy.rules
    blocked_reason = None
    if not rules["enabled"]:
        blocked_reason = "AI_REVIEW_DISABLED"
    elif (
        provider_kind == AIProviderKind.EXTERNAL
        and not rules["allow_external_providers"]
    ):
        blocked_reason = "EXTERNAL_PROVIDER_DISABLED"
    elif (
        provider_kind == AIProviderKind.EXTERNAL
        and repository.is_private
        and not rules["allow_private_repository_external"]
    ):
        blocked_reason = "PRIVATE_REPOSITORY_EXTERNAL_TRANSFER_DISABLED"
    allowed = blocked_reason is None
    return {
        "repository_private": repository.is_private,
        "provider_kind": provider_kind.value,
        "request_allowed": allowed,
        "external_transfer_allowed": bool(
            allowed and provider_kind == AIProviderKind.EXTERNAL
        ),
        "patches_included": bool(allowed and rules["include_patch_chunks"]),
        "blocked_reason": blocked_reason,
        "ai_review_policy_version": policy.version,
        "ai_review_policy_hash": policy.policy_hash,
    }


def _linked_requirements(db: Session, pull_request: PullRequest) -> list[dict]:
    bounties = (
        db.query(Bounty)
        .join(BountyAssignment, BountyAssignment.bounty_id == Bounty.id)
        .filter(BountyAssignment.pull_request_id == pull_request.id)
        .all()
    )
    claimed_bounties = (
        db.query(Bounty)
        .join(Claim, Claim.bounty_id == Bounty.id)
        .filter(Claim.pull_request_id == pull_request.id)
        .all()
    )
    by_id = {bounty.id: bounty for bounty in [*bounties, *claimed_bounties]}
    return [
        {
            "bounty_id": bounty.id,
            "amount": str(bounty.amount),
            "currency": bounty.currency,
            "status": bounty.status.value,
            "issue": {
                "id": bounty.issue.id,
                "number": bounty.issue.number,
                "title": bounty.issue.title,
                "description": bounty.issue.description,
                "url": bounty.issue.url,
            },
            "eligibility_policy_id": bounty.eligibility_policy_id,
            "bounty_policy": {
                "version": bounty.bounty_policy.version,
                "rules": bounty.bounty_policy.rules,
            },
        }
        for bounty in sorted(by_id.values(), key=lambda item: item.id)
    ]


def _diff_input(
    db: Session, pull_request: PullRequest, rules: dict
) -> tuple[dict, list[dict]]:
    files = (
        db.query(PullRequestFile)
        .filter(
            PullRequestFile.pr_id == pull_request.id,
            PullRequestFile.is_current.is_(True),
        )
        .order_by(PullRequestFile.filename)
        .all()
    )
    max_summary_files = rules["max_summary_files"]
    summary_files = files[:max_summary_files]
    diff_summary = {
        "total_files": len(files),
        "total_additions": sum(item.additions for item in files),
        "total_deletions": sum(item.deletions for item in files),
        "files_omitted": max(0, len(files) - len(summary_files)),
        "files": [
            {
                "filename": item.filename,
                "previous_filename": item.previous_filename,
                "status": item.github_status,
                "additions": item.additions,
                "deletions": item.deletions,
                "changes": item.changes,
                "patch_status": item.patch_status,
            }
            for item in summary_files
        ],
    }
    remaining = rules["max_patch_characters"]
    patch_chunks: list[dict] = []
    candidates = sorted(files, key=lambda item: (-item.changes, item.filename))
    for item in candidates:
        if (
            len(patch_chunks) >= rules["max_patch_files"]
            or remaining <= 0
            or not item.patch_available
            or not item.patch
        ):
            continue
        chunk = item.patch[:remaining]
        patch_chunks.append(
            {
                "filename": item.filename,
                "patch": chunk,
                "truncated": len(chunk) < len(item.patch),
            }
        )
        remaining -= len(chunk)
    return diff_summary, patch_chunks


def _analysis_evidence(analysis_run) -> tuple[list[dict], list[dict]]:
    static_findings: list[dict] = []
    ci_results: list[dict] = []
    for result in sorted(
        analysis_run.analyzer_results, key=lambda item: item.analyzer_name
    ):
        item = {
            "analyzer": result.analyzer_name,
            "version": result.analyzer_version,
            "category": result.category,
            "status": result.status.value,
            "score": str(result.score) if result.score is not None else None,
            "confidence": str(result.confidence),
            "findings": result.findings,
            "evidence": result.evidence,
            "errors": result.errors,
        }
        if result.analyzer_name == "ci_check_status":
            ci_results.append(item)
        else:
            static_findings.append(item)
    return static_findings, ci_results


def _build_input_snapshot(
    db: Session,
    *,
    pull_request: PullRequest,
    analysis_run,
    repository_policy,
    ai_policy: AIReviewPolicy,
    include_patches: bool,
) -> dict:
    diff_summary, patch_chunks = _diff_input(db, pull_request, ai_policy.rules)
    if not include_patches:
        patch_chunks = []
    static_findings, ci_results = _analysis_evidence(analysis_run)
    return {
        "contract": {
            "advisory_only": True,
            "output_schema": {
                "summary": "string",
                "positive_findings": ["string"],
                "risk_findings": ["string"],
                "requirement_coverage": ["string"],
                "recommended_actions": ["string"],
                "confidence": "number between 0 and 1",
            },
        },
        "pull_request": {
            "id": pull_request.id,
            "title": pull_request.title,
            "description": pull_request.description,
            "state": pull_request.state.value,
            "head_sha": pull_request.head_sha,
        },
        "issue_and_bounty_requirements": _linked_requirements(db, pull_request),
        "diff_summary": diff_summary,
        "selected_patch_chunks": patch_chunks,
        "static_analyzer_findings": static_findings,
        "ci_results": ci_results,
        "deterministic_analysis": {
            "analysis_run_id": analysis_run.id,
            "analyzer_version": analysis_run.analyzer_version,
            "input_complete": analysis_run.input_complete,
            "is_authoritative": analysis_run.is_authoritative,
        },
        "repository_review_policy": {
            "id": repository_policy.id,
            "version": repository_policy.version,
            "policy_hash": repository_policy.policy_hash,
            "rules": repository_policy.rules,
        },
    }


def request_ai_review(
    db: Session,
    *,
    pull_request: PullRequest,
    provider: str,
    model: str,
    provider_kind: AIProviderKind,
    requested_by_user_id: int | None,
    prompt_version: str | None = None,
    force_retry: bool = False,
) -> tuple[AIReview, bool]:
    _, analysis_run = _analysis_for_ai(pull_request)
    repository_policy = policy_for_repository(db, pull_request.repository)
    ai_policy = ai_review_policy_for_repository(db, pull_request.repository)
    privacy = _privacy_decision(
        pull_request.repository, ai_policy, provider_kind
    )
    blocked = privacy["blocked_reason"] is not None
    input_snapshot = (
        {}
        if blocked
        else _build_input_snapshot(
            db,
            pull_request=pull_request,
            analysis_run=analysis_run,
            repository_policy=repository_policy,
            ai_policy=ai_policy,
            include_patches=privacy["patches_included"],
        )
    )
    input_hash = stable_hash(input_snapshot)
    selected_prompt_version = prompt_version or settings.AI_REVIEW_PROMPT_VERSION
    existing_count = (
        db.query(AIReview)
        .filter(AIReview.pr_id == pull_request.id, AIReview.input_hash == input_hash)
        .count()
    )
    attempt_nonce = f":attempt-{existing_count}" if (force_retry or existing_count > 0) else ""
    review_key = stable_hash(
        {
            "pr_id": pull_request.id,
            "analysis_run_id": analysis_run.id,
            "repository_policy_id": repository_policy.id,
            "ai_review_policy_id": ai_policy.id,
            "provider": provider,
            "model": model,
            "provider_kind": provider_kind.value,
            "prompt_version": selected_prompt_version,
            "input_commit_sha": pull_request.head_sha,
            "input_hash": input_hash,
            "attempt_nonce": attempt_nonce,
        }
    )
    existing = db.query(AIReview).filter(AIReview.review_key == review_key).first()
    if existing is not None and not force_retry:
        return existing, False
    review = AIReview(
        pr_id=pull_request.id,
        analysis_run_id=analysis_run.id,
        repository_policy_id=repository_policy.id,
        ai_review_policy_id=ai_policy.id,
        requested_by_user_id=requested_by_user_id,
        provider=provider,
        model=model,
        provider_kind=provider_kind,
        prompt_version=selected_prompt_version,
        input_commit_sha=pull_request.head_sha,
        input_snapshot=input_snapshot,
        input_hash=input_hash,
        privacy_decision=privacy,
        status=AIReviewStatus.BLOCKED if blocked else AIReviewStatus.PENDING,
        moderation_result=(
            {
                "status": ModerationStatus.NOT_RUN.value,
                "categories": {},
                "details": privacy["blocked_reason"],
            }
            if blocked
            else None
        ),
        failure_reason=privacy["blocked_reason"] if blocked else None,
        advisory_only=True,
        review_key=review_key,
        completed_at=datetime.utcnow() if blocked else None,
    )
    db.add(review)
    db.flush()
    return review, True


def complete_ai_review(
    db: Session,
    *,
    review: AIReview,
    output: AIReviewOutput,
    provider_request_id: str | None,
    token_usage: TokenUsage,
    cost_amount: Decimal | None,
    cost_currency: str | None,
    moderation_result: ModerationResult,
) -> AIReview:
    if review.status != AIReviewStatus.PENDING:
        raise AIReviewConflictError("AI review is not pending completion")
    normalized_output = {
        **output.model_dump(exclude={"confidence"}),
        "confidence": float(output.confidence),
    }
    review.output = normalized_output
    review.provider_request_id = provider_request_id
    review.prompt_tokens = token_usage.prompt_tokens
    review.completion_tokens = token_usage.completion_tokens
    review.total_tokens = token_usage.total_tokens
    review.cost_amount = cost_amount
    review.cost_currency = cost_currency.upper() if cost_currency else None
    review.moderation_result = moderation_result.model_dump(mode="json")
    if moderation_result.status != ModerationStatus.PASSED:
        review.status = AIReviewStatus.FAILED
        review.failure_reason = f"MODERATION_{moderation_result.status.value.upper()}"
    else:
        review.status = AIReviewStatus.COMPLETE
    review.completed_at = datetime.utcnow()
    db.flush()
    return review


def fail_ai_review(
    db: Session,
    *,
    review: AIReview,
    failure_reason: str,
    provider_request_id: str | None,
    moderation_result: ModerationResult,
) -> AIReview:
    if review.status != AIReviewStatus.PENDING:
        raise AIReviewConflictError("AI review is not pending")
    review.status = AIReviewStatus.FAILED
    review.failure_reason = failure_reason
    review.provider_request_id = provider_request_id
    review.moderation_result = moderation_result.model_dump(mode="json")
    review.completed_at = datetime.utcnow()
    db.flush()
    return review


def execute_ai_review(
    db: Session,
    *,
    pull_request: PullRequest,
    provider: AIReviewProvider,
    requested_by_user_id: int | None,
) -> AIReview:
    review, _ = request_ai_review(
        db,
        pull_request=pull_request,
        provider=provider.name,
        model=provider.model,
        provider_kind=provider.kind,
        requested_by_user_id=requested_by_user_id,
    )
    if review.status != AIReviewStatus.PENDING:
        return review
    try:
        response = provider.review(
            input_snapshot=review.input_snapshot,
            prompt_version=review.prompt_version,
            idempotency_key=review.review_key,
        )
        return complete_ai_review(
            db,
            review=review,
            output=response.output,
            provider_request_id=response.provider_request_id,
            token_usage=response.token_usage,
            cost_amount=response.cost_amount,
            cost_currency=response.cost_currency,
            moderation_result=response.moderation_result,
        )
    except AIProviderSafetyBlocked as exc:
        return fail_ai_review(
            db,
            review=review,
            failure_reason="PROVIDER_SAFETY_BLOCKED",
            provider_request_id=None,
            moderation_result=exc.moderation_result,
        )
    except Exception as exc:
        return fail_ai_review(
            db,
            review=review,
            failure_reason=f"{type(exc).__name__}: {str(exc)[:1000]}",
            provider_request_id=None,
            moderation_result=ModerationResult(
                status=ModerationStatus.ERROR,
                details="Provider execution failed before a safety result was available",
            ),
        )


def _emit_ai_review_terminal_event(db: Session, review: AIReview) -> None:
    repository = review.pull_request.repository
    emit_domain_event(
        db,
        event_type=(
            "ai_review.completed"
            if review.status == AIReviewStatus.COMPLETE
            else "ai_review.failed"
        ),
        organization_id=repository.organization_id,
        repository_id=repository.id,
        aggregate_type="ai_review",
        aggregate_id=review.id,
        event_identity=f"{review.id}:{review.status.value}",
        recipient_user_ids=[review.pull_request.author_id],
        payload={
            "pull_request_id": review.pr_id,
            "pull_request_title": review.pull_request.title,
            "repository": repository.full_name,
            "ai_review_id": review.id,
            "status": review.status.value,
            "advisory_only": True,
        },
    )


def execute_ai_review_by_id(review_id: int) -> str:
    """Execute a persisted advisory review from the dedicated worker queue."""
    from app.db.session import SessionLocal
    from app.services.ai_review_provider_factory import (
        configured_ai_review_provider,
    )
    from app.services.ai_review_quota import (
        AIReviewDailyLimitExceeded,
        reserve_daily_ai_review_request,
    )

    db = SessionLocal()
    try:
        review = (
            db.query(AIReview)
            .filter(AIReview.id == review_id)
            .with_for_update()
            .one_or_none()
        )
        if review is None:
            return "missing"
        if review.status != AIReviewStatus.PENDING:
            return review.status.value
        try:
            provider = configured_ai_review_provider()
            if review.provider != provider.name:
                raise AIReviewConflictError(
                    f"Persisted review provider ({review.provider}) does not match configured provider ({provider.name})"
                )
            reserve_daily_ai_review_request(
                provider=provider.name,
            )
            response = provider.review(
                input_snapshot=review.input_snapshot,
                prompt_version=review.prompt_version,
                idempotency_key=review.review_key,
                model_override=review.model,
            )
            complete_ai_review(
                db,
                review=review,
                output=response.output,
                provider_request_id=response.provider_request_id,
                token_usage=response.token_usage,
                cost_amount=response.cost_amount,
                cost_currency=response.cost_currency,
                moderation_result=response.moderation_result,
            )
            _emit_ai_review_terminal_event(db, review)
            db.commit()
            return review.status.value
        except AIProviderSafetyBlocked as exc:
            fail_ai_review(
                db,
                review=review,
                failure_reason="PROVIDER_SAFETY_BLOCKED",
                provider_request_id=None,
                moderation_result=exc.moderation_result,
            )
            _emit_ai_review_terminal_event(db, review)
            db.commit()
            return review.status.value
        except AIReviewDailyLimitExceeded as exc:
            fail_ai_review(
                db,
                review=review,
                failure_reason="DAILY_AI_REVIEW_LIMIT_EXCEEDED",
                provider_request_id=None,
                moderation_result=ModerationResult(
                    status=ModerationStatus.NOT_RUN,
                    details=str(exc),
                ),
            )
            _emit_ai_review_terminal_event(db, review)
            db.commit()
            return review.status.value
        except Exception as exc:
            fail_ai_review(
                db,
                review=review,
                failure_reason=f"{type(exc).__name__}: {str(exc)[:4000]}",
                provider_request_id=None,
                moderation_result=ModerationResult(
                    status=ModerationStatus.ERROR,
                    details="Provider execution failed before a safety result was available",
                ),
            )
            _emit_ai_review_terminal_event(db, review)
            db.commit()
            return review.status.value
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def dispatch_pending_ai_reviews(send_task) -> int:
    """Recovery dispatcher for records committed before a broker outage."""
    from app.db.session import SessionLocal

    db = SessionLocal()
    try:
        review_ids = [
            row[0]
            for row in (
                db.query(AIReview.id)
                .filter(AIReview.status == AIReviewStatus.PENDING)
                .order_by(AIReview.created_at, AIReview.id)
                .limit(100)
                .all()
            )
        ]
    finally:
        db.close()
    for review_id in review_ids:
        send_task(
            "app.worker.tasks.execute_ai_review",
            args=[review_id],
            queue="ai_review",
        )
    return len(review_ids)
