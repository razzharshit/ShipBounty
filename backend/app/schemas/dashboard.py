from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict


class WorkerHeartbeatRead(BaseModel):
    worker_id: str
    queues: list[str]
    status: str
    active_tasks: int
    last_seen_at: datetime
    is_stale: bool


class PlatformWorkerHeartbeatRead(WorkerHeartbeatRead):
    worker_metadata: dict[str, Any]
    first_seen_at: datetime


class UnresolvedDeliveryRead(BaseModel):
    id: int
    delivery_id: str
    event_type: str
    action: str | None
    installation_id: int | None
    repository_id: int | None
    repository_full_name: str | None
    repository_owner_login: str | None
    status: str
    received_at: datetime
    last_error: str | None


class GitHubRateLimitRead(BaseModel):
    installation_id: int
    resource: str
    limit: int
    remaining: int
    used: int
    reset_at: datetime
    observed_at: datetime


class DeliverySummary(BaseModel):
    id: int
    delivery_id: str
    event_type: str
    action: str | None
    status: str
    attempt_count: int
    received_at: datetime
    started_at: datetime | None
    completed_at: datetime | None
    next_retry_at: datetime | None
    last_error: str | None


class IncompletePRSummary(BaseModel):
    id: int
    title: str
    repository: str
    incomplete_reason: str | None
    synchronized_at: datetime | None


class OperationsDashboardRead(BaseModel):
    generated_at: datetime
    queue_depth: int
    awaiting_publish: int
    queued_jobs: int
    running_jobs: int
    failed_jobs: int
    total_retry_attempts: int
    incomplete_ingestions: int
    average_processing_seconds: float | None
    workers: list[WorkerHeartbeatRead]
    github_rate_limits: list[GitHubRateLimitRead]
    recent_deliveries: list[DeliverySummary]
    incomplete_pull_requests: list[IncompletePRSummary]
    failure_logs: list[DeliverySummary]


class ContributorActivityRead(BaseModel):
    user_id: int
    username: str
    avatar_url: str | None
    pull_requests: int
    merged_pull_requests: int
    approved_claims: int
    confirmed_payouts: int
    last_activity_at: datetime | None


class RepositoryHealthRead(BaseModel):
    repository_id: int
    full_name: str
    pull_requests: int
    incomplete_ingestions: int
    failed_deliveries: int
    open_bounties: int
    pending_reviews: int
    last_synchronized_at: datetime | None
    health: str


class ProductAnalyticsRead(BaseModel):
    generated_at: datetime
    organization: dict[str, Any]
    open_bounties: int
    open_bounty_amounts: dict[str, str]
    pending_reviews: int
    eligible_claims: int
    pending_payouts: int
    confirmed_payouts: int
    confirmed_payout_amounts: dict[str, str]
    average_merge_seconds: float | None
    contributors: list[ContributorActivityRead]
    repositories: list[RepositoryHealthRead]


class NotificationRead(BaseModel):
    id: int
    event_id: int
    channel: str
    status: str
    subject: str
    body: str
    payload: dict[str, Any]
    attempt_count: int
    last_error: str | None
    delivered_at: datetime | None
    read_at: datetime | None
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)
