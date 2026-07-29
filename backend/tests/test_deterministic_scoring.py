from __future__ import annotations

from decimal import Decimal

import pytest

from app.analysis.analyzers import (
    DEFAULT_ANALYZERS,
    DiffSizeConcentrationAnalyzer,
    TestFileChangesAnalyzer,
)
from app.analysis.base import Analyzer, AnalyzerOutput
from app.analysis.engine import execute_scoring_run
from app.analysis.policy import policy_hash
from app.models.analysis_run import AnalyzerResultStatus
from app.models.authorization import Organization
from app.models.pull_request import PullRequest
from app.models.pull_request_file import PullRequestFile
from app.models.repository import Repository
from app.models.score import ImmutableRecordError, Score, ScoreVersion
from app.models.user import User
from app.models.webhook_delivery import IngestionState, WebhookDelivery


def _fixture_graph(db):
    organization = Organization(github_org_id=10, login="deterministic")
    user = User(github_id=20, username="analyst")
    db.add_all([organization, user])
    db.flush()
    repository = Repository(
        github_repo_id=30,
        organization_id=organization.id,
        name="engine",
        owner="deterministic",
        full_name="deterministic/engine",
    )
    db.add(repository)
    db.flush()
    pull_request = PullRequest(
        github_pr_id=40,
        title="Version the evidence",
        author_id=user.id,
        repo_id=repository.id,
        head_sha="a" * 40,
        file_sync_complete=True,
    )
    db.add(pull_request)
    db.flush()
    db.add_all(
        [
            PullRequestFile(
                pr_id=pull_request.id,
                filename="src/service.py",
                github_status="modified",
                sha="1" * 40,
                additions=30,
                deletions=5,
                changes=35,
                patch="@@ service",
                patch_available=True,
                patch_status="available",
            ),
            PullRequestFile(
                pr_id=pull_request.id,
                filename="tests/test_service.py",
                github_status="added",
                sha="2" * 40,
                additions=25,
                deletions=0,
                changes=25,
                patch="@@ tests",
                patch_available=True,
                patch_status="available",
            ),
            PullRequestFile(
                pr_id=pull_request.id,
                filename="docs/engine.md",
                github_status="modified",
                sha="3" * 40,
                additions=10,
                deletions=1,
                changes=11,
                patch="@@ docs",
                patch_available=True,
                patch_status="available",
            ),
        ]
    )
    db.flush()
    return repository, pull_request


def _delivery(db, sequence: int) -> WebhookDelivery:
    delivery = WebhookDelivery(
        delivery_id=f"score-delivery-{sequence}",
        event_type="pull_request",
        action="synchronize",
        payload={},
        payload_hash=f"{sequence:064d}",
        status=IngestionState.PROCESSING,
    )
    db.add(delivery)
    db.flush()
    return delivery


def _checks() -> list[dict]:
    return [
        {
            "id": 1,
            "name": "Ruff lint",
            "status": "completed",
            "conclusion": "success",
        },
        {
            "id": 2,
            "name": "Semgrep security",
            "status": "completed",
            "conclusion": "success",
        },
        {
            "id": 3,
            "name": "pytest",
            "status": "completed",
            "conclusion": "success",
        },
    ]


def _execute(db, pull_request, delivery, **overrides):
    return execute_scoring_run(
        db,
        pull_request=pull_request,
        delivery=delivery,
        check_runs=overrides.pop("check_runs", _checks()),
        metrics_snapshot={"total_files": 3},
        **overrides,
    )


def test_same_inputs_reuse_the_exact_run_and_score(session_factory):
    db = session_factory()
    try:
        _, pull_request = _fixture_graph(db)
        run, score, created = _execute(db, pull_request, _delivery(db, 1))
        repeated_run, repeated_score, repeated_created = _execute(
            db, pull_request, _delivery(db, 2)
        )

        assert created is True
        assert repeated_created is False
        assert repeated_run.id == run.id
        assert repeated_score.id == score.id
        assert db.query(Score).count() == 1
        assert score.evidence
        assert score.deterministic_hash
    finally:
        db.close()


