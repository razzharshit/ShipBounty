from __future__ import annotations

from decimal import Decimal

import pytest

from app.models.bounty_domain import (
    BountyStatus,
    ClaimStatus,
    FundingStatus,
    IssueState,
    PayoutAttemptState,
    PayoutState,
)
from app.models.score import ImmutableRecordError
from app.services.bounty_service import (
    BountyConflictError,
    approve_claim,
    assign_bounty,
    authorize_payout,
    confirm_payout,
    create_bounty,
    create_issue,
    create_payout,
    create_wallet,
    mark_attempt_failed,
    mark_attempt_submitted,
    mark_bounty_funded,
    start_payout_attempt,
    verify_wallet_for_bounty,
)
from app.services.eligibility_service import (
    evaluate_eligibility,
    submit_approval,
)
from app.models.authorization import AuthorizationRole
from app.models.review_domain import ApprovalOutcome
from test_review_approval_domain import _approve_review, _domain_fixture


def _approved_claim_graph(db, *, verified_wallet=True):
    graph = _domain_fixture(db)
    decision, _ = evaluate_eligibility(
        db,
        pull_request=graph["pull_request"],
        actor_user_id=graph["reviewer"].id,
    )
    _approve_review(db, graph, decision)
    approval = submit_approval(
        db,
        decision=decision,
        approver=graph["approver"],
        approver_role=AuthorizationRole.ADMIN,
        outcome=ApprovalOutcome.APPROVED,
        reason="Bounty eligibility approved",
    )
    issue = create_issue(
        db,
        repository=graph["repository"],
        github_issue_id=9400,
        number=42,
        title="Implement the bounty domain",
        url="https://github.com/review-domain/policy/issues/42",
    )
    bounty = create_bounty(
        db,
        repository=graph["repository"],
        issue=issue,
        amount=Decimal("125.500000"),
        currency="usdc",
        expires_at=None,
        created_by_user_id=graph["approver"].id,
    )
    mark_bounty_funded(db, bounty)
    assignment = assign_bounty(
        db,
        bounty=bounty,
        assignee_user_id=graph["author"].id,
        assigned_by_user_id=graph["approver"].id,
    )
    wallet = create_wallet(
        db,
        user_id=graph["author"].id,
        chain="base",
        address="0xABCDEF1234",
    )
    wallet.verified = verified_wallet
    db.flush()
    claim = None
    if verified_wallet:
        claim = approve_claim(
            db,
            bounty=bounty,
            assignment=assignment,
            pull_request=graph["pull_request"],
            decision=decision,
            claimant_user_id=graph["author"].id,
            wallet=wallet,
        )
    return {
        **graph,
        "decision": decision,
        "approval": approval,
        "issue": issue,
        "bounty": bounty,
        "assignment": assignment,
        "wallet": wallet,
        "claim": claim,
    }


def test_claim_requires_issue_policy_funding_assignment_and_approval(session_factory):
    db = session_factory()
    try:
        graph = _approved_claim_graph(db)
        claim = graph["claim"]

        assert graph["issue"].repository_id == graph["repository"].id
        assert graph["bounty"].bounty_policy.version == "default-v1"
        assert graph["bounty"].eligibility_policy_id == graph["decision"].repository_policy_id
        assert claim.status == ClaimStatus.APPROVED
        assert claim.approval_id == graph["approval"].id
        assert claim.amount == Decimal("125.500000")
        assert claim.currency == "USDC"
        assert claim.destination_chain == "base"
        assert claim.destination_address == "0xABCDEF1234"
        assert graph["bounty"].status == BountyStatus.CLOSED
    finally:
        db.close()


def test_unverified_wallet_cannot_create_approved_claim(session_factory):
    db = session_factory()
    try:
        graph = _approved_claim_graph(db, verified_wallet=False)
        with pytest.raises(BountyConflictError, match="verified claimant wallet"):
            approve_claim(
                db,
                bounty=graph["bounty"],
                assignment=graph["assignment"],
                pull_request=graph["pull_request"],
                decision=graph["decision"],
                claimant_user_id=graph["author"].id,
                wallet=graph["wallet"],
            )
    finally:
        db.close()


def test_closed_issue_cannot_create_bounty(session_factory):
    db = session_factory()
    try:
        graph = _domain_fixture(db)
        issue = create_issue(
            db,
            repository=graph["repository"],
            github_issue_id=9401,
            number=43,
            title="Already closed",
            url=None,
            state=IssueState.CLOSED,
        )
        with pytest.raises(BountyConflictError, match="open issue"):
            create_bounty(
                db,
                repository=graph["repository"],
                issue=issue,
                amount=Decimal("25"),
                currency="USDC",
                expires_at=None,
                created_by_user_id=graph["approver"].id,
            )
    finally:
        db.close()


def test_wallet_verification_is_scoped_to_active_bounty_assignee(session_factory):
    db = session_factory()
    try:
        graph = _approved_claim_graph(db, verified_wallet=False)
        unrelated = create_wallet(
            db,
            user_id=graph["reviewer"].id,
            chain="base",
            address="0xUNRELATED",
        )
        with pytest.raises(BountyConflictError, match="active assignee"):
            verify_wallet_for_bounty(
                db, bounty=graph["bounty"], wallet=unrelated
            )

        verified = verify_wallet_for_bounty(
            db, bounty=graph["bounty"], wallet=graph["wallet"]
        )
        assert verified.verified is True
    finally:
        db.close()


def test_payout_creation_requires_a_treasury_snapshot(session_factory):
    db = session_factory()
    try:
        graph = _approved_claim_graph(db)
        with pytest.raises(BountyConflictError, match="treasury account"):
            create_payout(
                db,
                claim=graph["claim"],
                idempotency_key="create-payout-0001",
                treasury_account=None,
            )
    finally:
        db.close()
