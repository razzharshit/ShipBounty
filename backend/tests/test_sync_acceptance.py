import pytest

from app.github.client import GitHubCheckSnapshot, GitHubFileSnapshot
from app.models.analysis_run import AnalysisRun, AnalysisRunStatus
from app.models.pull_request import PullRequest, PullRequestState
from app.models.webhook_delivery import IngestionState, WebhookDelivery
from app.models.authorization import (
    AuthorizationRole,
    OAuthCredential,
    Organization,
    OrganizationMembership,
    RepositoryPermission,
)
from app.models.repository import Repository
from app.models.user import User
from app.services import delivery_processor, webhook_sync_service


def _delivery(session_factory, delivery_id: str, action: str = "opened") -> int:
    db = session_factory()
    delivery = WebhookDelivery(
        delivery_id=delivery_id,
        event_type="pull_request",
        action=action,
        installation_id=11,
        repository_id=22,
        payload={
            "installation": {"id": 11},
            "repository": {
                "id": 22,
                "name": "widgets",
                "full_name": "acme/widgets",
                "owner": {"id": 33, "login": "acme", "type": "Organization"},
            },
            "pull_request": {"number": 7},
        },
        payload_hash=delivery_id.ljust(64, "0")[:64],
        status=IngestionState.QUEUED,
    )
    db.add(delivery)
    db.commit()
    delivery_pk = delivery.id
    db.close()
    return delivery_pk


def _remote_pr(
    *,
    state="open",
    merged=False,
    draft=False,
    updated_at="2026-07-25T10:00:00Z",
    head_sha="a" * 40,
) -> dict:
    return {
        "id": 101,
        "number": 7,
        "title": "Reliable sync",
        "state": state,
        "merged": merged,
        "draft": draft,
        "updated_at": updated_at,
        "head": {"sha": head_sha},
        "user": {"id": 201, "login": "octocat", "avatar_url": None},
        "base": {
            "repo": {
                "id": 22,
                "name": "widgets",
                "full_name": "acme/widgets",
                "owner": {"id": 33, "login": "acme", "type": "Organization"},
            }
        },
        "additions": 5,
        "deletions": 2,
        "changed_files": 1,
        "requested_reviewers": [],
        "requested_teams": [],
    }


def _remote_file(filename="src/app.py", **overrides) -> dict:
    data = {
        "filename": filename,
        "status": "modified",
        "sha": "f" * 40,
        "additions": 5,
        "deletions": 2,
        "changes": 7,
        "patch": "@@ -1 +1 @@",
    }
    data.update(overrides)
    return data


def _mock_github(monkeypatch, remote_pr: dict, snapshot: GitHubFileSnapshot):
    monkeypatch.setattr(webhook_sync_service, "get_installation_token", lambda _: "token")
    monkeypatch.setattr(
        webhook_sync_service,
        "get_pull_request",
        lambda repo, number, token: remote_pr,
    )
    monkeypatch.setattr(
        webhook_sync_service,
        "get_pr_reviews",
        lambda repo, number, token: [],
    )
    monkeypatch.setattr(
        webhook_sync_service,
        "get_pr_files",
        lambda repo, number, token: snapshot,
    )
    monkeypatch.setattr(
        webhook_sync_service,
        "get_check_runs",
        lambda repo, head_sha, token: GitHubCheckSnapshot(
            check_runs=[],
            limit_reached=False,
        ),
    )


@pytest.mark.parametrize(
    ("action", "remote_pr", "expected"),
    [
        ("closed", _remote_pr(state="closed", merged=False), PullRequestState.CLOSED),
        ("closed", _remote_pr(state="closed", merged=True), PullRequestState.MERGED),
        (
            "reopened",
            _remote_pr(state="open", merged=False, updated_at="2026-07-25T10:01:00Z"),
            PullRequestState.OPEN,
        ),
    ],
)
def test_lifecycle_transitions_from_current_github_state(
    monkeypatch,
    session_factory,
    action,
    remote_pr,
    expected,
):
    monkeypatch.setattr(delivery_processor, "SessionLocal", session_factory)
    _mock_github(
        monkeypatch,
        remote_pr,
        GitHubFileSnapshot(files=[_remote_file()], limit_reached=False),
    )
    delivery_pk = _delivery(session_factory, f"delivery-{action}-{expected.value}", action)

    assert delivery_processor.process_delivery_once(delivery_pk, next_retry_seconds=10) == "synchronized"

    db = session_factory()
    try:
        pr = db.query(PullRequest).one()
        assert pr.state == expected
        assert pr.github_pr_number == remote_pr["number"]
        assert pr.file_sync_complete is True
        assert pr.last_synchronized_head_sha == remote_pr["head"]["sha"]
        run = db.query(AnalysisRun).one()
        assert run.status == AnalysisRunStatus.COMPLETE
        assert run.is_authoritative is True
    finally:
        db.close()


