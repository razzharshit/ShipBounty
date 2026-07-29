from datetime import datetime

from pydantic import BaseModel, ConfigDict


class RepositoryBase(BaseModel):
    github_repo_id: int
    organization_id: int
    name: str
    owner: str
    full_name: str
    is_private: bool = False
    is_archived: bool = False


class RepositoryRead(RepositoryBase):
    id: int
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)
