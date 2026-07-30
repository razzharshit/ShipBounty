from __future__ import annotations

from decimal import Decimal

import pytest

from app.models.authorization import (
    AuthorizationRole,
    Organization,
    OrganizationMembership,
)
from app.models.pull_request import EligibilityState, PullRequest, PullRequestState
from app.models.repository import Repository
from app.models.review_domain import (
    ApprovalOutcome,
    EligibilityDecisionStatus,
    RepositoryPolicy,
    ReviewRecommendation,
)
from app.models.score import ImmutableRecordError, Score, ScoreVersion
from app.models.user import User
from app.schemas.pull_request import PullRequestCreate
from app.services.eligibility_service import (
    DEFAULT_ELIGIBILITY_RULES,
    EligibilityConflictError,
    evaluate_eligibility,
    set_repository_policy,
    submit_approval,
    submit_review,
    supersede_current_decision,
)


def _domain_fixture(
    db, *, final_score=90, authoritative=True, id_base=9100
):
    suffix = "" if id_base == 9100 else f"-{id_base}"
    organization = Organization(
        github_org_id=id_base, login=f"review-domain{suffix}"
    )
    author = User(github_id=id_base + 1, username=f"author{suffix}")
    reviewer = User(github_id=id_base + 2, username=f"reviewer{suffix}")
    approver = User(github_id=id_base + 3, username=f"approver{suffix}")
    second_approver = User(
        github_id=id_base + 4, username=f"second-approver{suffix}"
    )
    db.add_all([organization, author, reviewer, approver, second_approver])
    db.flush()
    for user, role in (
        (author, AuthorizationRole.CONTRIBUTOR),
        (reviewer, AuthorizationRole.REVIEWER),
        (approver, AuthorizationRole.ADMIN),
        (second_approver, AuthorizationRole.OWNER),
    ):
        db.add(
            OrganizationMembership(
                organization_id=organization.id,
                user_id=user.id,
                role=role,
                is_active=True,
                github_verified=True,
            )
        )
    repository = Repository(
        github_repo_id=id_base + 100,
        organization_id=organization.id,
        name="policy",
        owner=organization.login,
        full_name=f"{organization.login}/policy",
    )
    score_version = ScoreVersion(
        version=f"review-score-v1{suffix}",
        name="Review score",
        weights={
            "correctness": 0.30,
            "tests": 0.20,
            "maintainability": 0.15,
            "security": 0.15,
            "documentation": 0.05,
            "architecture": 0.10,
            "change_risk": 0.05,
        },
        analyzer_weights={},
        required_analyzers=[],
        settings={},
        policy_hash=(
            "a" * 64 if id_base == 9100 else f"{id_base:064x}"[-64:]
        ),
    )
    db.add_all([repository, score_version])
    db.flush()
    pull_request = PullRequest(
        github_pr_id=id_base + 200,
        title="Require a human decision",
        author_id=author.id,
        repo_id=repository.id,
        state=PullRequestState.MERGED,
        head_sha="b" * 40,
        last_synchronized_head_sha="b" * 40,
        file_sync_complete=True,
    )
    db.add(pull_request)
    db.flush()
    score = Score(
        pr_id=pull_request.id,
        score_version_id=score_version.id,
        head_sha=pull_request.head_sha,
        analyzer_suite_version="suite-v1",
        scoring_policy_version=score_version.version,
        category_scores={"correctness": float(final_score)},
        category_confidence={"correctness": 1.0},
        unavailable_categories=[],
        final_score=Decimal(str(final_score)),
        confidence=Decimal("1"),
        input_complete=True,
        is_authoritative=authoritative,
        explanation={"test": True},
        deterministic_hash=(
            "c" * 64
            if id_base == 9100
            else f"{id_base + 1:064x}"[-64:]
        ),
    )
    db.add(score)
    db.flush()
    pull_request.latest_score_id = score.id
    db.flush()
    return {
        "repository": repository,
        "pull_request": pull_request,
        "score": score,
        "score_version": score_version,
        "author": author,
        "reviewer": reviewer,
        "approver": approver,
        "second_approver": second_approver,
    }


def _approve_review(db, graph, decision):
    return submit_review(
        db,
        decision=decision,
        reviewer=graph["reviewer"],
        reviewer_role=AuthorizationRole.REVIEWER,
        recommendation=ReviewRecommendation.APPROVE,
        summary="The evidence and policy checks support approval.",
        findings=[
            {
                "severity": "info",
                "category": "policy",
                "code": "EVIDENCE_VERIFIED",
                "message": "Score evidence matches the merged head.",
                "evidence": {"head_sha": graph["pull_request"].head_sha},
            }
        ],
    )


