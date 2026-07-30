from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timedelta, timezone

from sqlalchemy import case, func
from sqlalchemy.orm import Session

from app.models.authorization import Organization
from app.models.bounty_domain import (
    Bounty,
    BountyStatus,
    Claim,
    ClaimStatus,
    Payout,
    PayoutState,
)
from app.models.operations import GitHubRateLimitSnapshot, WorkerHeartbeat
from app.models.pull_request import PullRequest, PullRequestState
from app.models.repository import Repository
from app.models.review_domain import EligibilityDecision, EligibilityDecisionStatus
from app.models.webhook_delivery import IngestionState, WebhookDelivery
from app.models.webhook_outbox import OutboxState, WebhookOutbox


PENDING_REVIEW_STATES = {
    EligibilityDecisionStatus.PENDING_REVIEW,
    EligibilityDecisionStatus.CHANGES_REQUESTED,
    EligibilityDecisionStatus.PENDING_APPROVAL,
}
PENDING_PAYOUT_STATES = {
    PayoutState.CREATED,
    PayoutState.AUTHORIZED,
    PayoutState.SUBMITTING,
    PayoutState.SUBMISSION_UNKNOWN,
    PayoutState.SUBMITTED,
    PayoutState.FAILED,
}


def _naive_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value
    return value.astimezone(timezone.utc).replace(tzinfo=None)


def _delivery_summary(delivery: WebhookDelivery) -> dict:
    return {
        "id": delivery.id,
        "delivery_id": delivery.delivery_id,
        "event_type": delivery.event_type,
        "action": delivery.action,
        "status": delivery.status.value,
        "attempt_count": delivery.attempt_count,
        "received_at": delivery.received_at,
        "started_at": delivery.started_at,
        "completed_at": delivery.completed_at,
        "next_retry_at": delivery.next_retry_at,
        "last_error": delivery.last_error,
    }


def _amounts_by_currency(items) -> dict[str, str]:
    totals = defaultdict(lambda: 0)
    for item in items:
        totals[item.currency] += item.amount
    return {
        currency: str(amount)
        for currency, amount in sorted(totals.items())
    }


