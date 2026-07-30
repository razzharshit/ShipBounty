from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from app.models.review_domain import (
    ApprovalOutcome,
    EligibilityDecisionStatus,
    FindingSeverity,
    HumanReviewStatus,
    ReviewRecommendation,
)


class RepositoryPolicyRead(BaseModel):
    id: int
    repository_id: int
    version: str
    name: str
    description: str | None
    rules: dict[str, Any]
    policy_hash: str
    created_by_user_id: int | None
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class RepositoryPolicyUpdate(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    description: str | None = Field(default=None, max_length=2000)
    rules: dict[str, Any]


class ReviewFindingCreate(BaseModel):
    severity: FindingSeverity
    category: str = Field(min_length=1, max_length=64)
    code: str = Field(min_length=1, max_length=128)
    message: str = Field(min_length=1, max_length=4000)
    evidence: dict[str, Any] = Field(default_factory=dict)


class ReviewFindingRead(ReviewFindingCreate):
    id: int
    review_id: int
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class ReviewSubmit(BaseModel):
    recommendation: ReviewRecommendation
    summary: str = Field(min_length=1, max_length=4000)
    findings: list[ReviewFindingCreate] = Field(default_factory=list, max_length=100)


class ReviewRead(BaseModel):
    id: int
    eligibility_decision_id: int
    reviewer_user_id: int
    status: HumanReviewStatus
    recommendation: ReviewRecommendation | None
    summary: str | None
    started_at: datetime
    completed_at: datetime | None
    findings: list[ReviewFindingRead] = Field(default_factory=list)

    model_config = ConfigDict(from_attributes=True)


class ApprovalSubmit(BaseModel):
    outcome: ApprovalOutcome
    reason: str | None = Field(default=None, max_length=4000)


class ApprovalRead(BaseModel):
    id: int
    eligibility_decision_id: int
    approver_user_id: int
    outcome: ApprovalOutcome
    reason: str | None
    score_id: int
    score_version_id: int
    repository_policy_id: int
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class EligibilityDecisionRead(BaseModel):
    id: int
    pr_id: int
    score_id: int
    score_version_id: int
    repository_policy_id: int
    status: EligibilityDecisionStatus
    is_current: bool
    evaluation_result: dict[str, Any]
    failure_reasons: list[str]
    requires_human_review: bool
    required_approvals: int
    evaluation_hash: str
    evaluated_by_user_id: int | None
    final_approved_by_user_id: int | None
    created_at: datetime
    finalized_at: datetime | None
    reviews: list[ReviewRead] = Field(default_factory=list)
    approvals: list[ApprovalRead] = Field(default_factory=list)

    model_config = ConfigDict(from_attributes=True)
