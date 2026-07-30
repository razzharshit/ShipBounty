from __future__ import annotations

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.security import decode_session_token
from app.db.session import get_db
from app.models.authorization import (
    AuthorizationRole,
    OrganizationMembership,
    RepositoryPermission,
)
from app.models.repository import Repository
from app.models.user import User
from app.services.audit_service import record_audit_event


bearer = HTTPBearer(auto_error=False)
ROLE_WEIGHT = {
    AuthorizationRole.VIEWER: 10,
    AuthorizationRole.CONTRIBUTOR: 20,
    AuthorizationRole.REVIEWER: 30,
    AuthorizationRole.MAINTAINER: 40,
    AuthorizationRole.ADMIN: 50,
    AuthorizationRole.OWNER: 60,
}


def get_current_user(
    request: Request,
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer),
    db: Session = Depends(get_db),
) -> User:
    token = (
        credentials.credentials
        if credentials and credentials.scheme.lower() == "bearer"
        else request.cookies.get(settings.SESSION_COOKIE_NAME)
    )
    if not token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required",
            headers={"WWW-Authenticate": "Bearer"},
        )
    user_id, session_version = decode_session_token(token)
    user = db.get(User, user_id)
    if (
        user is None
        or not user.is_active
        or user.session_version != session_version
    ):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Session has been revoked or the user is inactive",
        )
    return user


def effective_repository_role(
    db: Session, user_id: int, repository: Repository
) -> AuthorizationRole | None:
    membership = (
        db.query(OrganizationMembership)
        .filter(
            OrganizationMembership.organization_id == repository.organization_id,
            OrganizationMembership.user_id == user_id,
            OrganizationMembership.is_active.is_(True),
            OrganizationMembership.github_verified.is_(True),
        )
        .first()
    )
    direct = (
        db.query(RepositoryPermission)
        .filter(
            RepositoryPermission.repository_id == repository.id,
            RepositoryPermission.user_id == user_id,
        )
        .first()
    )
    roles = [direct.role] if direct else []
    # GitHub organization owners can administer every repository. Other members
    # need an explicit repository permission synchronized from the installation.
    if membership and membership.role in {
        AuthorizationRole.OWNER,
        AuthorizationRole.ADMIN,
    }:
        roles.append(membership.role)
    return max(roles, key=ROLE_WEIGHT.get) if roles else None


def authorize_repository(
    db: Session,
    user: User,
    repository: Repository,
    required_role: AuthorizationRole,
    request: Request | None = None,
) -> AuthorizationRole:
    actual_role = effective_repository_role(db, user.id, repository)
    if actual_role is None or ROLE_WEIGHT[actual_role] < ROLE_WEIGHT[required_role]:
        record_audit_event(
            db,
            action="authorization.denied",
            resource_type="repository",
            actor_user_id=user.id,
            organization_id=repository.organization_id,
            repository_id=repository.id,
            resource_id=repository.id,
            event_metadata={"required_role": required_role.value},
            request=request,
        )
        db.commit()
        # Do not reveal whether an inaccessible repository exists.
        raise HTTPException(status_code=404, detail="Repository not found")
    return actual_role
