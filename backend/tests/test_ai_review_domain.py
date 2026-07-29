from __future__ import annotations

from decimal import Decimal

import pytest
from pydantic import ValidationError

from app.models.ai_review import AIProviderKind, AIReviewStatus
from app.models.pull_request import EligibilityState
from app.models.score import ImmutableRecordError
from app.schemas.ai_review import (
    AIReviewOutput,
    ModerationResult,
    ModerationStatus,
    TokenUsage,
)
from app.services.ai_review_service import (
    AIProviderResponse,
    AIReviewConflictError,
    complete_ai_review,
    execute_ai_review,
    request_ai_review,
)
from app.services.bounty_service import (
    assign_bounty,
    create_bounty,
    create_issue,
    link_assignment_to_pull_request,
    mark_bounty_funded,
)
from test_deterministic_scoring import _delivery, _execute, _fixture_graph


def _analyzed_graph(db, *, private=False, with_bounty=True):
    repository, pull_request = _fixture_graph(db)
    repository.is_private = private
    pull_request.description = "Implement the issue requirements without regressions."
    _, score, _ = _execute(db, pull_request, _delivery(db, 800))
    assignment = None
    if with_bounty:
        issue = create_issue(
            db,
            repository=repository,
            github_issue_id=8100,
            number=81,
            title="Protect advisory review",
            description="AI findings must never authorize payment.",
            url="https://github.com/deterministic/engine/issues/81",
        )
        bounty = create_bounty(
            db,
            repository=repository,
            issue=issue,
            amount=Decimal("75"),
            currency="USDC",
            expires_at=None,
            created_by_user_id=pull_request.author_id,
        )
        mark_bounty_funded(db, bounty)
        assignment = assign_bounty(
            db,
            bounty=bounty,
            assignee_user_id=pull_request.author_id,
            assigned_by_user_id=pull_request.author_id,
        )
        link_assignment_to_pull_request(
            db, assignment=assignment, pull_request=pull_request
        )
    return repository, pull_request, score, assignment


def _output(confidence=Decimal("0.84")):
    return AIReviewOutput(
        summary="The change is coherent but remains subject to human review.",
        positive_findings=["Tests cover the modified service path."],
        risk_findings=["Provider timeout behavior needs explicit verification."],
        requirement_coverage=["Advisory isolation is represented."],
        recommended_actions=["Add a provider-timeout integration test."],
        confidence=confidence,
    )


def _moderation(status=ModerationStatus.PASSED):
    return ModerationResult(status=status, categories={"source_code": False})


def test_ai_input_is_structured_versioned_and_requirement_aware(session_factory):
    db = session_factory()
    try:
        repository, pull_request, score, _ = _analyzed_graph(db)
        review, created = request_ai_review(
            db,
            pull_request=pull_request,
            provider="example-ai",
            model="review-model-1",
            provider_kind=AIProviderKind.EXTERNAL,
            requested_by_user_id=pull_request.author_id,
        )
        repeated, repeated_created = request_ai_review(
            db,
            pull_request=pull_request,
            provider="example-ai",
            model="review-model-1",
            provider_kind=AIProviderKind.EXTERNAL,
            requested_by_user_id=pull_request.author_id,
        )

        assert created is True
        assert repeated_created is False
        assert repeated.id == review.id
        assert review.status == AIReviewStatus.PENDING
        assert review.advisory_only is True
        assert review.analysis_run_id == score.analysis_run_id
        assert review.input_commit_sha == pull_request.head_sha
        assert review.prompt_version == "ai-review-v1"
        assert review.repository_policy.version == "default-v1"
        assert review.ai_review_policy.version == "default-v1"

        payload = review.input_snapshot
        assert payload["contract"]["advisory_only"] is True
        assert payload["pull_request"]["title"] == pull_request.title
        assert payload["pull_request"]["description"] == pull_request.description
        assert payload["issue_and_bounty_requirements"][0]["issue"]["description"]
        assert payload["diff_summary"]["total_files"] == 3
        assert payload["selected_patch_chunks"]
        assert payload["static_analyzer_findings"]
        assert payload["ci_results"][0]["analyzer"] == "ci_check_status"
        assert payload["repository_review_policy"]["rules"]
        assert review.privacy_decision["patches_included"] is True
        assert repository.is_private is False
    finally:
        db.close()


