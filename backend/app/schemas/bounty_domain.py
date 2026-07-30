from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from app.models.bounty_domain import (
    AssignmentStatus,
    BountyStatus,
    ClaimStatus,
    FundingStatus,
    IssueState,
    PayoutAttemptState,
    PayoutState,
    WalletStatus,
)


class BountyPolicyRead(BaseModel):
    id: int
    organization_id: int
    repository_id: int
    version: str
    name: str
    rules: dict[str, Any]
    policy_hash: str
    created_by_user_id: int | None
    created_at: datetime
    model_config = ConfigDict(from_attributes=True)


class BountyPolicyUpdate(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    rules: dict[str, Any]


class IssueCreate(BaseModel):
    github_issue_id: int
    number: int = Field(gt=0)
    title: str = Field(min_length=1, max_length=512)
    description: str | None = None
    url: str | None = Field(default=None, max_length=2048)
    state: IssueState = IssueState.OPEN


class IssueRead(IssueCreate):
    id: int
    organization_id: int
    repository_id: int
    state: IssueState
    created_at: datetime
    updated_at: datetime
    model_config = ConfigDict(from_attributes=True)


class BountyCreate(BaseModel):
    amount: Decimal = Field(gt=0, max_digits=18, decimal_places=6)
    currency: str = Field(min_length=1, max_length=16)
    expires_at: datetime | None = None


class BountyRead(BaseModel):
    id: int
    organization_id: int
    repository_id: int
    issue_id: int
    bounty_policy_id: int
    eligibility_policy_id: int
    amount: Decimal
    currency: str
    status: BountyStatus
    funding_status: FundingStatus
    expires_at: datetime | None
    created_by_user_id: int
    created_at: datetime
    model_config = ConfigDict(from_attributes=True)


class AssignmentCreate(BaseModel):
    assignee_user_id: int
    pull_request_id: int | None = None


class AssignmentLink(BaseModel):
    pull_request_id: int


class AssignmentRead(BaseModel):
    id: int
    bounty_id: int
    assignee_user_id: int
    pull_request_id: int | None
    status: AssignmentStatus
    assigned_by_user_id: int
    assigned_at: datetime
    completed_at: datetime | None
    model_config = ConfigDict(from_attributes=True)


class WalletCreate(BaseModel):
    chain: str = Field(min_length=1, max_length=64)
    address: str = Field(min_length=1, max_length=255)


class WalletRead(BaseModel):
    id: int
    user_id: int
    chain: str
    address: str
    status: WalletStatus
    verified: bool
    created_at: datetime
    model_config = ConfigDict(from_attributes=True)


class ClaimCreate(BaseModel):
    assignment_id: int
    pull_request_id: int
    eligibility_decision_id: int
    wallet_id: int


class ClaimRead(BaseModel):
    id: int
    bounty_id: int
    assignment_id: int
    pull_request_id: int
    eligibility_decision_id: int
    approval_id: int
    claimant_user_id: int
    wallet_id: int
    amount: Decimal
    currency: str
    destination_chain: str
    destination_address: str
    status: ClaimStatus
    created_at: datetime
    model_config = ConfigDict(from_attributes=True)


class IdempotencyRequest(BaseModel):
    idempotency_key: str = Field(min_length=8, max_length=128)


class PayoutCreateRequest(IdempotencyRequest):
    treasury_account_id: int


class PayoutRead(BaseModel):
    id: int
    claim_id: int
    approval_id: int
    amount: Decimal
    currency: str
    destination_chain: str
    destination_address: str
    idempotency_key: str
    treasury_account_id: int | None
    provider_key: str | None
    provider_reference: str | None
    state: PayoutState
    authorized_by_user_id: int | None
    authorized_at: datetime | None
    transaction_hash: str | None
    explorer_url: str | None
    required_confirmations: int
    observed_confirmations: int
    last_status_checked_at: datetime | None
    next_reconciliation_at: datetime | None
    confirmed_at: datetime | None
    failure_reason: str | None
    created_at: datetime
    updated_at: datetime
    model_config = ConfigDict(from_attributes=True)


class AttemptCreate(IdempotencyRequest):
    provider: str = Field(min_length=1, max_length=64)


class AttemptSubmitted(BaseModel):
    transaction_hash: str = Field(min_length=1, max_length=255)


class AttemptFailed(BaseModel):
    error: str = Field(min_length=1, max_length=4000)


class PayoutAttemptRead(BaseModel):
    id: int
    payout_id: int
    attempt_number: int
    idempotency_key: str
    state: PayoutAttemptState
    provider: str
    request_hash: str
    provider_reference: str | None
    transaction_hash: str | None
    explorer_url: str | None
    simulation_result: dict[str, Any]
    provider_response: dict[str, Any]
    last_checked_at: datetime | None
    recovery_attempt_count: int
    error: str | None
    created_at: datetime
    submitted_at: datetime | None
    completed_at: datetime | None
    model_config = ConfigDict(from_attributes=True)
