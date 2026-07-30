from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any
from urllib.parse import urlparse

import requests
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.security import encrypt_oauth_token
from app.models.authorization import (
    AuthorizationRole,
    GitHubInstallation,
    OAuthCredential,
    Organization,
    OrganizationMembership,
    RepositoryPermission,
)
from app.models.repository import Repository
from app.models.user import User


logger = logging.getLogger(__name__)
GITHUB_API = "https://api.github.com"


class GitHubIdentityError(RuntimeError):
    pass


def _github_headers(token: str) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }


def _response_json(response: requests.Response, operation: str) -> Any:
    if response.status_code >= 400:
        raise GitHubIdentityError(
            f"GitHub {operation} failed with status {response.status_code}"
        )
    return response.json()


def exchange_oauth_code(code: str, code_verifier: str) -> dict:
    if not settings.GITHUB_OAUTH_CLIENT_ID or not settings.GITHUB_OAUTH_CLIENT_SECRET:
        raise GitHubIdentityError("GitHub OAuth credentials are not configured")
    response = requests.post(
        "https://github.com/login/oauth/access_token",
        headers={"Accept": "application/json"},
        data={
            "client_id": settings.GITHUB_OAUTH_CLIENT_ID,
            "client_secret": settings.GITHUB_OAUTH_CLIENT_SECRET,
            "code": code,
            "redirect_uri": settings.GITHUB_OAUTH_REDIRECT_URI,
            "code_verifier": code_verifier,
        },
        timeout=15,
    )
    payload = _response_json(response, "OAuth exchange")
    if payload.get("error") or not payload.get("access_token"):
        raise GitHubIdentityError(
            f"GitHub rejected the OAuth exchange: {payload.get('error_description', 'missing token')}"
        )
    return payload


def _get_paginated(
    url: str, token: str, collection_key: str | None = None
) -> list[dict]:
    items: list[dict] = []
    next_url: str | None = url
    while next_url:
        parsed_next = urlparse(next_url)
        if (
            parsed_next.scheme != "https"
            or parsed_next.hostname != "api.github.com"
        ):
            raise GitHubIdentityError("GitHub returned an unsafe pagination URL")
        response = requests.get(
            next_url,
            headers=_github_headers(token),
            params={"per_page": 100} if "?" not in next_url else None,
            timeout=15,
        )
        response_payload = _response_json(response, "identity synchronization")
        page = (
            response_payload.get(collection_key)
            if collection_key and isinstance(response_payload, dict)
            else response_payload
        )
        if not isinstance(page, list):
            raise GitHubIdentityError("GitHub returned an invalid paginated response")
        items.extend(page)
        next_url = (response.links.get("next") or {}).get("url")
    return items


def _organization(db: Session, account: dict) -> Organization:
    github_id = int(account["id"])
    login = str(account["login"]).lower()
    organization = (
        db.query(Organization)
        .filter(
            (Organization.github_org_id == github_id)
            | (Organization.login == login)
        )
        .first()
    )
    if organization is None:
        organization = Organization(github_org_id=github_id, login=login)
        db.add(organization)
    organization.github_org_id = github_id
    organization.login = login
    organization.display_name = account.get("name") or account.get("login")
    organization.avatar_url = account.get("avatar_url")
    db.flush()
    return organization


def _upsert_user(db: Session, profile: dict, email: str | None) -> User:
    user = db.query(User).filter(User.github_id == int(profile["id"])).first()
    if user is None:
        user = User(github_id=int(profile["id"]), username=str(profile["login"]))
        db.add(user)
    user.username = str(profile["login"])
    user.avatar_url = profile.get("avatar_url")
    user.email = email or profile.get("email")
    user.display_name = profile.get("name")
    user.is_active = True
    user.last_login_at = datetime.utcnow()
    db.flush()
    return user


