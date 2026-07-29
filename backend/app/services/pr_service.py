from __future__ import annotations

from sqlalchemy import and_, or_
from sqlalchemy.orm import Session, joinedload

from app.models.authorization import (
    AuthorizationRole,
    OrganizationMembership,
    RepositoryPermission,
)
from app.models.pull_request import PullRequest
from app.models.repository import Repository
from app.models.user import User
from app.schemas.pull_request import PullRequestCreate


def _load_pr_with_relations(db: Session, pr_id: int) -> PullRequest:
    return (
        db.query(PullRequest)
        .options(joinedload(PullRequest.author), joinedload(PullRequest.repository))
        .filter(PullRequest.id == pr_id)
        .one()
    )


def list_pull_requests(db: Session, user_id: int) -> list[PullRequest]:
    return (
        db.query(PullRequest)
        .join(Repository, PullRequest.repo_id == Repository.id)
        .outerjoin(
            RepositoryPermission,
            and_(
                RepositoryPermission.repository_id == Repository.id,
                RepositoryPermission.user_id == user_id,
            ),
        )
        .outerjoin(
            OrganizationMembership,
            and_(
                OrganizationMembership.organization_id == Repository.organization_id,
                OrganizationMembership.user_id == user_id,
                OrganizationMembership.is_active.is_(True),
                OrganizationMembership.github_verified.is_(True),
                OrganizationMembership.role.in_(
                    [AuthorizationRole.OWNER, AuthorizationRole.ADMIN]
                ),
            ),
        )
        .filter(
            or_(
                RepositoryPermission.id.is_not(None),
                OrganizationMembership.id.is_not(None),
            )
        )
        .options(joinedload(PullRequest.author), joinedload(PullRequest.repository))
        .order_by(PullRequest.created_at.desc())
        .all()
    )


def get_pull_request_by_github_id(db: Session, github_pr_id: int) -> PullRequest | None:
    return db.query(PullRequest).filter(PullRequest.github_pr_id == github_pr_id).first()


def update_pull_request(db: Session, pr: PullRequest, payload: PullRequestCreate) -> PullRequest:
    pr.title = payload.title
    pr.description = payload.description
    pr.state = payload.state.value
    pr.review_state = payload.review_state.value
    pr.additions = payload.additions
    pr.deletions = payload.deletions
    pr.changed_files = payload.changed_files
    if payload.author_id is not None:
        pr.author_id = payload.author_id
    if payload.repo_id is not None:
        pr.repo_id = payload.repo_id
    db.commit()
    return _load_pr_with_relations(db, pr.id)


def _ensure_default_user(db: Session, github_pr_id: int) -> User:
    user = db.query(User).filter(User.github_id == 1000).first()
    if user:
        return user

    user = User(
        github_id=1000,
        username=f"dummy-user-{github_pr_id}",
        avatar_url=None,
    )
    db.add(user)
    db.flush()
    return user


def create_pull_request(
    db: Session, payload: PullRequestCreate, default_author_id: int | None = None
) -> PullRequest:
    author_id = payload.author_id

    if author_id is None:
        author_id = default_author_id or _ensure_default_user(db, payload.github_pr_id).id

    pr = PullRequest(
        github_pr_id=payload.github_pr_id,
        github_pr_number=payload.github_pr_number,
        title=payload.title,
        description=payload.description,
        author_id=author_id,
        repo_id=payload.repo_id,
        state=payload.state.value,
        review_state=payload.review_state.value,
        eligibility_state="not_evaluated",
        additions=payload.additions,
        deletions=payload.deletions,
        changed_files=payload.changed_files,
    )
    db.add(pr)
    db.commit()
    return _load_pr_with_relations(db, pr.id)