def operations_dashboard(db: Session, organization_id: int) -> dict:
    now = datetime.utcnow()
    deliveries = (
        db.query(WebhookDelivery)
        .filter(WebhookDelivery.organization_id == organization_id)
        .order_by(WebhookDelivery.received_at.desc(), WebhookDelivery.id.desc())
        .limit(250)
        .all()
    )
    job_counts = (
        db.query(
            func.sum(
                case((WebhookDelivery.status == IngestionState.QUEUED, 1), else_=0)
            ),
            func.sum(
                case(
                    (WebhookDelivery.status == IngestionState.PROCESSING, 1),
                    else_=0,
                )
            ),
            func.sum(
                case((WebhookDelivery.status == IngestionState.FAILED, 1), else_=0)
            ),
            func.sum(
                case(
                    (
                        WebhookDelivery.attempt_count > 1,
                        WebhookDelivery.attempt_count - 1,
                    ),
                    else_=0,
                )
            ),
        )
        .filter(WebhookDelivery.organization_id == organization_id)
        .one()
    )
    queued_jobs, running_jobs, failed_jobs, total_retry_attempts = (
        int(value or 0) for value in job_counts
    )
    durations = [
        (item.completed_at - item.started_at).total_seconds()
        for item in deliveries
        if item.started_at is not None
        and item.completed_at is not None
        and item.completed_at >= item.started_at
    ]
    awaiting_publish = (
        db.query(WebhookOutbox)
        .join(WebhookDelivery, WebhookDelivery.id == WebhookOutbox.delivery_pk)
        .filter(
            WebhookDelivery.organization_id == organization_id,
            WebhookOutbox.status.in_([OutboxState.PENDING, OutboxState.FAILED]),
        )
        .count()
    )
    incomplete_query = (
        db.query(PullRequest)
        .join(Repository, Repository.id == PullRequest.repo_id)
        .filter(
            Repository.organization_id == organization_id,
            PullRequest.file_sync_complete.is_(False),
        )
    )
    incomplete_ingestions = incomplete_query.count()
    incomplete_prs = (
        incomplete_query
        .order_by(PullRequest.synchronized_at.desc(), PullRequest.id.desc())
        .limit(50)
        .all()
    )
    workers = db.query(WorkerHeartbeat).all()
    stale_cutoff = now - timedelta(seconds=90)
    rate_limits = (
        db.query(GitHubRateLimitSnapshot)
        .filter(GitHubRateLimitSnapshot.organization_id == organization_id)
        .order_by(
            GitHubRateLimitSnapshot.remaining.asc(),
            GitHubRateLimitSnapshot.observed_at.desc(),
        )
        .all()
    )
    failures = [
        item
        for item in deliveries
        if item.status in {IngestionState.FAILED, IngestionState.INCOMPLETE}
        and item.last_error
    ][:50]
    return {
        "generated_at": now,
        "queue_depth": awaiting_publish + queued_jobs,
        "awaiting_publish": awaiting_publish,
        "queued_jobs": queued_jobs,
        "running_jobs": running_jobs,
        "failed_jobs": failed_jobs,
        "total_retry_attempts": total_retry_attempts,
        "incomplete_ingestions": incomplete_ingestions,
        "average_processing_seconds": (
            round(sum(durations) / len(durations), 3) if durations else None
        ),
        # Tenant dashboards expose fleet health, never worker identifiers or
        # per-worker metadata. Detailed worker data belongs to platform admin.
        "workers": (
            [
                {
                    "worker_id": "aggregate",
                    "queues": sorted(
                        {
                            queue
                            for item in workers
                            for queue in (item.queues or [])
                        }
                    ),
                    "status": (
                        "online"
                        if any(item.last_seen_at >= stale_cutoff for item in workers)
                        else "stale"
                    ),
                    "active_tasks": sum(item.active_tasks for item in workers),
                    "last_seen_at": max(item.last_seen_at for item in workers),
                    "is_stale": all(
                        item.last_seen_at < stale_cutoff for item in workers
                    ),
                }
            ]
            if workers
            else []
        ),
        "github_rate_limits": [
            {
                "installation_id": item.installation_id,
                "resource": item.resource,
                "limit": item.limit,
                "remaining": item.remaining,
                "used": item.used,
                "reset_at": item.reset_at,
                "observed_at": item.observed_at,
            }
            for item in rate_limits
        ],
        "recent_deliveries": [_delivery_summary(item) for item in deliveries[:50]],
        "incomplete_pull_requests": [
            {
                "id": item.id,
                "title": item.title,
                "repository": item.repository.full_name,
                "incomplete_reason": item.incomplete_reason,
                "synchronized_at": item.synchronized_at,
            }
            for item in incomplete_prs
        ],
        "failure_logs": [_delivery_summary(item) for item in failures],
    }