def _store_credential(
    db: Session, user: User, oauth_payload: dict, token: str
) -> None:
    ciphertext, key_id = encrypt_oauth_token(token)
    refresh_ciphertext = None
    refresh_token = oauth_payload.get("refresh_token")
    if refresh_token:
        refresh_ciphertext, refresh_key_id = encrypt_oauth_token(refresh_token)
        if refresh_key_id != key_id:
            raise RuntimeError("Encryption primary key changed during OAuth exchange")
    credential = (
        db.query(OAuthCredential)
        .filter(OAuthCredential.user_id == user.id, OAuthCredential.provider == "github")
        .first()
    )
    if credential is None:
        credential = OAuthCredential(
            user_id=user.id,
            provider="github",
            access_token_ciphertext=ciphertext,
            encryption_key_id=key_id,
        )
        db.add(credential)
    credential.access_token_ciphertext = ciphertext
    credential.refresh_token_ciphertext = refresh_ciphertext
    credential.encryption_key_id = key_id
    credential.scopes = [
        scope for scope in str(oauth_payload.get("scope") or "").split(",") if scope
    ]
    credential.expires_at = (
        datetime.now(timezone.utc)
        + timedelta(seconds=int(oauth_payload["expires_in"]))
        if oauth_payload.get("expires_in")
        else None
    )
    credential.refresh_token_expires_at = (
        datetime.now(timezone.utc)
        + timedelta(seconds=int(oauth_payload["refresh_token_expires_in"]))
        if oauth_payload.get("refresh_token_expires_in")
        else None
    )


def _repository_role(repo: dict) -> tuple[AuthorizationRole, str]:
    permissions = repo.get("permissions") or {}
    role_name = str(repo.get("role_name") or "").lower()
    if role_name == "admin" or permissions.get("admin"):
        return AuthorizationRole.ADMIN, "admin"
    if role_name == "maintain" or permissions.get("maintain"):
        return AuthorizationRole.MAINTAINER, "maintain"
    if role_name in {"write", "push"} or permissions.get("push"):
        return AuthorizationRole.CONTRIBUTOR, "push"
    if role_name == "triage" or permissions.get("triage"):
        return AuthorizationRole.REVIEWER, "triage"
    return AuthorizationRole.VIEWER, role_name or "pull"


def _sync_memberships(db: Session, user: User, token: str) -> None:
    memberships = _get_paginated(
        f"{GITHUB_API}/user/memberships/orgs?state=active", token
    )
    verified_ids: set[int] = set()
    verified_at = datetime.utcnow()
    for payload in memberships:
        organization_payload = payload.get("organization") or {}
        if not organization_payload.get("id") or not organization_payload.get("login"):
            continue
        organization = _organization(db, organization_payload)
        membership = (
            db.query(OrganizationMembership)
            .filter(
                OrganizationMembership.organization_id == organization.id,
                OrganizationMembership.user_id == user.id,
            )
            .first()
        )
        if membership is None:
            membership = OrganizationMembership(
                organization_id=organization.id,
                user_id=user.id,
                role=(
                    AuthorizationRole.OWNER
                    if payload.get("role") == "admin"
                    else AuthorizationRole.VIEWER
                ),
            )
            db.add(membership)
        if payload.get("role") == "admin":
            membership.role = AuthorizationRole.OWNER
        elif membership.role == AuthorizationRole.OWNER:
            membership.role = AuthorizationRole.VIEWER
        membership.github_role = payload.get("role")
        membership.is_active = payload.get("state") == "active"
        membership.github_verified = True
        membership.github_verified_at = verified_at
        verified_ids.add(organization.id)

    db.query(OrganizationMembership).filter(
        OrganizationMembership.user_id == user.id,
        OrganizationMembership.github_verified.is_(True),
        ~OrganizationMembership.organization_id.in_(verified_ids or {-1}),
    ).update(
        {
            OrganizationMembership.is_active: False,
            OrganizationMembership.github_verified_at: verified_at,
        },
        synchronize_session=False,
    )


