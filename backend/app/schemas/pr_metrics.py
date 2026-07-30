from datetime import datetime

from pydantic import BaseModel, ConfigDict


class PRMetricsRead(BaseModel):
    id: int
    pr_id: int
    total_files: int
    total_additions: int
    total_deletions: int
    has_tests: bool
    has_docs: bool
    language_breakdown: dict[str, int]
    analysis_version: str
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)
