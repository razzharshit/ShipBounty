from __future__ import annotations

import pytest
from fastapi import HTTPException

from app.api.authz import authorize_repository, effective_repository_role
from app.core.config import settings
from app.core.security import (
    create_session_token,
    decode_session_token,
    decrypt_oauth_token,
    encrypt_oauth_token,
)
from app.models.authorization import (
    AuditLog,
    AuthorizationRole,
    Organization,
    OrganizationMembership,
    OAuthCredential,
    RepositoryPermission,
)
from app.models.repository import Repository
from app.models.user import User
from app.services.pr_service import list_pull_requests
from app.models.pull_request import PullRequest


def _tenant(db, suffix: str, *, membership_role=None, repository_role=None):
    identity_offset = sum((index + 1) * ord(char) for index, char in enumerate(suffix))
    user = User(github_id=1000 + identity_offset, username=f"user-{suffix}")
    organization = Organization(
        github_org_id=2000 + identity_offset, login=f"org-{suffix}"
    )
    db.add_all([user, organization])
    db.flush()
    repository = Repository(
        github_repo_id=3000 + identity_offset,
        organization_id=organization.id,
        name=f"repo-{suffix}",
        owner=organization.login,
        full_name=f"{organization.login}/repo-{suffix}",
    )
    db.add(repository)
    db.flush()
    if membership_role:
        db.add(
            OrganizationMembership(
                organization_id=organization.id,
                user_id=user.id,
                role=membership_role,
                github_role="member",
                is_active=True,
                github_verified=True,
            )
        )
    if repository_role:
        db.add(
            RepositoryPermission(
                repository_id=repository.id,
                user_id=user.id,
                role=repository_role,
                source="github",
            )
        )
    db.flush()
    return user, organization, repository


def test_session_key_rotation_and_encrypted_tokens(monkeypatch):
    from cryptography.fernet import Fernet

    old_jwt_keys = settings.AUTH_JWT_KEYS
    old_encryption_keys = settings.TOKEN_ENCRYPTION_KEYS
    old_ttl = settings.AUTH_SESSION_TTL_SECONDS
    try:
        settings.AUTH_JWT_KEYS = "current:current-secret-with-sufficient-entropy"
        settings.AUTH_SESSION_TTL_SECONDS = 60
        token = create_session_token(42, 3)
        assert decode_session_token(token) == (42, 3)

        key = Fernet.generate_key().decode()
        settings.TOKEN_ENCRYPTION_KEYS = f"current:{key}"
        ciphertext, key_id = encrypt_oauth_token("github-secret-token")
        assert "github-secret-token" not in ciphertext
        assert decrypt_oauth_token(ciphertext, key_id) == "github-secret-token"
    finally:
        settings.AUTH_JWT_KEYS = old_jwt_keys
        settings.TOKEN_ENCRYPTION_KEYS = old_encryption_keys
        settings.AUTH_SESSION_TTL_SECONDS = old_ttl


def test_repository_permission_is_required_for_regular_org_member(session_factory):
    db = session_factory()
    user, _, repository = _tenant(
        db, "member", membership_role=AuthorizationRole.VIEWER
    )
    assert effective_repository_role(db, user.id, repository) is None
    with pytest.raises(HTTPException) as exc:
        authorize_repository(
            db, user, repository, AuthorizationRole.VIEWER
        )
    assert exc.value.status_code == 404
    assert db.query(AuditLog).filter(AuditLog.action == "authorization.denied").count() == 1
    db.close()


def test_owner_and_direct_repository_roles_are_enforced(session_factory):
    db = session_factory()
    owner, _, owner_repo = _tenant(
        db, "owner", membership_role=AuthorizationRole.OWNER
    )
    contributor, _, contributor_repo = _tenant(
        db, "contrib", repository_role=AuthorizationRole.CONTRIBUTOR
    )
    assert (
        authorize_repository(db, owner, owner_repo, AuthorizationRole.ADMIN)
        == AuthorizationRole.OWNER
    )
    assert (
        authorize_repository(
            db, contributor, contributor_repo, AuthorizationRole.VIEWER
        )
        == AuthorizationRole.CONTRIBUTOR
    )
    with pytest.raises(HTTPException):
        authorize_repository(
            db, contributor, contributor_repo, AuthorizationRole.REVIEWER
        )
    db.close()


