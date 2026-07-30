from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

from app.schemas.authorization import AuthenticatedUserRead


DemoPersonaName = Literal["owner", "reviewer", "finance", "contributor"]


class DemoLoginRequest(BaseModel):
    workspace: str = Field(min_length=1, max_length=255)
    persona: DemoPersonaName
    access_key: str = Field(min_length=1, max_length=512)


class DemoLoginRead(BaseModel):
    workspace: str
    persona: DemoPersonaName
    user: AuthenticatedUserRead
