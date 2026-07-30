from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict


class PullRequestFileRead(BaseModel):
    id: int
    pr_id: int
    filename: str
    previous_filename: str | None
    github_status: str
    sha: str | None
    additions: int
    deletions: int
    changes: int
    patch: str | None
    patch_available: bool
    patch_status: str
    contents_url: str | None
    blob_url: str | None
    raw_url: str | None
    first_seen_at: datetime
    last_seen_at: datetime
    is_current: bool
    removed_at: datetime | None
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)
