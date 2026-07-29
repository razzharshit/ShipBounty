from __future__ import annotations

import hashlib
import logging
from datetime import datetime, timezone
from enum import Enum

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.analysis.engine import (
    execute_scoring_run,
    record_incomplete_scoring_run,
)
from app.github.auth import get_installation_token
from app.github.client import (
    get_check_runs,
    get_pr_files,
    get_pr_reviews,
    get_pull_request,
    github_rate_limit_scope,
)
from app.models.authorization import GitHubInstallation, Organization
from app.models.authorization import (
    OAuthCredential,
    OrganizationMembership,
    RepositoryPermission,
)
from app.models.pr_metrics import PRMetrics
from app.models.pull_request import (
    EligibilityState,
    PullRequest,
    PullRequestState,
    ReviewState,
)
from app.models.repository import Repository
from app.models.user import User
from app.models.webhook_delivery import WebhookDelivery
from app.services.pr_analysis_service import analyze_pull_request
from app.services.pr_file_service import synchronize_pr_files
from app.services.audit_service import record_audit_event
from app.services.eligibility_service import supersede_current_decision


logger = logging.getLogger(__name__)

PULL_REQUEST_ACTIONS = {
    "opened",
    "reopened",
    "synchronize",
    "closed",
    "edited",
    "ready_for_review",
    "converted_to_draft",
    "review_requested",
    "review_request_removed",
}
PULL_REQUEST_REVIEW_ACTIONS = {"submitted", "dismissed"}
CHECK_RUN_ACTIONS = {"created", "rerequested", "completed", "requested_action"}
CHECK_SUITE_ACTIONS = {"requested", "rerequested", "completed"}


class IncompleteReason(str, Enum):
    GITHUB_FILE_LIMIT = "GITHUB_FILE_LIMIT"
    MISSING_REQUIRED_FIELDS = "MISSING_REQUIRED_FIELDS"


class IncompleteDeliveryError(ValueError):
    def __init__(self, reason: IncompleteReason, message: str) -> None:
        super().__init__(message)
        self.reason = reason


def _lifecycle_state(pr_data: dict) -> PullRequestState:
    if pr_data.get("merged"):
        return PullRequestState.MERGED
    if (pr_data.get("state") or "").lower() == "closed":
        return PullRequestState.CLOSED
    if pr_data.get("draft"):
        return PullRequestState.DRAFT
    return PullRequestState.OPEN


def _review_state(pr_data: dict, reviews: list[dict]) -> ReviewState:
    decisive_state_by_reviewer: dict[int | str, str] = {}
    for review in reviews:
        user = review.get("user") or {}
        reviewer_key = user.get("id") or user.get("login") or review.get("id")
        state = str(review.get("state") or "").upper()
        if state in {"APPROVED", "CHANGES_REQUESTED"}:
            decisive_state_by_reviewer[reviewer_key] = state
        elif state == "DISMISSED":
            decisive_state_by_reviewer.pop(reviewer_key, None)

    current_states = set(decisive_state_by_reviewer.values())
    if "CHANGES_REQUESTED" in current_states:
        return ReviewState.CHANGES_REQUESTED
    if "APPROVED" in current_states:
        return ReviewState.APPROVED
    if pr_data.get("requested_reviewers") or pr_data.get("requested_teams") or reviews:
        return ReviewState.UNDER_REVIEW
    return ReviewState.NOT_REQUESTED


def _is_supported(delivery: WebhookDelivery) -> bool:
    if delivery.event_type == "github_app_authorization":
        return delivery.action == "revoked"
    if delivery.event_type == "pull_request":
        return delivery.action in PULL_REQUEST_ACTIONS
    if delivery.event_type == "pull_request_review":
        return delivery.action in PULL_REQUEST_REVIEW_ACTIONS
    if delivery.event_type == "check_run":
        return delivery.action in CHECK_RUN_ACTIONS
    if delivery.event_type == "check_suite":
        return delivery.action in CHECK_SUITE_ACTIONS
    return False


def _pull_request_number(payload: dict, event_type: str) -> int | None:
    direct = payload.get("pull_request") or {}
    if direct.get("number"):
        return int(direct["number"])
    container = payload.get(event_type) or {}
    linked = container.get("pull_requests") or []
    if linked and linked[0].get("number"):
        return int(linked[0]["number"])
    return None


