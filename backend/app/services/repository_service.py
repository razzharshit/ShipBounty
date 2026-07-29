import logging

from sqlalchemy.orm import Session

from app.models.repository import Repository
from app.models.authorization import Organization


logger = logging.getLogger(__name__)


def get_or_create_repository(
    db: Session,
    github_repo_id: int,
    name: str,
    owner: str,
) -> Repository:
    repo = db.query(Repository).filter(Repository.github_repo_id == github_repo_id).first()
    if repo:
        organization = (
            db.query(Organization)
            .filter(Organization.login == owner.lower())
            .first()
        )
        if organization is None:
            organization = Organization(login=owner.lower(), display_name=owner)
            db.add(organization)
            db.flush()
        repo.organization_id = organization.id
        repo.name = name
        repo.owner = owner
        repo.full_name = f"{owner}/{name}"
        db.commit()
        db.refresh(repo)
        logger.info("Updated existing repository: github_repo_id=%s name=%s owner=%s", github_repo_id, name, owner)
        return repo

    organization = (
        db.query(Organization)
        .filter(Organization.login == owner.lower())
        .first()
    )
    if organization is None:
        organization = Organization(login=owner.lower(), display_name=owner)
        db.add(organization)
        db.flush()
    repo = Repository(
        github_repo_id=github_repo_id,
        organization_id=organization.id,
        name=name,
        owner=owner,
        full_name=f"{owner}/{name}",
    )
    db.add(repo)
    db.commit()
    db.refresh(repo)
    logger.info("Created new repository: github_repo_id=%s name=%s owner=%s", github_repo_id, name, owner)
    return repo