def product_analytics(
    db: Session,
    organization: Organization,
    repository_ids: list[int],
) -> dict:
    now = datetime.utcnow()
    if not repository_ids:
        return {
            "generated_at": now,
            "organization": {
                "id": organization.id,
                "login": organization.login,
                "repository_count": 0,
                "contributor_count": 0,
                "pull_request_count": 0,
            },
            "open_bounties": 0,
            "open_bounty_amounts": {},
            "pending_reviews": 0,
            "eligible_claims": 0,
            "pending_payouts": 0,
            "confirmed_payouts": 0,
            "confirmed_payout_amounts": {},
            "average_merge_seconds": None,
            "contributors": [],
            "repositories": [],
        }
    repositories = (
        db.query(Repository)
        .filter(Repository.id.in_(repository_ids))
        .order_by(Repository.full_name)
        .all()
    )
    prs = (
        db.query(PullRequest)
        .filter(PullRequest.repo_id.in_(repository_ids))
        .all()
    )
    pr_ids = [item.id for item in prs]
    bounties = (
        db.query(Bounty).filter(Bounty.repository_id.in_(repository_ids)).all()
    )
    decisions = (
        db.query(EligibilityDecision)
        .join(PullRequest, PullRequest.id == EligibilityDecision.pr_id)
        .filter(
            PullRequest.repo_id.in_(repository_ids),
            EligibilityDecision.is_current.is_(True),
        )
        .all()
    )
    claims = (
        db.query(Claim).filter(Claim.pull_request_id.in_(pr_ids)).all()
        if pr_ids
        else []
    )
    payouts = (
        db.query(Payout)
        .join(Claim, Claim.id == Payout.claim_id)
        .filter(Claim.pull_request_id.in_(pr_ids))
        .all()
        if pr_ids
        else []
    )
    open_bounties = [
        item for item in bounties
        if item.status in {BountyStatus.OPEN, BountyStatus.ASSIGNED}
    ]
    confirmed = [item for item in payouts if item.state == PayoutState.CONFIRMED]
    merge_durations = [
        (item.merged_at - item.github_created_at).total_seconds()
        for item in prs
        if item.merged_at is not None
        and item.github_created_at is not None
        and item.merged_at >= item.github_created_at
    ]
    claims_by_pr: dict[int, list[Claim]] = defaultdict(list)
    for claim in claims:
        claims_by_pr[claim.pull_request_id].append(claim)
    confirmed_claim_ids = {item.claim_id for item in confirmed}
    contributor_rows: dict[int, dict] = {}
    for pr in prs:
        row = contributor_rows.setdefault(
            pr.author_id,
            {
                "user_id": pr.author_id,
                "username": pr.author.username,
                "avatar_url": pr.author.avatar_url,
                "pull_requests": 0,
                "merged_pull_requests": 0,
                "approved_claims": 0,
                "confirmed_payouts": 0,
                "last_activity_at": None,
            },
        )
        row["pull_requests"] += 1
        if pr.state == PullRequestState.MERGED:
            row["merged_pull_requests"] += 1
        linked_claims = claims_by_pr.get(pr.id, [])
        row["approved_claims"] += sum(
            claim.status in {ClaimStatus.APPROVED, ClaimStatus.PAID}
            for claim in linked_claims
        )
        row["confirmed_payouts"] += sum(
            claim.id in confirmed_claim_ids for claim in linked_claims
        )
        activity_at = _naive_utc(
            pr.merged_at or pr.github_updated_at or pr.created_at
        )
        if row["last_activity_at"] is None or activity_at > row["last_activity_at"]:
            row["last_activity_at"] = activity_at

    repo_rows = []
    for repository in repositories:
        repo_prs = [item for item in prs if item.repo_id == repository.id]
        repo_pr_ids = {item.id for item in repo_prs}
        incomplete = sum(not item.file_sync_complete for item in repo_prs)
        failed = (
            db.query(WebhookDelivery)
            .filter(
                WebhookDelivery.repository_pk == repository.id,
                WebhookDelivery.status == IngestionState.FAILED,
            )
            .count()
        )
        repo_open_bounties = sum(
            item.repository_id == repository.id
            and item.status in {BountyStatus.OPEN, BountyStatus.ASSIGNED}
            for item in bounties
        )
        repo_pending_reviews = sum(
            item.pr_id in repo_pr_ids and item.status in PENDING_REVIEW_STATES
            for item in decisions
        )
        last_sync = max(
            (item.synchronized_at for item in repo_prs if item.synchronized_at),
            default=None,
        )
        health = (
            "critical"
            if failed > 0
            else "attention"
            if incomplete > 0 or repo_pending_reviews > 0
            else "healthy"
        )
        repo_rows.append(
            {
                "repository_id": repository.id,
                "full_name": repository.full_name,
                "pull_requests": len(repo_prs),
                "incomplete_ingestions": incomplete,
                "failed_deliveries": failed,
                "open_bounties": repo_open_bounties,
                "pending_reviews": repo_pending_reviews,
                "last_synchronized_at": last_sync,
                "health": health,
            }
        )
    return {
        "generated_at": now,
        "organization": {
            "id": organization.id,
            "login": organization.login,
            "repository_count": len(repositories),
            "contributor_count": len(contributor_rows),
            "pull_request_count": len(prs),
        },
        "open_bounties": len(open_bounties),
        "open_bounty_amounts": _amounts_by_currency(open_bounties),
        "pending_reviews": sum(
            item.status in PENDING_REVIEW_STATES for item in decisions
        ),
        "eligible_claims": sum(
            item.status == ClaimStatus.APPROVED for item in claims
        ),
        "pending_payouts": sum(
            item.state in PENDING_PAYOUT_STATES for item in payouts
        ),
        "confirmed_payouts": len(confirmed),
        "confirmed_payout_amounts": _amounts_by_currency(confirmed),
        "average_merge_seconds": (
            round(sum(merge_durations) / len(merge_durations), 3)
            if merge_durations
            else None
        ),
        "contributors": sorted(
            contributor_rows.values(),
            key=lambda item: (
                -item["confirmed_payouts"],
                -item["merged_pull_requests"],
                item["username"],
            ),
        ),
        "repositories": repo_rows,
    }
