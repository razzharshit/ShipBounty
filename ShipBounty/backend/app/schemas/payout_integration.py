from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from app.models.payout_integration import (
    LedgerEntryType,
    ReconciliationOutcome,
    TreasuryApprovalDecision,
    TreasuryEnvironment,
    TreasuryStatus,
)


class TreasuryCreate(BaseModel):
    provider_key: str = Field(min_length=1, max_length=64)
    environment: TreasuryEnvironment = TreasuryEnvironment.TESTNET
    chain: str = Field(min_length=1, max_length=64)
    currency: str = Field(min_length=1, max_length=16)
    treasury_address: str = Field(min_length=1, max_length=255)
    asset_contract_address: str | None = Field(default=None, max_length=255)
    asset_decimals: int = Field(default=6, ge=0, le=18)
    custody_model: str = Field(default="multisig", min_length=1, max_length=32)
    opening_balance: Decimal = Field(ge=0, max_digits=24, decimal_places=6)
    per_payout_limit: Decimal = Field(gt=0, max_digits=24, decimal_places=6)
    daily_spending_limit: Decimal = Field(
        gt=0, max_digits=24, decimal_places=6
    )
    manual_approval_threshold: Decimal | None = Field(
        default=None, gt=0, max_digits=24, decimal_places=6
    )
    standard_required_approvals: int = Field(default=1, ge=1, le=20)
    high_value_required_approvals: int = Field(default=2, ge=1, le=20)
    required_confirmations: int = Field(default=1, ge=1, le=10000)
    simulation_required: bool = True
    provider_config: dict[str, Any] = Field(default_factory=dict)


class TreasuryRead(BaseModel):
    id: int
    organization_id: int
    provider_key: str
    environment: TreasuryEnvironment
    chain: str
    currency: str
    treasury_address: str
    asset_contract_address: str | None
    asset_decimals: int
    custody_model: str
    opening_balance: Decimal
    observed_balance: Decimal | None
    available_balance: Decimal
    reserved_balance: Decimal
    settled_amount: Decimal
    per_payout_limit: Decimal
    daily_spending_limit: Decimal
    manual_approval_threshold: Decimal | None
    standard_required_approvals: int
    high_value_required_approvals: int
    required_confirmations: int
    simulation_required: bool
    status: TreasuryStatus
    paused_reason: str | None
    last_balance_checked_at: datetime | None
    created_by_user_id: int
    created_at: datetime
    updated_at: datetime


class TreasuryPauseRequest(BaseModel):
    paused: bool
    reason: str = Field(min_length=1, max_length=1000)


class TreasuryApprovalCreate(BaseModel):
    decision: TreasuryApprovalDecision = TreasuryApprovalDecision.APPROVED
    reason: str | None = Field(default=None, max_length=4000)


class TreasuryApprovalRead(BaseModel):
    id: int
    payout_id: int
    treasury_account_id: int
    approver_user_id: int
    decision: TreasuryApprovalDecision
    reason: str | None
    amount: Decimal
    currency: str
    created_at: datetime
    model_config = ConfigDict(from_attributes=True)


class PayoutSubmitRequest(BaseModel):
    idempotency_key: str = Field(min_length=8, max_length=128)


class LedgerEntryRead(BaseModel):
    id: int
    treasury_account_id: int
    payout_id: int | None
    entry_type: LedgerEntryType
    currency: str
    available_delta: Decimal
    reserved_delta: Decimal
    settled_delta: Decimal
    idempotency_key: str
    entry_metadata: dict[str, Any]
    created_by_user_id: int | None
    created_at: datetime
    model_config = ConfigDict(from_attributes=True)


class ReconciliationRead(BaseModel):
    id: int
    payout_id: int
    payout_attempt_id: int | None
    provider_key: str
    provider_reference: str
    outcome: ReconciliationOutcome
    confirmations: int
    transaction_hash: str | None
    provider_status_hash: str
    provider_response: dict[str, Any]
    error: str | None
    checked_at: datetime
    model_config = ConfigDict(from_attributes=True)


class TreasuryBalanceSnapshotRead(BaseModel):
    id: int
    treasury_account_id: int
    provider_key: str
    currency: str
    observed_balance: Decimal
    balance_hash: str
    provider_response: dict[str, Any]
    observed_at: datetime
    model_config = ConfigDict(from_attributes=True)