def _revoke_user_authorization(db: Session, delivery: WebhookDelivery) -> str:
    user_data = delivery.payload.get("sender") or {}
    github_user_id = user_data.get("id")
    if not github_user_id:
        raise IncompleteDeliveryError(
            IncompleteReason.MISSING_REQUIRED_FIELDS,
            "github_app_authorization.revoked is missing sender.id",
        )
    user = db.query(User).filter(User.github_id == int(github_user_id)).first()
    if user is None:
        return "authorization_already_absent"
    db.query(OAuthCredential).filter(OAuthCredential.user_id == user.id).delete(
        synchronize_session=False
    )
    db.query(RepositoryPermission).filter(
        RepositoryPermission.user_id == user.id,
        RepositoryPermission.source == "github",
    ).delete(synchronize_session=False)
    db.query(OrganizationMembership).filter(
        OrganizationMembership.user_id == user.id,
        OrganizationMembership.github_verified.is_(True),
    ).update(
        {OrganizationMembership.is_active: False},
        synchronize_session=False,
    )
    user.session_version += 1
    record_audit_event(
        db,
        action="auth.github_authorization_revoked",
        resource_type="user",
        actor_user_id=user.id,
        resource_id=user.id,
        event_metadata={"delivery_id": delivery.delivery_id},
    )
    db.flush()
    return "authorization_revoked"


def _parse_github_datetime(value: object) -> datetime:
    if not isinstance(value, str) or not value:
        raise IncompleteDeliveryError(
            IncompleteReason.MISSING_REQUIRED_FIELDS,
            "GitHub's current pull request response is missing updated_at",
        )
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def _parse_optional_github_datetime(value: object) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def _comparable_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _pull_resource_lock_key(repository_id: int, pr_number: int) -> int:
    digest = hashlib.blake2b(
        f"{repository_id}:{pr_number}".encode(),
        digest_size=8,
    ).digest()
    return int.from_bytes(digest, byteorder="big", signed=True)


def _lock_pull_request_resource(
    db: Session,
    repository_id: int,
    pr_number: int,
) -> None:
    if db.get_bind().dialect.name == "postgresql":
        db.execute(
            text("SELECT pg_advisory_xact_lock(:resource_key)"),
            {"resource_key": _pull_resource_lock_key(repository_id, pr_number)},
        )


def _get_or_create_user(db: Session, user_data: dict) -> User:
    github_user_id = int(user_data["id"])
    user = db.query(User).filter(User.github_id == github_user_id).first()
    if user is None:
        user = User(github_id=github_user_id, username=str(user_data["login"]))
        db.add(user)
    user.username = str(user_data["login"])
    user.avatar_url = user_data.get("avatar_url")
    db.flush()
    return user


def _get_or_create_organization(db: Session, owner_data: dict) -> Organization:
    github_account_id = int(owner_data["id"])
    login = str(owner_data["login"]).lower()
    organization = (
        db.query(Organization)
        .filter(
            (Organization.github_org_id == github_account_id)
            | (Organization.login == login)
        )
        .first()
    )
    if organization is None:
        organization = Organization(
            github_org_id=github_account_id,
            login=login,
        )
        db.add(organization)
    organization.github_org_id = github_account_id
    organization.login = login
    organization.display_name = owner_data.get("name") or owner_data.get("login")
    organization.avatar_url = owner_data.get("avatar_url")
    db.flush()
    return organization


def _get_or_create_installation(
    db: Session,
    installation_data: dict,
    organization: Organization,
    owner_data: dict,
) -> GitHubInstallation:
    installation_id = int(installation_data["id"])
    installation = (
        db.query(GitHubInstallation)
        .filter(GitHubInstallation.installation_id == installation_id)
        .first()
    )
    if installation is None:
        installation = GitHubInstallation(
            installation_id=installation_id,
            organization_id=organization.id,
            account_id=int(owner_data["id"]),
            account_login=str(owner_data["login"]),
            target_type=str(owner_data.get("type") or "Organization"),
        )
        db.add(installation)
    installation.organization_id = organization.id
    installation.account_id = int(owner_data["id"])
    installation.account_login = str(owner_data["login"])
    installation.target_type = str(owner_data.get("type") or "Organization")
    if "repository_selection" in installation_data:
        installation.repository_selection = installation_data.get(
            "repository_selection"
        )
    if "permissions" in installation_data:
        installation.permissions = installation_data.get("permissions") or {}
    if "events" in installation_data:
        installation.events = installation_data.get("events") or []
    db.flush()
    return installation