def test_private_repository_blocks_external_provider_before_data_exposure(
    session_factory,
):
    db = session_factory()
    try:
        _, pull_request, _, _ = _analyzed_graph(db, private=True)

        class Provider:
            name = "external-ai"
            model = "external-model"
            kind = AIProviderKind.EXTERNAL
            calls = 0

            def review(self, *, input_snapshot, prompt_version, idempotency_key):
                self.calls += 1
                raise AssertionError("Blocked provider must never be called")

        provider = Provider()
        review = execute_ai_review(
            db,
            pull_request=pull_request,
            provider=provider,
            requested_by_user_id=pull_request.author_id,
        )

        assert review.status == AIReviewStatus.BLOCKED
        assert review.input_snapshot == {}
        assert provider.calls == 0
        assert (
            review.privacy_decision["blocked_reason"]
            == "PRIVATE_REPOSITORY_EXTERNAL_TRANSFER_DISABLED"
        )
    finally:
        db.close()


def test_private_repository_can_use_a_local_provider_without_external_transfer(
    session_factory,
):
    db = session_factory()
    try:
        _, pull_request, _, _ = _analyzed_graph(db, private=True)
        review, _ = request_ai_review(
            db,
            pull_request=pull_request,
            provider="local-runtime",
            model="local-reviewer",
            provider_kind=AIProviderKind.LOCAL,
            requested_by_user_id=pull_request.author_id,
        )

        assert review.status == AIReviewStatus.PENDING
        assert review.input_snapshot["selected_patch_chunks"]
        assert review.privacy_decision["blocked_reason"] is None
    finally:
        db.close()


def test_ai_output_schema_is_strict():
    with pytest.raises(ValidationError):
        AIReviewOutput(
            summary="Invalid confidence",
            positive_findings=[],
            risk_findings=[],
            requirement_coverage=[],
            recommended_actions=[],
            confidence=Decimal("1.1"),
            payment_decision="pay",
        )


def test_ai_completion_stores_provenance_without_changing_eligibility(
    session_factory,
):
    db = session_factory()
    try:
        _, pull_request, _, _ = _analyzed_graph(db)
        initial_eligibility = pull_request.eligibility_state
        review, _ = request_ai_review(
            db,
            pull_request=pull_request,
            provider="example-ai",
            model="review-model-1",
            provider_kind=AIProviderKind.EXTERNAL,
            requested_by_user_id=pull_request.author_id,
        )
        complete_ai_review(
            db,
            review=review,
            output=_output(),
            provider_request_id="provider-request-1",
            token_usage=TokenUsage(
                prompt_tokens=1000,
                completion_tokens=200,
                total_tokens=1200,
            ),
            cost_amount=Decimal("0.01234567"),
            cost_currency="usd",
            moderation_result=_moderation(),
        )

        assert review.status == AIReviewStatus.COMPLETE
        assert review.output["confidence"] == 0.84
        assert review.provider_request_id == "provider-request-1"
        assert review.total_tokens == 1200
        assert review.cost_amount == Decimal("0.01234567")
        assert review.cost_currency == "USD"
        assert review.moderation_result["status"] == "passed"
        assert pull_request.eligibility_state == initial_eligibility
        assert pull_request.eligibility_state == EligibilityState.NOT_EVALUATED

        review.output = {**review.output, "summary": "mutated"}
        with pytest.raises(ImmutableRecordError):
            db.flush()
        db.rollback()
    finally:
        db.close()


def test_flagged_output_is_recorded_as_failed_advice(session_factory):
    db = session_factory()
    try:
        _, pull_request, _, _ = _analyzed_graph(db)
        review, _ = request_ai_review(
            db,
            pull_request=pull_request,
            provider="example-ai",
            model="review-model-1",
            provider_kind=AIProviderKind.EXTERNAL,
            requested_by_user_id=pull_request.author_id,
        )
        complete_ai_review(
            db,
            review=review,
            output=_output(),
            provider_request_id=None,
            token_usage=TokenUsage(
                prompt_tokens=10, completion_tokens=5, total_tokens=15
            ),
            cost_amount=Decimal("0"),
            cost_currency="USD",
            moderation_result=_moderation(ModerationStatus.FLAGGED),
        )

        assert review.status == AIReviewStatus.FAILED
        assert review.failure_reason == "MODERATION_FLAGGED"
        assert pull_request.eligibility_state == EligibilityState.NOT_EVALUATED
    finally:
        db.close()


def test_ai_review_cannot_run_before_deterministic_analysis(session_factory):
    db = session_factory()
    try:
        _, pull_request = _fixture_graph(db)
        with pytest.raises(AIReviewConflictError, match="deterministic analysis"):
            request_ai_review(
                db,
                pull_request=pull_request,
                provider="example-ai",
                model="review-model-1",
                provider_kind=AIProviderKind.EXTERNAL,
                requested_by_user_id=pull_request.author_id,
            )
    finally:
        db.close()