def test_score_never_directly_changes_eligibility(session_factory):
    db = session_factory()
    try:
        graph = _domain_fixture(db)
        pull_request = graph["pull_request"]
        assert pull_request.eligibility_state == EligibilityState.NOT_EVALUATED

        decision, created = evaluate_eligibility(
            db,
            pull_request=pull_request,
            actor_user_id=graph["reviewer"].id,
        )

        assert created is True
        assert decision.status == EligibilityDecisionStatus.PENDING_REVIEW
        assert pull_request.eligibility_state == EligibilityState.NOT_EVALUATED
        assert decision.score_id == graph["score"].id
        assert decision.score_version_id == graph["score_version"].id
        assert decision.repository_policy.version == "default-v1"
        assert decision.evaluation_result["score"]["deterministic_hash"] == "c" * 64
    finally:
        db.close()


def test_manual_pr_input_cannot_set_eligibility():
    with pytest.raises(ValueError):
        PullRequestCreate(
            github_pr_id=1,
            title="bypass attempt",
            repo_id=1,
            eligibility_state="eligible",
        )


def test_review_and_separate_approval_are_required_for_eligibility(session_factory):
    db = session_factory()
    try:
        graph = _domain_fixture(db)
        decision, _ = evaluate_eligibility(
            db,
            pull_request=graph["pull_request"],
            actor_user_id=graph["reviewer"].id,
        )
        with pytest.raises(EligibilityConflictError, match="not awaiting approval"):
            submit_approval(
                db,
                decision=decision,
                approver=graph["approver"],
                approver_role=AuthorizationRole.ADMIN,
                outcome=ApprovalOutcome.APPROVED,
                reason=None,
            )

        review = _approve_review(db, graph, decision)
        assert review.findings[0].code == "EVIDENCE_VERIFIED"
        assert decision.status == EligibilityDecisionStatus.PENDING_APPROVAL
        with pytest.raises(EligibilityConflictError, match="different users"):
            submit_approval(
                db,
                decision=decision,
                approver=graph["reviewer"],
                approver_role=AuthorizationRole.ADMIN,
                outcome=ApprovalOutcome.APPROVED,
                reason=None,
            )

        approval = submit_approval(
            db,
            decision=decision,
            approver=graph["approver"],
            approver_role=AuthorizationRole.ADMIN,
            outcome=ApprovalOutcome.APPROVED,
            reason="Independent approval complete",
        )

        assert decision.status == EligibilityDecisionStatus.ELIGIBLE
        assert graph["pull_request"].eligibility_state == EligibilityState.ELIGIBLE
        assert decision.final_approved_by_user_id == graph["approver"].id
        assert approval.score_id == graph["score"].id
        assert approval.score_version_id == graph["score_version"].id
        assert approval.repository_policy_id == decision.repository_policy_id
    finally:
        db.close()


def test_author_cannot_review_or_approve_own_pull_request(session_factory):
    db = session_factory()
    try:
        graph = _domain_fixture(db)
        decision, _ = evaluate_eligibility(
            db,
            pull_request=graph["pull_request"],
            actor_user_id=graph["reviewer"].id,
        )
        with pytest.raises(EligibilityConflictError, match="review themselves"):
            submit_review(
                db,
                decision=decision,
                reviewer=graph["author"],
                reviewer_role=AuthorizationRole.REVIEWER,
                recommendation=ReviewRecommendation.APPROVE,
                summary="Self review",
                findings=[],
            )
        _approve_review(db, graph, decision)
        with pytest.raises(EligibilityConflictError, match="approve themselves"):
            submit_approval(
                db,
                decision=decision,
                approver=graph["author"],
                approver_role=AuthorizationRole.ADMIN,
                outcome=ApprovalOutcome.APPROVED,
                reason=None,
            )
    finally:
        db.close()


def test_policy_failure_is_explainable_and_has_no_approval(session_factory):
    db = session_factory()
    try:
        graph = _domain_fixture(db, final_score=45)
        decision, _ = evaluate_eligibility(
            db,
            pull_request=graph["pull_request"],
            actor_user_id=graph["reviewer"].id,
        )

        assert decision.status == EligibilityDecisionStatus.INELIGIBLE
        assert decision.failure_reasons == ["MINIMUM_SCORE_NOT_MET"]
        assert graph["pull_request"].eligibility_state == EligibilityState.INELIGIBLE
        assert decision.reviews == []
        assert decision.approvals == []
    finally:
        db.close()