def _sync_installations_and_repositories(db: Session, user: User, token: str) -> None:
    installations = _get_paginated(
        f"{GITHUB_API}/user/installations", token, "installations"
    )
    visible_repository_ids: set[int] = set()
    verified_at = datetime.utcnow()

    for payload in installations:
        account = payload.get("account") or {}
        if not account.get("id") or not account.get("login"):
            continue
        organization = _organization(db, account)
        installation_id = int(payload["id"])
        installation = (
            db.query(GitHubInstallation)
            .filter(GitHubInstallation.installation_id == installation_id)
            .first()
        )
        if installation is None:
            installation = GitHubInstallation(
                installation_id=installation_id,
                organization_id=organization.id,
                account_id=int(account["id"]),
                account_login=str(account["login"]),
                target_type=str(payload.get("target_type") or account.get("type") or "Organization"),
            )
            db.add(installation)
        installation.organization_id = organization.id
        installation.account_id = int(account["id"])
        installation.account_login = str(account["login"])
        installation.target_type = str(
            payload.get("target_type") or account.get("type") or "Organization"
        )
        installation.repository_selection = payload.get("repository_selection")
        installation.permissions = payload.get("permissions") or {}
        installation.events = payload.get("events") or []
        installation.suspended_at = payload.get("suspended_at")
        db.flush()

        repositories = _get_paginated(
            f"{GITHUB_API}/user/installations/{installation_id}/repositories",
            token,
            "repositories",
        )
        for repo_payload in repositories:
            owner = repo_payload.get("owner") or account
            repo_organization = _organization(db, owner)
            github_repo_id = int(repo_payload["id"])
            repository = (
                db.query(Repository)
                .filter(Repository.github_repo_id == github_repo_id)
                .first()
            )
            if repository is None:
                repository = Repository(
                    github_repo_id=github_repo_id,
                    organization_id=repo_organization.id,
                    github_installation_id=installation.id,
                    name=str(repo_payload["name"]),
                    owner=str(owner["login"]),
                    full_name=str(repo_payload["full_name"]),
                )
                db.add(repository)
            repository.organization_id = repo_organization.id
            repository.github_installation_id = installation.id
            repository.name = str(repo_payload["name"])
            repository.owner = str(owner["login"])
            repository.full_name = str(repo_payload["full_name"])
            repository.is_private = bool(repo_payload.get("private"))
            repository.is_archived = bool(repo_payload.get("archived"))
            db.flush()

            role, github_permission = _repository_role(repo_payload)
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
                    source="github",
                )
                db.add(permission)
            permission.role = role
            permission.source = "github"
            permission.github_permission = github_permission
            permission.github_verified_at = verified_at
            visible_repository_ids.add(repository.id)

    db.query(RepositoryPermission).filter(
        RepositoryPermission.user_id == user.id,
        RepositoryPermission.source == "github",
        ~RepositoryPermission.repository_id.in_(visible_repository_ids or {-1}),
    ).delete(synchronize_session=False)


def synchronize_github_identity(db: Session, oauth_payload: dict) -> User:
    token = str(oauth_payload["access_token"])
    profile_response = requests.get(
        f"{GITHUB_API}/user", headers=_github_headers(token), timeout=15
    )
    profile = _response_json(profile_response, "user profile")

    email = profile.get("email")
    if not email:
        email_response = requests.get(
            f"{GITHUB_API}/user/emails", headers=_github_headers(token), timeout=15
        )
        if email_response.status_code < 400:
            emails = email_response.json()
            primary = next(
                (
                    item.get("email")
                    for item in emails
                    if item.get("primary") and item.get("verified")
                ),
                None,
            )
            email = primary

    user = _upsert_user(db, profile, email)
    _store_credential(db, user, oauth_payload, token)
    _sync_memberships(db, user, token)
    _sync_installations_and_repositories(db, user, token)
    return user
