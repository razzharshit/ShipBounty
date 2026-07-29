from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from enum import Enum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.models.ai_review import AIProviderKind, AIReviewStatus


class ModerationStatus(str, Enum):
    PASSED = "passed"
    FLAGGED = "flagged"
    NOT_RUN = "not_run"
    ERROR = "error"


class AIReviewOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    summary: str = Field(min_length=1, max_length=10000)
    positive_findings: list[str] = Field(default_factory=list, max_length=100)
    risk_findings: list[str] = Field(default_factory=list, max_length=100)
    requirement_coverage: list[str] = Field(default_factory=list, max_length=100)
    recommended_actions: list[str] = Field(default_factory=list, max_length=100)
    confidence: Decimal = Field(ge=0, le=1, decimal_places=4)


class ModerationResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: ModerationStatus
    categories: dict[str, bool] = Field(default_factory=dict)
    details: str | None = Field(default=None, max_length=4000)


class TokenUsage(BaseModel):
    model_config = ConfigDict(extra="forbid")

    prompt_tokens: int = Field(ge=0)
    completion_tokens: int = Field(ge=0)
    total_tokens: int = Field(ge=0)

    @model_validator(mode="after")
    def validate_total(self):
        if self.total_tokens < self.prompt_tokens + self.completion_tokens:
            raise ValueError(
                "total_tokens cannot be less than prompt_tokens + completion_tokens"
            )
        return self


class AIReviewPolicyRead(BaseModel):
    id: int
    repository_id: int
    version: str
    name: str
    rules: dict[str, Any]
    policy_hash: str
    created_by_user_id: int | None
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class AIReviewPolicyUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=255)
    rules: dict[str, Any]


class AIReviewRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")


class AIReviewCompletion(BaseModel):
    model_config = ConfigDict(extra="forbid")

    output: AIReviewOutput
    provider_request_id: str | None = Field(default=None, max_length=255)
    token_usage: TokenUsage
    cost_amount: Decimal = Field(ge=0, max_digits=18, decimal_places=8)
    cost_currency: str = Field(min_length=1, max_length=16)
    moderation_result: ModerationResult


class AIReviewFailure(BaseModel):
    model_config = ConfigDict(extra="forbid")

    failure_reason: str = Field(min_length=1, max_length=4000)
    provider_request_id: str | None = Field(default=None, max_length=255)
    moderation_result: ModerationResult = Field(
        default_factory=lambda: ModerationResult(status=ModerationStatus.NOT_RUN)
    )


class AIReviewRead(BaseModel):
    id: int
    pr_id: int
    analysis_run_id: int
    repository_policy_id: int
    ai_review_policy_id: int
    requested_by_user_id: int | None
    provider: str
    model: str
    provider_kind: AIProviderKind
    prompt_version: str
    input_commit_sha: str
    input_snapshot: dict[str, Any]
    input_hash: str
    privacy_decision: dict[str, Any]
    status: AIReviewStatus
    output: dict[str, Any] | None
    provider_request_id: str | None
    prompt_tokens: int | None
    completion_tokens: int | None
    total_tokens: int | None
    cost_amount: Decimal | None
    cost_currency: str | None
    moderation_result: dict[str, Any] | None
    failure_reason: str | None
    advisory_only: bool
    review_key: str
    created_at: datetime
    completed_at: datetime | None

    model_config = ConfigDict(from_attributes=True)
