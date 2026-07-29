from __future__ import annotations

import hashlib
from dataclasses import dataclass

from sqlalchemy.orm import Session

from app.models.authorization import (
    AuthorizationRole,
    OrganizationMembership,
    RepositoryPermission,
)
from app.models.demo import DemoPersona
from app.models.pull_request import PullRequest
from app.models.repository import Repository
from app.models.user import User


DEMO_PERSONA_ROLES = {
    "owner": AuthorizationRole.OWNER,
    "reviewer": AuthorizationRole.REVIEWER,
    "finance": AuthorizationRole.ADMIN,
    "contributor": AuthorizationRole.CONTRIBUTOR,
}
DEMO_PERSONA_LABELS = {
    "owner": "Demo organization owner",
    "reviewer": "Demo human reviewer",
    "finance": "Demo finance approver",
    "contributor": "GitHub pull-request author",
}


class DemoBootstrapError(RuntimeError):
    pass


@dataclass(frozen=True)
class DemoWorkspace:
    workspace: str
    repository: str
    pull_request_id: int
    pull_request_number: int
    personas: dict[str, str]


def demo_mode_enabled() -> bool:
    from app.core.config import settings

    return settings.DEMO_MODE and settings.APP_ENV.lower() != "production"


def _synthetic_github_id(workspace: str, persona: str) -> int:
    digest = hashlib.blake2b(
        f"github-bounty-demo:{workspace}:{persona}".encode("utf-8"),
        digest_size=8,
    ).digest()
    # Real GitHub database IDs are positive. Negative values make synthetic
    # showcase identities unambiguous and collision-resistant.
    return -max(1, int.from_bytes(digest, "big") & ((1 << 63) - 1))


def _synthetic_user(db: Session, workspace: str, persona: str) -> User:
    github_id = _synthetic_github_id(workspace, persona)
    user = db.query(User).filter(User.github_id == github_id).first()
    username = f"demo-{workspace}-{persona}"[:255]
    if user is None:
        user = User(github_id=github_id, username=username)
        db.add(user)
    user.username = username
    user.display_name = DEMO_PERSONA_LABELS[persona]
    user.is_active = True
    db.flush()
    return user


def _upsert_persona(
    db: Session,
    *,
    repository: Repository,
    persona: str,
    user: User,
) -> None:
    role = DEMO_PERSONA_ROLES[persona]
    membership = (
        db.query(OrganizationMembership)
        .filter(
            OrganizationMembership.organization_id == repository.organization_id,
            OrganizationMembership.user_id == user.id,
        )
        .first()
    )
    if membership is None:
        membership = OrganizationMembership(
            organization_id=repository.organization_id,
            user_id=user.id,
            role=role,
        )
        db.add(membership)
    membership.role = role
    membership.github_role = "demo"
    membership.is_active = True
    membership.github_verified = True

    permission = (
        db.query(RepositoryPermission)
        .filter(
            RepositoryPermission.repository_id == repository.id,
            RepositoryPermission.user_id == user.id,
        )
        .first()
    )
    if permission is None:
        permission = RepositoryPermission(
            repository_id=repository.id,
            user_id=user.id,
            role=role,
            source="demo",
        )
        db.add(permission)
    permission.role = role
    permission.source = "demo"
    permission.github_permission = "demo"

    mapping = (
        db.query(DemoPersona)
        .filter(
            DemoPersona.organization_id == repository.organization_id,
            DemoPersona.persona == persona,
        )
        .first()
    )
    if mapping is None:
        mapping = DemoPersona(
            organization_id=repository.organization_id,
            user_id=user.id,
            persona=persona,
            label=DEMO_PERSONA_LABELS[persona],
        )
        db.add(mapping)
    elif mapping.user_id != user.id:
        old_permission = (
            db.query(RepositoryPermission)
            .filter(
                RepositoryPermission.repository_id == repository.id,
                RepositoryPermission.user_id == mapping.user_id,
                RepositoryPermission.source == "demo",
            )
            .first()
        )
        if old_permission is not None:
            db.delete(old_permission)
        old_membership = (
            db.query(OrganizationMembership)
            .filter(
                OrganizationMembership.organization_id
                == repository.organization_id,
                OrganizationMembership.user_id == mapping.user_id,
                OrganizationMembership.github_role == "demo",
            )
            .first()
        )
        if old_membership is not None:
            db.delete(old_membership)
        db.flush()
    mapping.user_id = user.id
    mapping.label = DEMO_PERSONA_LABELS[persona]
    db.flush()


def bootstrap_demo_workspace(
    db: Session,
    *,
    repository_full_name: str,
    pull_request_number: int,
) -> DemoWorkspace:
    repository = (
        db.query(Repository)
        .filter(Repository.full_name == repository_full_name)
        .first()
    )
    if repository is None:
        raise DemoBootstrapError(
            "Repository has not been synchronized. Install the GitHub App and "
            "sign in with GitHub or deliver a pull_request webhook first."
        )
    pull_request = (
        db.query(PullRequest)
        .filter(
            PullRequest.repo_id == repository.id,
            PullRequest.github_pr_number == pull_request_number,
        )
        .first()
    )
    if pull_request is None:
        raise DemoBootstrapError(
            "Pull request has not been ingested yet. Open the test PR, wait for "
            "the worker, then rerun this command."
        )

    workspace = repository.organization.login
    users = {
        persona: (
            pull_request.author
            if persona == "contributor"
            else _synthetic_user(db, workspace, persona)
        )
        for persona in DEMO_PERSONA_ROLES
    }
    for persona, user in users.items():
        _upsert_persona(
            db,
            repository=repository,
            persona=persona,
            user=user,
        )
    db.flush()
    return DemoWorkspace(
        workspace=workspace,
        repository=repository.full_name,
        pull_request_id=pull_request.id,
        pull_request_number=pull_request_number,
        personas={key: value.username for key, value in users.items()},
    )


def ensure_demo_personas_for_organization(
    db: Session, workspace_login: str
) -> bool:
    from app.models.authorization import Organization

    target_slug = workspace_login.strip().lower()
    organization = (
        db.query(Organization)
        .filter(Organization.login == target_slug)
        .first()
    )
    if organization is None:
        orgs = db.query(Organization).all()
        if len(orgs) == 1:
            organization = orgs[0]
        else:
            return False

    repositories = (
        db.query(Repository)
        .filter(Repository.organization_id == organization.id)
        .all()
    )
    if not repositories:
        return False

    primary_repo = repositories[0]
    workspace = organization.login
    for persona in DEMO_PERSONA_ROLES:
        user = _synthetic_user(db, workspace, persona)
        _upsert_persona(
            db,
            repository=primary_repo,
            persona=persona,
            user=user,
        )
    db.flush()
    return True
