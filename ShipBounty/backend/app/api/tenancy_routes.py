from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session

from app.analysis.policy import policy_for_repository, policy_hash, validate_policy
from app.api.authz import (
    ROLE_WEIGHT,
    authorize_repository,
    effective_repository_role,
    get_current_user,
)
from app.db.session import get_db
from app.models.authorization import (
    AuditLog,
    AuthorizationRole,
    Organization,
    OrganizationMembership,
    RepositoryPermission,
)
from app.models.repository import Repository
from app.models.score import ScoreVersion
from app.models.user import User
from app.schemas.authorization import (
    AuditLogRead,
    MembershipRoleUpdate,
    OrganizationMemberRead,
    OrganizationRead,
    RepositoryAccessRead,
)
from app.schemas.score import ScoringPolicyRead, ScoringPolicyUpdate
from app.services.audit_service import record_audit_event


router = APIRouter(tags=["tenancy"])


def _membership(
    db: Session, organization_id: int, user_id: int
) -> OrganizationMembership | None:
    return (
        db.query(OrganizationMembership)
        .filter(
            OrganizationMembership.organization_id == organization_id,
            OrganizationMembership.user_id == user_id,
            OrganizationMembership.is_active.is_(True),
            OrganizationMembership.github_verified.is_(True),
        )
        .first()
    )


def _require_org_admin(
    db: Session, organization_id: int, user: User
) -> OrganizationMembership:
    membership = _membership(db, organization_id, user.id)
    if not membership or membership.role not in {
        AuthorizationRole.OWNER,
        AuthorizationRole.ADMIN,
    }:
        raise HTTPException(status_code=404, detail="Organization not found")
    return membership


