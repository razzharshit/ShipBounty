from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict

from app.models.pull_request import EligibilityState, PullRequestState, ReviewState


class PullRequestBase(BaseModel):
    github_pr_id: int
    github_pr_number: int | None = None
    title: str
    description: str | None = None
    author_id: int
    repo_id: int
    state: PullRequestState = PullRequestState.OPEN
    review_state: ReviewState = ReviewState.NOT_REQUESTED
    eligibility_state: EligibilityState = EligibilityState.NOT_EVALUATED
    additions: int = 0
    deletions: int = 0
    changed_files: int = 0
    github_updated_at: datetime | None = None
    github_created_at: datetime | None = None
    merged_at: datetime | None = None
    head_sha: str | None = None
    last_processed_delivery_id: str | None = None
    last_synchronized_head_sha: str | None = None
    file_sync_complete: bool = False
    incomplete_reason: str | None = None
    synchronized_at: datetime | None = None


class PullRequestCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    github_pr_id: int
    github_pr_number: int | None = None
    title: str
    description: str | None = None
    author_id: int | None = None
    repo_id: int
    state: PullRequestState = PullRequestState.OPEN
    review_state: ReviewState = ReviewState.NOT_REQUESTED
    additions: int = 0
    deletions: int = 0
    changed_files: int = 0


class PullRequestAuthorRead(BaseModel):
    username: str
    avatar_url: str | None

    model_config = ConfigDict(from_attributes=True)


class PullRequestRepositoryRead(BaseModel):
    name: str
    owner: str

    model_config = ConfigDict(from_attributes=True)


class PullRequestRead(PullRequestBase):
    id: int
    created_at: datetime
    author: PullRequestAuthorRead
    repository: PullRequestRepositoryRead

    model_config = ConfigDict(from_attributes=True)