def test_pull_request_collections_do_not_cross_tenant_boundaries(session_factory):
    db = session_factory()
    user, _, allowed_repo = _tenant(
        db, "allowed", repository_role=AuthorizationRole.VIEWER
    )
    other_user, _, hidden_repo = _tenant(
        db, "hiddenx", repository_role=AuthorizationRole.VIEWER
    )
    db.add_all(
        [
            PullRequest(
                github_pr_id=901,
                title="visible",
                author_id=user.id,
                repo_id=allowed_repo.id,
            ),
            PullRequest(
                github_pr_id=902,
                title="hidden",
                author_id=other_user.id,
                repo_id=hidden_repo.id,
            ),
        ]
    )
    db.commit()
    assert [item.title for item in list_pull_requests(db, user.id)] == ["visible"]
    db.close()


def test_installation_tokens_have_no_persistent_model_field():
    from app.models.authorization import GitHubInstallation

    assert "access_token" not in GitHubInstallation.__table__.columns
    assert "token" not in GitHubInstallation.__table__.columns


def test_github_identity_sync_verifies_membership_and_repository_access(
    monkeypatch, session_factory
):
    from cryptography.fernet import Fernet
    from app.services import identity_service

    class FakeResponse:
        def __init__(self, payload):
            self.status_code = 200
            self._payload = payload
            self.links = {}

        def json(self):
            return self._payload

    payloads = {
        f"{identity_service.GITHUB_API}/user": {
            "id": 501,
            "login": "octocat",
            "email": "octocat@example.com",
            "name": "Octo Cat",
        },
        f"{identity_service.GITHUB_API}/user/memberships/orgs?state=active": [
            {
                "state": "active",
                "role": "admin",
                "organization": {"id": 601, "login": "acme"},
            }
        ],
        f"{identity_service.GITHUB_API}/user/installations": {
            "total_count": 1,
            "installations": [
                {
                    "id": 701,
                    "account": {
                        "id": 601,
                        "login": "acme",
                        "type": "Organization",
                    },
                    "target_type": "Organization",
                    "repository_selection": "selected",
                    "permissions": {"pull_requests": "read"},
                    "events": ["pull_request"],
                }
            ],
        },
        f"{identity_service.GITHUB_API}/user/installations/701/repositories": {
            "total_count": 1,
            "repositories": [
                {
                    "id": 801,
                    "name": "widgets",
                    "full_name": "acme/widgets",
                    "owner": {
                        "id": 601,
                        "login": "acme",
                        "type": "Organization",
                    },
                    "private": True,
                    "archived": False,
                    "permissions": {"pull": True, "triage": True},
                    "role_name": "triage",
                }
            ],
        },
    }

    def fake_get(url, **kwargs):
        return FakeResponse(payloads[url])

    old_keys = settings.TOKEN_ENCRYPTION_KEYS
    settings.TOKEN_ENCRYPTION_KEYS = f"v1:{Fernet.generate_key().decode()}"
    monkeypatch.setattr(identity_service.requests, "get", fake_get)
    db = session_factory()
    try:
        user = identity_service.synchronize_github_identity(
            db,
            {
                "access_token": "ghu_plaintext_must_not_be_stored",
                "refresh_token": "ghr_refresh_plaintext",
                "expires_in": 28800,
                "refresh_token_expires_in": 15897600,
                "scope": "",
            },
        )
        db.commit()
        membership = db.query(OrganizationMembership).one()
        permission = db.query(RepositoryPermission).one()
        credential = db.query(OAuthCredential).one()
        assert membership.user_id == user.id
        assert membership.github_verified is True
        assert membership.role == AuthorizationRole.OWNER
        assert permission.role == AuthorizationRole.REVIEWER
        assert credential.encryption_key_id == "v1"
        assert "ghu_plaintext" not in credential.access_token_ciphertext
        assert "ghr_refresh" not in credential.refresh_token_ciphertext
    finally:
        db.close()
        settings.TOKEN_ENCRYPTION_KEYS = old_keys