@router.get("/organizations", response_model=list[OrganizationRead])
def list_organizations(
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> list[OrganizationRead]:
    membership_rows = (
        db.query(Organization, OrganizationMembership)
        .join(
            OrganizationMembership,
            OrganizationMembership.organization_id == Organization.id,
        )
        .filter(
            OrganizationMembership.user_id == user.id,
            OrganizationMembership.is_active.is_(True),
            OrganizationMembership.github_verified.is_(True),
        )
        .order_by(Organization.login)
        .all()
    )
    organizations_by_id = {
        organization.id: OrganizationRead(
            id=organization.id,
            github_org_id=organization.github_org_id,
            login=organization.login,
            display_name=organization.display_name,
            avatar_url=organization.avatar_url,
            role=membership.role,
            github_verified=membership.github_verified,
        )
        for organization, membership in membership_rows
    }
    permission_rows = (
        db.query(Organization, RepositoryPermission)
        .join(Repository, Repository.organization_id == Organization.id)
        .join(
            RepositoryPermission,
            RepositoryPermission.repository_id == Repository.id,
        )
        .filter(RepositoryPermission.user_id == user.id)
        .all()
    )
    for organization, permission in permission_rows:
        existing = organizations_by_id.get(organization.id)
        if existing and ROLE_WEIGHT[existing.role] >= ROLE_WEIGHT[permission.role]:
            continue
        organizations_by_id[organization.id] = OrganizationRead(
            id=organization.id,
            github_org_id=organization.github_org_id,
            login=organization.login,
            display_name=organization.display_name,
            avatar_url=organization.avatar_url,
            role=permission.role,
            github_verified=bool(existing and existing.github_verified),
        )
    return sorted(
        organizations_by_id.values(),
        key=lambda item: item.login,
    )


@router.get(
    "/organizations/{organization_id}/repositories",
    response_model=list[RepositoryAccessRead],
)
def list_organization_repositories(
    organization_id: int,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> list[RepositoryAccessRead]:
    organization = db.get(Organization, organization_id)
    if organization is None:
        raise HTTPException(status_code=404, detail="Organization not found")
    repositories = (
        db.query(Repository)
        .filter(Repository.organization_id == organization_id)
        .order_by(Repository.full_name)
        .all()
    )
    result: list[RepositoryAccessRead] = []
    for repository in repositories:
        role = effective_repository_role(db, user.id, repository)
        if role:
            result.append(
                RepositoryAccessRead(
                    id=repository.id,
                    github_repo_id=repository.github_repo_id,
                    organization_id=repository.organization_id,
                    name=repository.name,
                    owner=repository.owner,
                    full_name=repository.full_name,
                    is_private=repository.is_private,
                    is_archived=repository.is_archived,
                    role=role,
                )
            )
    if not result and _membership(db, organization_id, user.id) is None:
        raise HTTPException(status_code=404, detail="Organization not found")
    return result


@router.get(
    "/organizations/{organization_id}/members",
    response_model=list[OrganizationMemberRead],
)
def list_organization_members(
    organization_id: int,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> list[OrganizationMemberRead]:
    _require_org_admin(db, organization_id, user)
    rows = (
        db.query(OrganizationMembership, User)
        .join(User, User.id == OrganizationMembership.user_id)
        .filter(OrganizationMembership.organization_id == organization_id)
        .order_by(OrganizationMembership.role.desc(), User.username)
        .all()
    )
    return [
        OrganizationMemberRead(
            membership_id=membership.id,
            user_id=member.id,
            username=member.username,
            display_name=member.display_name,
            avatar_url=member.avatar_url,
            role=membership.role,
            github_verified=membership.github_verified,
            is_active=membership.is_active,
            created_at=membership.created_at,
        )
        for membership, member in rows
    ]


@router.patch(
    "/organizations/{organization_id}/members/{member_user_id}",
    response_model=OrganizationRead,
)
def update_member_role(
    organization_id: int,
    member_user_id: int,
    payload: MembershipRoleUpdate,
    request: Request,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> OrganizationRead:
    actor_membership = _require_org_admin(db, organization_id, user)
    if (
        actor_membership.role != AuthorizationRole.OWNER
        and payload.role in {AuthorizationRole.OWNER, AuthorizationRole.ADMIN}
    ):
        raise HTTPException(status_code=403, detail="Only owners can grant this role")
    target = _membership(db, organization_id, member_user_id)
    if target is None:
        raise HTTPException(status_code=404, detail="Member not found")
    if (
        actor_membership.role != AuthorizationRole.OWNER
        and ROLE_WEIGHT[target.role] >= ROLE_WEIGHT[actor_membership.role]
    ):
        raise HTTPException(
            status_code=403,
            detail="Administrators cannot change an owner or peer administrator",
        )
    if target.role == AuthorizationRole.OWNER and payload.role != AuthorizationRole.OWNER:
        owner_count = (
            db.query(OrganizationMembership)
            .filter(
                OrganizationMembership.organization_id == organization_id,
                OrganizationMembership.role == AuthorizationRole.OWNER,
                OrganizationMembership.is_active.is_(True),
            )
            .count()
        )
        if owner_count <= 1:
            raise HTTPException(status_code=409, detail="Cannot demote the last owner")
    old_role = target.role
    target.role = payload.role
    record_audit_event(
        db,
        action="organization.member_role_changed",
        resource_type="organization_membership",
        actor_user_id=user.id,
        organization_id=organization_id,
        resource_id=target.id,
        event_metadata={
            "member_user_id": member_user_id,
            "old_role": old_role.value,
            "new_role": payload.role.value,
        },
        request=request,
    )
    db.commit()
    organization = db.get(Organization, organization_id)
    return OrganizationRead(
        id=organization.id,
        github_org_id=organization.github_org_id,
        login=organization.login,
        display_name=organization.display_name,
        avatar_url=organization.avatar_url,
        role=target.role,
        github_verified=target.github_verified,
    )


@router.get(
    "/organizations/{organization_id}/audit-logs",
    response_model=list[AuditLogRead],
)
def list_audit_logs(
    organization_id: int,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> list[AuditLog]:
    _require_org_admin(db, organization_id, user)
    return (
        db.query(AuditLog)
        .filter(AuditLog.organization_id == organization_id)
        .order_by(AuditLog.created_at.desc())
        .limit(250)
        .all()
    )


@router.get(
    "/repositories/{repository_id}/scoring-policy",
    response_model=ScoringPolicyRead,
)
def get_repository_scoring_policy(
    repository_id: int,
    request: Request,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> ScoringPolicyRead:
    repository = db.get(Repository, repository_id)
    if repository is None:
        raise HTTPException(status_code=404, detail="Repository not found")
    authorize_repository(
        db, user, repository, AuthorizationRole.VIEWER, request
    )
    policy = policy_for_repository(db, repository)
    db.commit()
    return policy


@router.put(
    "/repositories/{repository_id}/scoring-policy",
    response_model=ScoringPolicyRead,
)
def update_repository_scoring_policy(
    repository_id: int,
    payload: ScoringPolicyUpdate,
    request: Request,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> ScoringPolicyRead:
    repository = db.get(Repository, repository_id)
    if repository is None:
        raise HTTPException(status_code=404, detail="Repository not found")
    authorize_repository(
        db, user, repository, AuthorizationRole.MAINTAINER, request
    )
    try:
        validate_policy(
            payload.weights,
            payload.analyzer_weights,
            payload.required_analyzers,
            payload.settings,
        )
    except (TypeError, ValueError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    digest = policy_hash(
        payload.weights,
        payload.analyzer_weights,
        payload.required_analyzers,
        payload.settings,
    )
    policy = (
        db.query(ScoreVersion)
        .filter(ScoreVersion.policy_hash == digest)
        .first()
    )
    if policy is None:
        policy = ScoreVersion(
            version=f"repo-{repository.id}-{digest[:16]}",
            name=payload.name,
            description=payload.description,
            weights=payload.weights,
            analyzer_weights=payload.analyzer_weights,
            required_analyzers=payload.required_analyzers,
            settings=payload.settings,
            policy_hash=digest,
            created_by_user_id=user.id,
        )
        db.add(policy)
        db.flush()
    previous_policy_id = repository.scoring_policy_id
    repository.scoring_policy_id = policy.id
    record_audit_event(
        db,
        action="repository.scoring_policy_changed",
        resource_type="repository",
        actor_user_id=user.id,
        organization_id=repository.organization_id,
        repository_id=repository.id,
        resource_id=repository.id,
        event_metadata={
            "previous_policy_id": previous_policy_id,
            "new_policy_id": policy.id,
            "policy_hash": policy.policy_hash,
        },
        request=request,
    )
    db.commit()
    return policy