def test_head_or_analyzer_version_creates_new_immutable_score(session_factory):
    class DiffV2(DiffSizeConcentrationAnalyzer):
        version = "2.0.0"

    db = session_factory()
    try:
        _, pull_request = _fixture_graph(db)
        _, original, _ = _execute(db, pull_request, _delivery(db, 1))
        original_hash = original.deterministic_hash

        pull_request.head_sha = "b" * 40
        _, head_score, _ = _execute(db, pull_request, _delivery(db, 2))
        analyzers = (DiffV2(),) + DEFAULT_ANALYZERS[1:]
        _, analyzer_score, _ = _execute(
            db,
            pull_request,
            _delivery(db, 3),
            analyzers=analyzers,
        )

        assert len({original.id, head_score.id, analyzer_score.id}) == 3
        assert original.deterministic_hash == original_hash
        assert original.head_sha == "a" * 40
        assert analyzer_score.analyzer_suite_version != head_score.analyzer_suite_version
    finally:
        db.close()


def test_repository_policy_change_creates_a_new_score_version(session_factory):
    db = session_factory()
    try:
        repository, pull_request = _fixture_graph(db)
        _, original, _ = _execute(db, pull_request, _delivery(db, 1))
        weights = {
            "correctness": 0.10,
            "tests": 0.40,
            "maintainability": 0.05,
            "security": 0.10,
            "documentation": 0.20,
            "architecture": 0.10,
            "change_risk": 0.05,
        }
        digest = policy_hash(weights, {}, [], {"minimum_confidence": 0.1})
        policy = ScoreVersion(
            version=f"test-{digest[:12]}",
            name="Test-heavy repository",
            weights=weights,
            analyzer_weights={},
            required_analyzers=[],
            settings={"minimum_confidence": 0.1},
            policy_hash=digest,
        )
        db.add(policy)
        db.flush()
        repository.scoring_policy = policy

        _, rescored, _ = _execute(db, pull_request, _delivery(db, 2))

        assert rescored.id != original.id
        assert rescored.score_version_id == policy.id
        assert rescored.scoring_policy_version == policy.version
        assert rescored.deterministic_hash != original.deterministic_hash
        assert db.query(Score).count() == 2
    finally:
        db.close()


def test_analyzer_failure_is_error_and_never_becomes_zero(session_factory):
    class BrokenAnalyzer(Analyzer):
        name = "broken_security_tool"
        version = "1.0.0"
        category = "security"

        def analyze(self, context):
            raise RuntimeError("scanner executable unavailable")

    db = session_factory()
    try:
        _, pull_request = _fixture_graph(db)
        analyzers = (DiffSizeConcentrationAnalyzer(), BrokenAnalyzer())
        run, score, _ = _execute(
            db,
            pull_request,
            _delivery(db, 1),
            analyzers=analyzers,
        )
        broken = next(
            result
            for result in run.analyzer_results
            if result.analyzer_name == "broken_security_tool"
        )

        assert broken.status == AnalyzerResultStatus.ERROR
        assert broken.score is None
        assert "security" in score.unavailable_categories
        assert score.final_score == Decimal("85.00")
        assert score.is_authoritative is False
    finally:
        db.close()


def test_language_aware_test_detection_and_insert_only_scores(session_factory):
    db = session_factory()
    try:
        _, pull_request = _fixture_graph(db)
        run, score, _ = _execute(db, pull_request, _delivery(db, 1))
        test_result = next(
            result
            for result in run.analyzer_results
            if result.analyzer_name == TestFileChangesAnalyzer.name
        )
        classified = test_result.evidence[0]["data"]
        assert classified["languages"] == ["Markdown", "Python"]
        assert classified["test_files"] == ["tests/test_service.py"]

        score.final_score = Decimal("0")
        with pytest.raises(ImmutableRecordError):
            db.flush()
        db.rollback()
    finally:
        db.close()
