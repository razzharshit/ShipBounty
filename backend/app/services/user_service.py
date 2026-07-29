from __future__ import annotations

import logging

from sqlalchemy.orm import Session

from app.models.user import User


logger = logging.getLogger(__name__)


def get_or_create_user(
    db: Session,
    github_id: int,
    username: str,
    avatar_url: str | None = None,
) -> User:
    user = db.query(User).filter(User.github_id == github_id).first()
    if user:
        user.username = username
        user.avatar_url = avatar_url
        db.commit()
        db.refresh(user)
        logger.info("Updated existing user: github_id=%s username=%s", github_id, username)
        return user

    user = User(
        github_id=github_id,
        username=username,
        avatar_url=avatar_url,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    logger.info("Created new user: github_id=%s username=%s", github_id, username)
    return user