def _get_or_create_repository(
    db: Session,
    repo_data: dict,
    installation_data: dict,
) -> Repository:
    github_repo_id = int(repo_data["id"])
    owner = repo_data.get("owner") or {}
    organization = _get_or_create_organization(db, owner)
    installation = _get_or_create_installation(
        db, installation_data, organization, owner
    )
    repository = (
        db.query(Repository)
        .filter(Repository.github_repo_id == github_repo_id)
        .first()
    )
    if repository is None:
        repository = Repository(
            github_repo_id=github_repo_id,
            organization_id=organization.id,
            github_installation_id=installation.id,
            name=str(repo_data["name"]),
            owner=str(owner["login"]),
            full_name=str(
                repo_data.get("full_name")
                or f"{owner['login']}/{repo_data['name']}"
            ),
        )
        db.add(repository)
    repository.organization_id = organization.id
    repository.github_installation_id = installation.id
    repository.name = str(repo_data["name"])
    repository.owner = str(owner["login"])
    repository.full_name = str(
        repo_data.get("full_name") or f"{owner['login']}/{repo_data['name']}"
    )
    repository.is_private = bool(repo_data.get("private"))
    repository.is_archived = bool(repo_data.get("archived"))
    db.flush()
    return repository


def _metrics_snapshot(metrics: PRMetrics) -> dict:
    return {
        "total_files": metrics.total_files,
        "total_additions": metrics.total_additions,
        "total_deletions": metrics.total_deletions,
        "has_tests": metrics.has_tests,
        "has_docs": metrics.has_docs,
        "language_breakdown": metrics.language_breakdown,
    }


