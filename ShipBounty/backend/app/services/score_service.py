from __future__ import annotations

from sqlalchemy.orm import Session

from app.models.pull_request import PullRequest
from app.models.score import Score


def get_score_by_pr_id(db: Session, pr_id: int) -> Score | None:
    pull_request = db.get(PullRequest, pr_id)
    if pull_request is None or pull_request.latest_score_id is None:
        return None
    return db.get(Score, pull_request.latest_score_id)


def list_score_history(db: Session, pr_id: int) -> list[Score]:
    return (
        db.query(Score)
        .filter(Score.pr_id == pr_id)
        .order_by(Score.created_at.desc(), Score.id.desc())
        .all()
    )