def test_older_job_cannot_overwrite_newer_state(monkeypatch, session_factory):
    monkeypatch.setattr(delivery_processor, "SessionLocal", session_factory)
    newer = _remote_pr(
        state="closed",
        merged=True,
        updated_at="2026-07-25T12:00:00Z",
        head_sha="b" * 40,
    )
    _mock_github(
        monkeypatch,
        newer,
        GitHubFileSnapshot(files=[_remote_file()], limit_reached=False),
    )
    newer_delivery = _delivery(session_factory, "delivery-newer", "closed")
    delivery_processor.process_delivery_once(newer_delivery, next_retry_seconds=10)

    older = _remote_pr(
        state="open",
        merged=False,
        updated_at="2026-07-25T11:00:00Z",
        head_sha="a" * 40,
    )
    _mock_github(
        monkeypatch,
        older,
        GitHubFileSnapshot(files=[_remote_file()], limit_reached=False),
    )
    older_delivery = _delivery(session_factory, "delivery-older", "reopened")

    assert delivery_processor.process_delivery_once(older_delivery, next_retry_seconds=10) == "stale_skipped"
    db = session_factory()
    try:
        pr = db.query(PullRequest).one()
        assert pr.state == PullRequestState.MERGED
        assert pr.head_sha == "b" * 40
        assert pr.last_processed_delivery_id == "delivery-newer"
        assert db.get(WebhookDelivery, older_delivery).status == IngestionState.COMPLETE
    finally:
        db.close()


def test_file_limit_is_incomplete_and_has_no_authoritative_score(
    monkeypatch,
    session_factory,
):
    monkeypatch.setattr(delivery_processor, "SessionLocal", session_factory)
    _mock_github(
        monkeypatch,
        _remote_pr(updated_at="2026-07-25T13:00:00Z", head_sha="c" * 40),
        GitHubFileSnapshot(files=[_remote_file()] * 3000, limit_reached=True),
    )
    delivery_pk = _delivery(session_factory, "delivery-file-limit")

    assert delivery_processor.process_delivery_once(delivery_pk, next_retry_seconds=10) == "incomplete"

    db = session_factory()
    try:
        delivery = db.get(WebhookDelivery, delivery_pk)
        pr = db.query(PullRequest).one()
        run = db.query(AnalysisRun).one()
        assert delivery.status == IngestionState.INCOMPLETE
        assert delivery.incomplete_reason == "GITHUB_FILE_LIMIT"
        assert pr.file_sync_complete is False
        assert pr.incomplete_reason == "GITHUB_FILE_LIMIT"
        assert pr.latest_score is None
        assert pr.metrics is None
        assert run.status == AnalysisRunStatus.INCOMPLETE
        assert run.is_authoritative is False
        assert run.incomplete_reason == "GITHUB_FILE_LIMIT"
    finally:
        db.close()


def test_worker_failure_can_retry_to_completion(monkeypatch, session_factory):
    monkeypatch.setattr(delivery_processor, "SessionLocal", session_factory)
    delivery_pk = _delivery(session_factory, "delivery-retry")
    calls = 0

    def crash_once(db, delivery):
        nonlocal calls
        calls += 1
        if calls == 1:
            raise RuntimeError("worker crashed")
        return "synchronized"

    monkeypatch.setattr(delivery_processor, "synchronize_webhook_delivery", crash_once)
    with pytest.raises(RuntimeError, match="worker crashed"):
        delivery_processor.process_delivery_once(delivery_pk, next_retry_seconds=1)

    assert delivery_processor.process_delivery_once(delivery_pk, next_retry_seconds=1) == "synchronized"
    db = session_factory()
    try:
        delivery = db.get(WebhookDelivery, delivery_pk)
        assert delivery.status == IngestionState.COMPLETE
        assert delivery.attempt_count == 2
        assert delivery.completed_at is not None
    finally:
        db.close()


