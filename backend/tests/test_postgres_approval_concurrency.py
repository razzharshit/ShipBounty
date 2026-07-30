from __future__ import annotations

import os
import random
import threading

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.models.authorization import AuthorizationRole
from app.models.review_domain import (
    Approval,
    ApprovalOutcome,
    EligibilityDecision,
    EligibilityDecisionStatus,
)
from app.models.user import User
from app.services.eligibility_service import (
    DEFAULT_ELIGIBILITY_RULES,
    EligibilityConflictError,
    evaluate_eligibility,
    set_repository_policy,
    submit_approval,
    supersede_current_decision,
)
from test_review_approval_domain import _approve_review, _domain_fixture


pytestmark = [pytest.mark.integration, pytest.mark.concurrency]


def _factory():
    url = os.getenv("TEST_POSTGRES_URL")
    if not url:
        pytest.skip("TEST_POSTGRES_URL is not configured")
    engine = create_engine(url)
    return engine, sessionmaker(bind=engine, expire_on_commit=False)


def _pending_decision(factory):
    db = factory()
    try:
        graph = _domain_fixture(
            db, id_base=random.randint(1_000_000, 2_000_000_000)
        )
        set_repository_policy(
            db,
            repository=graph["repository"],
            name="Concurrent approvals",
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
        result = (
            decision.id,
            graph["approver"].id,
            graph["second_approver"].id,
        )
        db.commit()
        return result
    finally:
        db.close()


def _race(factory, decision_id, actors):
    barrier = threading.Barrier(len(actors))
    results = []
    lock = threading.Lock()

    def worker(user_id, role, outcome):
        db = factory()
        try:
            decision = db.get(EligibilityDecision, decision_id)
            user = db.get(User, user_id)
            barrier.wait(timeout=10)
            submit_approval(
                db,
                decision=decision,
                approver=user,
                approver_role=role,
                outcome=outcome,
                reason="Concurrent rejection" if outcome == ApprovalOutcome.REJECTED else None,
            )
            db.commit()
            value = "committed"
        except EligibilityConflictError:
            db.rollback()
            value = "conflict"
        finally:
            db.close()
        with lock:
            results.append(value)

    threads = [
        threading.Thread(target=worker, args=actor, daemon=True)
        for actor in actors
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=15)
    assert all(not thread.is_alive() for thread in threads)
    return results


def test_distinct_simultaneous_approvals_serialize_to_eligible():
    engine, factory = _factory()
    try:
        decision_id, first_id, second_id = _pending_decision(factory)
        results = _race(
            factory,
            decision_id,
            [
                (first_id, AuthorizationRole.ADMIN, ApprovalOutcome.APPROVED),
                (second_id, AuthorizationRole.OWNER, ApprovalOutcome.APPROVED),
            ],
        )
        db = factory()
        try:
            decision = db.get(EligibilityDecision, decision_id)
            count = (
                db.query(Approval)
                .filter(Approval.eligibility_decision_id == decision_id)
                .count()
            )
            assert results == ["committed", "committed"]
            assert count == 2
            assert decision.status == EligibilityDecisionStatus.ELIGIBLE
        finally:
            db.close()
    finally:
        engine.dispose()


def test_same_approver_and_approve_reject_races_are_deterministic():
    engine, factory = _factory()
    try:
        decision_id, first_id, _ = _pending_decision(factory)
        results = _race(
            factory,
            decision_id,
            [
                (first_id, AuthorizationRole.ADMIN, ApprovalOutcome.APPROVED),
                (first_id, AuthorizationRole.ADMIN, ApprovalOutcome.APPROVED),
            ],
        )
        assert sorted(results) == ["committed", "conflict"]

        decision_id, first_id, second_id = _pending_decision(factory)
        _race(
            factory,
            decision_id,
            [
                (first_id, AuthorizationRole.ADMIN, ApprovalOutcome.APPROVED),
                (second_id, AuthorizationRole.OWNER, ApprovalOutcome.REJECTED),
            ],
        )
        db = factory()
        try:
            decision = db.get(EligibilityDecision, decision_id)
            assert decision.status == EligibilityDecisionStatus.INELIGIBLE
        finally:
            db.close()
    finally:
        engine.dispose()


def test_stale_invalidation_cannot_leave_a_current_approved_decision():
    engine, factory = _factory()
    try:
        decision_id, approver_id, _ = _pending_decision(factory)
        setup = factory()
        try:
            pr_id = setup.get(EligibilityDecision, decision_id).pr_id
        finally:
            setup.close()
        barrier = threading.Barrier(2)
        errors = []

        def approve():
            db = factory()
            try:
                barrier.wait(timeout=10)
                submit_approval(
                    db,
                    decision=db.get(EligibilityDecision, decision_id),
                    approver=db.get(User, approver_id),
                    approver_role=AuthorizationRole.ADMIN,
                    outcome=ApprovalOutcome.APPROVED,
                    reason=None,
                )
                db.commit()
            except EligibilityConflictError:
                db.rollback()
            except Exception as exc:
                errors.append(exc)
                db.rollback()
            finally:
                db.close()

        def invalidate():
            from app.models.pull_request import PullRequest

            db = factory()
            try:
                barrier.wait(timeout=10)
                supersede_current_decision(db, db.get(PullRequest, pr_id))
                db.commit()
            except Exception as exc:
                errors.append(exc)
                db.rollback()
            finally:
                db.close()

        threads = [
            threading.Thread(target=approve, daemon=True),
            threading.Thread(target=invalidate, daemon=True),
        ]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=15)
        assert not errors
        db = factory()
        try:
            decision = db.get(EligibilityDecision, decision_id)
            assert decision.is_current is False
            assert decision.status == EligibilityDecisionStatus.SUPERSEDED
        finally:
            db.close()
    finally:
        engine.dispose()