def test_policy_version_change_supersedes_pending_decision(session_factory):
    db = session_factory()
    try:
        graph = _domain_fixture(db)
        decision, _ = evaluate_eligibility(
            db,
            pull_request=graph["pull_request"],
            actor_user_id=graph["reviewer"].id,
        )
        rules = {
            **DEFAULT_ELIGIBILITY_RULES,
            "minimum_score": 85.0,
            "required_approvals": 2,
        }
        policy = set_repository_policy(
            db,
            repository=graph["repository"],
            name="High assurance",
            description=None,
            rules=rules,
            created_by_user_id=graph["approver"].id,
        )

        assert policy.id != decision.repository_policy_id
        assert decision.status == EligibilityDecisionStatus.SUPERSEDED
        assert decision.is_current is False
        assert graph["pull_request"].eligibility_state == EligibilityState.NOT_EVALUATED

        replacement, _ = evaluate_eligibility(
            db,
            pull_request=graph["pull_request"],
            actor_user_id=graph["reviewer"].id,
        )
        assert replacement.repository_policy_id == policy.id
        assert replacement.required_approvals == 2
    finally:
        db.close()


def test_repository_policy_can_require_multiple_independent_approvals(
    session_factory,
):
    db = session_factory()
    try:
        graph = _domain_fixture(db)
        policy = set_repository_policy(
            db,
            repository=graph["repository"],
            name="Two-person approval",
            description=None,
            rules={**DEFAULT_ELIGIBILITY_RULES, "required_approvals": 2},
            created_by_user_id=graph["approver"].id,
        )
        decision, _ = evaluate_eligibility(
            db,
            pull_request=graph["pull_request"],
            actor_user_id=graph["reviewer"].id,
        )
        _approve_review(db, graph, decision)

        submit_approval(
            db,
            decision=decision,
            approver=graph["approver"],
            approver_role=AuthorizationRole.ADMIN,
            outcome=ApprovalOutcome.APPROVED,
            reason=None,
        )
        assert decision.status == EligibilityDecisionStatus.PENDING_APPROVAL
        assert graph["pull_request"].eligibility_state == EligibilityState.NOT_EVALUATED

        submit_approval(
            db,
            decision=decision,
            approver=graph["second_approver"],
            approver_role=AuthorizationRole.OWNER,
            outcome=ApprovalOutcome.APPROVED,
            reason=None,
        )
        assert decision.status == EligibilityDecisionStatus.ELIGIBLE
        assert decision.repository_policy_id == policy.id
        assert decision.final_approved_by_user_id == graph["second_approver"].id
    finally:
        db.close()


def test_terminal_review_findings_and_approvals_are_insert_only(session_factory):
    db = session_factory()
    try:
        graph = _domain_fixture(db)
        decision, _ = evaluate_eligibility(
            db,
            pull_request=graph["pull_request"],
            actor_user_id=graph["reviewer"].id,
        )
        review = _approve_review(db, graph, decision)
        approval = submit_approval(
            db,
            decision=decision,
            approver=graph["approver"],
            approver_role=AuthorizationRole.ADMIN,
            outcome=ApprovalOutcome.APPROVED,
            reason=None,
        )
        db.commit()

        approval.reason = "rewrite history"
        with pytest.raises(ImmutableRecordError):
            db.flush()
        db.rollback()

        persisted_review = db.get(type(review), review.id)
        persisted_review.summary = "rewrite review"
        with pytest.raises(ImmutableRecordError):
            db.flush()
        db.rollback()

        finding = db.get(type(review.findings[0]), review.findings[0].id)
        finding.message = "rewrite finding"
        with pytest.raises(ImmutableRecordError):
            db.flush()
        db.rollback()
    finally:
        db.close()


def test_new_score_invalidation_resets_eligibility_without_deleting_history(
    session_factory,
):
    db = session_factory()
    try:
        graph = _domain_fixture(db)
        decision, _ = evaluate_eligibility(
            db,
            pull_request=graph["pull_request"],
            actor_user_id=graph["reviewer"].id,
        )
        _approve_review(db, graph, decision)
        submit_approval(
            db,
            decision=decision,
            approver=graph["approver"],
            approver_role=AuthorizationRole.ADMIN,
            outcome=ApprovalOutcome.APPROVED,
            reason=None,
        )
        assert graph["pull_request"].eligibility_state == EligibilityState.ELIGIBLE

        supersede_current_decision(db, graph["pull_request"])

        assert decision.is_current is False
        assert decision.status == EligibilityDecisionStatus.ELIGIBLE
        assert graph["pull_request"].eligibility_state == EligibilityState.NOT_EVALUATED
        assert decision.approvals
    finally:
        db.close()