def test_crash_rolls_back_partial_snapshot_then_retry_applies_atomically(
    monkeypatch,
    session_factory,
):
    monkeypatch.setattr(delivery_processor, "SessionLocal", session_factory)
    first_remote = _remote_pr(
        updated_at="2026-07-25T14:00:00Z",
        head_sha="1" * 40,
    )
    _mock_github(
        monkeypatch,
        first_remote,
        GitHubFileSnapshot(
            files=[_remote_file(patch="old patch", sha="1" * 40)],
            limit_reached=False,
        ),
    )
    first_delivery = _delivery(session_factory, "delivery-before-crash")
    delivery_processor.process_delivery_once(first_delivery, next_retry_seconds=1)

    second_remote = _remote_pr(
        updated_at="2026-07-25T14:01:00Z",
        head_sha="2" * 40,
    )
    _mock_github(
        monkeypatch,
        second_remote,
        GitHubFileSnapshot(
            files=[
                _remote_file(
                    patch="new patch",
                    sha="2" * 40,
                    additions=50,
                    deletions=10,
                    changes=60,
                )
            ],
            limit_reached=False,
        ),
    )
    second_delivery = _delivery(session_factory, "delivery-crashes")
    real_analyze = webhook_sync_service.analyze_pull_request

    def crash_after_file_flush(db, pr_id, *, commit):
        raise RuntimeError("crash after snapshot flush")

    monkeypatch.setattr(
        webhook_sync_service,
        "analyze_pull_request",
        crash_after_file_flush,
    )
    with pytest.raises(RuntimeError, match="crash after snapshot flush"):
        delivery_processor.process_delivery_once(second_delivery, next_retry_seconds=1)

    db = session_factory()
    try:
        pr = db.query(PullRequest).one()
        assert pr.head_sha == "1" * 40
        assert pr.files[0].patch == "old patch"
        assert pr.files[0].additions == 5
    finally:
        db.close()

    monkeypatch.setattr(
        webhook_sync_service,
        "analyze_pull_request",
        real_analyze,
    )
    assert delivery_processor.process_delivery_once(second_delivery, next_retry_seconds=1) == "synchronized"

    db = session_factory()
    try:
        pr = db.query(PullRequest).one()
        assert pr.head_sha == "2" * 40
        assert pr.files[0].patch == "new patch"
        assert pr.files[0].additions == 50
        assert db.get(WebhookDelivery, second_delivery).attempt_count == 2
    finally:
        db.close()


def test_github_authorization_revocation_removes_credentials_and_access(
    monkeypatch, session_factory
):
    monkeypatch.setattr(delivery_processor, "SessionLocal", session_factory)
    db = session_factory()
    user = User(github_id=9001, username="revoked-user", session_version=2)
    organization = Organization(github_org_id=9002, login="revoked-org")
    db.add_all([user, organization])
    db.flush()
    repository = Repository(
        github_repo_id=9003,
        organization_id=organization.id,
        name="private-repo",
        owner="revoked-org",
        full_name="revoked-org/private-repo",
    )
    db.add(repository)
    db.flush()
    db.add_all(
        [
            OrganizationMembership(
                organization_id=organization.id,
                user_id=user.id,
                role=AuthorizationRole.VIEWER,
                github_role="member",
                github_verified=True,
                is_active=True,
            ),
            RepositoryPermission(
                repository_id=repository.id,
                user_id=user.id,
                role=AuthorizationRole.VIEWER,
                source="github",
            ),
            OAuthCredential(
                user_id=user.id,
                provider="github",
                access_token_ciphertext="encrypted",
                encryption_key_id="v1",
            ),
        ]
    )
    delivery = WebhookDelivery(
        delivery_id="authorization-revoked",
        event_type="github_app_authorization",
        action="revoked",
        payload={"sender": {"id": user.github_id}},
        payload_hash="e" * 64,
        status=IngestionState.QUEUED,
    )
    db.add(delivery)
    db.commit()
    delivery_pk = delivery.id
    db.close()

    assert (
        delivery_processor.process_delivery_once(delivery_pk, next_retry_seconds=10)
        == "authorization_revoked"
    )
    db = session_factory()
    try:
        stored_user = db.query(User).filter(User.github_id == 9001).one()
        assert stored_user.session_version == 3
        assert db.query(OAuthCredential).count() == 0
        assert db.query(RepositoryPermission).count() == 0
        assert db.query(OrganizationMembership).one().is_active is False
    finally:
        db.close()