def synchronize_webhook_delivery(db: Session, delivery: WebhookDelivery) -> str:
    """Fetch a complete snapshot, then atomically apply current GitHub state."""
    if not _is_supported(delivery):
        logger.info(
            "Delivery is outside the configured subscription: event=%s action=%s",
            delivery.event_type,
            delivery.action,
        )
        return "ignored"
    if delivery.event_type == "github_app_authorization":
        return _revoke_user_authorization(db, delivery)

    payload = delivery.payload
    installation_data = payload.get("installation") or {}
    installation_id = installation_data.get("id")
    repository_payload = payload.get("repository") or {}
    repo_full_name = repository_payload.get("full_name")
    pr_number = _pull_request_number(payload, delivery.event_type)
    if pr_number is None and delivery.event_type in {"check_run", "check_suite"}:
        return "ignored_unlinked_check"
    if not installation_id or not repo_full_name or not pr_number:
        raise IncompleteDeliveryError(
            IncompleteReason.MISSING_REQUIRED_FIELDS,
            "installation.id, repository.full_name, and pull_request.number are required",
        )

    repository_id = repository_payload.get("id")
    if not repository_id:
        raise IncompleteDeliveryError(
            IncompleteReason.MISSING_REQUIRED_FIELDS,
            "repository.id is required",
        )
    # Serialize fetch-and-apply for the same PR. A queued older delivery therefore
    # fetches GitHub only after any in-flight newer snapshot has committed.
    _lock_pull_request_resource(db, int(repository_id), int(pr_number))

    # No business rows are modified until every remote request has completed.
    token = get_installation_token(int(installation_id))
    known_installation = (
        db.query(GitHubInstallation)
        .filter(GitHubInstallation.installation_id == int(installation_id))
        .first()
    )
    known_repository = (
        db.query(Repository)
        .filter(Repository.github_repo_id == int(repository_id))
        .first()
    )
    with github_rate_limit_scope(
        installation_id=int(installation_id),
        organization_id=(
            known_installation.organization_id if known_installation else None
        ),
        repository_id=known_repository.id if known_repository else None,
    ):
        current_pr = get_pull_request(str(repo_full_name), int(pr_number), token)
        reviews = get_pr_reviews(str(repo_full_name), int(pr_number), token)
        file_snapshot = get_pr_files(str(repo_full_name), int(pr_number), token)

        user_data = current_pr.get("user") or {}
        repo_data = ((current_pr.get("base") or {}).get("repo")) or repository_payload
        owner_data = repo_data.get("owner") or {}
        head_data = current_pr.get("head") or {}
        required_values = (
            current_pr.get("id"),
            user_data.get("id"),
            user_data.get("login"),
            repo_data.get("id"),
            repo_data.get("name"),
            owner_data.get("id"),
            owner_data.get("login"),
            head_data.get("sha"),
        )
        if not all(required_values):
            raise IncompleteDeliveryError(
                IncompleteReason.MISSING_REQUIRED_FIELDS,
                "GitHub's current pull request response is missing identity or head fields",
            )

        github_pr_id = int(current_pr["id"])
        head_sha = str(head_data["sha"])
        check_snapshot = get_check_runs(str(repo_full_name), head_sha, token)
    remote_updated_at = _parse_github_datetime(current_pr.get("updated_at"))
    stored_pr = (
        db.query(PullRequest)
        .filter(PullRequest.github_pr_id == github_pr_id)
        .first()
    )
    eligibility_inputs_changed = stored_pr is not None and (
        stored_pr.state != _lifecycle_state(current_pr)
        or stored_pr.head_sha != head_sha
        or stored_pr.file_sync_complete == file_snapshot.limit_reached
    )
    if (
        stored_pr is not None
        and stored_pr.github_updated_at is not None
        and _comparable_utc(remote_updated_at)
        < _comparable_utc(stored_pr.github_updated_at)
    ):
        logger.warning(
            "Skipped stale GitHub snapshot for PR %s: remote=%s stored=%s",
            github_pr_id,
            remote_updated_at,
            stored_pr.github_updated_at,
        )
        return "stale_skipped"

    user = _get_or_create_user(db, user_data)
    repository = _get_or_create_repository(db, repo_data, installation_data)
    delivery.organization_id = repository.organization_id
    delivery.repository_pk = repository.id
    if stored_pr is None:
        stored_pr = PullRequest(
            github_pr_id=github_pr_id,
            title=current_pr.get("title") or "Untitled pull request",
            description=current_pr.get("body"),
            author_id=user.id,
            repo_id=repository.id,
            eligibility_state=EligibilityState.NOT_EVALUATED,
        )
        db.add(stored_pr)
        db.flush()

    stored_pr.title = current_pr.get("title") or "Untitled pull request"
    stored_pr.description = current_pr.get("body")
    stored_pr.github_pr_number = int(current_pr.get("number") or pr_number)
    stored_pr.author_id = user.id
    stored_pr.repo_id = repository.id
    stored_pr.state = _lifecycle_state(current_pr)
    stored_pr.review_state = _review_state(current_pr, reviews)
    stored_pr.additions = int(current_pr.get("additions") or 0)
    stored_pr.deletions = int(current_pr.get("deletions") or 0)
    stored_pr.changed_files = int(current_pr.get("changed_files") or 0)
    stored_pr.github_updated_at = remote_updated_at
    stored_pr.github_created_at = _parse_optional_github_datetime(
        current_pr.get("created_at")
    )
    stored_pr.merged_at = _parse_optional_github_datetime(
        current_pr.get("merged_at")
    )
    stored_pr.head_sha = head_sha
    stored_pr.last_processed_delivery_id = delivery.delivery_id
    if eligibility_inputs_changed:
        supersede_current_decision(db, stored_pr)

    if file_snapshot.limit_reached:
        stored_pr.file_sync_complete = False
        stored_pr.incomplete_reason = IncompleteReason.GITHUB_FILE_LIMIT.value
        stored_pr.latest_score_id = None
        db.query(PRMetrics).filter(PRMetrics.pr_id == stored_pr.id).delete(
            synchronize_session=False
        )
        record_incomplete_scoring_run(
            db,
            pull_request=stored_pr,
            delivery=delivery,
            reason=IncompleteReason.GITHUB_FILE_LIMIT.value,
        )
        record_audit_event(
            db,
            action="github.pr_sync_incomplete",
            resource_type="pull_request",
            organization_id=repository.organization_id,
            repository_id=repository.id,
            resource_id=stored_pr.id,
            event_metadata={
                "delivery_id": delivery.delivery_id,
                "reason": IncompleteReason.GITHUB_FILE_LIMIT.value,
            },
        )
        raise IncompleteDeliveryError(
            IncompleteReason.GITHUB_FILE_LIMIT,
            "GitHub's pull-request files endpoint reached its 3,000-file limit",
        )

    synchronize_pr_files(
        db,
        stored_pr.id,
        file_snapshot.files,
        commit=False,
    )
    metrics = analyze_pull_request(db, stored_pr.id, commit=False)
    scoring_input_complete = not check_snapshot.limit_reached
    check_error = check_snapshot.error
    if check_snapshot.limit_reached:
        check_error = "GitHub check-runs endpoint reached its 1,000-suite limit"
    run, score, _ = execute_scoring_run(
        db,
        pull_request=stored_pr,
        delivery=delivery,
        check_runs=check_snapshot.check_runs,
        check_runs_error=check_error,
        metrics_snapshot=_metrics_snapshot(metrics),
        input_complete=scoring_input_complete,
    )
    stored_pr.last_synchronized_head_sha = head_sha
    stored_pr.file_sync_complete = True
    stored_pr.incomplete_reason = None
    stored_pr.synchronized_at = datetime.utcnow()
    record_audit_event(
        db,
        action="github.pr_synchronized",
        resource_type="pull_request",
        organization_id=repository.organization_id,
        repository_id=repository.id,
        resource_id=stored_pr.id,
        event_metadata={
            "delivery_id": delivery.delivery_id,
            "head_sha": head_sha,
            "analysis_run_id": run.id,
            "score_id": score.id if score is not None else None,
            "score_authoritative": (
                score.is_authoritative if score is not None else False
            ),
        },
    )
    db.flush()
    return "synchronized"
