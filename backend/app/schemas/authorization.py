from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict

from app.models.authorization import AuthorizationRole


class AuthenticatedUserRead(BaseModel):
    id: int
    github_id: int
    username: str
    avatar_url: str | None
    email: str | None
    display_name: str | None

    model_config = ConfigDict(from_attributes=True)


class OrganizationRead(BaseModel):
    id: int
    github_org_id: int | None
    login: str
    display_name: str | None
    avatar_url: str | None
    role: AuthorizationRole
    github_verified: bool


class MembershipRoleUpdate(BaseModel):
    role: AuthorizationRole


class OrganizationMemberRead(BaseModel):
    membership_id: int
    user_id: int
    username: str
    display_name: str | None
    avatar_url: str | None
    role: AuthorizationRole
    github_verified: bool
    is_active: bool
    created_at: datetime


class RepositoryAccessRead(BaseModel):
    id: int
    github_repo_id: int
    organization_id: int
    name: str
    owner: str
    full_name: str
    is_private: bool
    is_archived: bool
    role: AuthorizationRole


class AuditLogRead(BaseModel):
    id: int
    organization_id: int | None
    actor_user_id: int | None
    repository_id: int | None
    action: str
    resource_type: str
    resource_id: str | None
    event_metadata: dict
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)
