"""Add operational telemetry, analytics timestamps, and notifications.

Revision ID: 20260725_0012
Revises: 20260725_0011
Create Date: 2026-07-25
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "20260725_0012"
down_revision: Union[str, None] = "20260725_0011"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

EVENT_TYPES = (
    "pr.analysis_completed",
    "pr.analysis_failed",
    "review.requested",
    "review.changes_requested",
    "bounty.eligible",
    "claim.approved",
    "payout.submitted",
    "payout.confirmed",
    "payout.failed",
)

notification_channel = postgresql.ENUM(
    "in_app", "email", name="notificationchannel", create_type=False
)
notification_status = postgresql.ENUM(
    "pending", "delivered", "failed",
    name="notificationstatus",
    create_type=False,
)


def _index(table: str, *columns: str) -> None:
    for column in columns:
        op.create_index(f"ix_{table}_{column}", table, [column])


def upgrade() -> None:
    bind = op.get_bind()
    notification_channel.create(bind, checkfirst=True)
    notification_status.create(bind, checkfirst=True)

    op.add_column(
        "pull_requests",
        sa.Column("github_created_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "pull_requests",
        sa.Column("merged_at", sa.DateTime(timezone=True), nullable=True),
    )

    op.create_table(
        "worker_heartbeats",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("worker_id", sa.String(255), nullable=False),
        sa.Column("queues", sa.JSON(), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("active_tasks", sa.Integer(), nullable=False),
        sa.Column("worker_metadata", sa.JSON(), nullable=False),
        sa.Column(
            "first_seen_at", sa.DateTime(), nullable=False, server_default=sa.func.now()
        ),
        sa.Column(
            "last_seen_at", sa.DateTime(), nullable=False, server_default=sa.func.now()
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("worker_id", name="uq_worker_heartbeats_worker_id"),
    )
    _index("worker_heartbeats", "id", "worker_id", "last_seen_at")

    op.create_table(
        "github_rate_limit_snapshots",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("installation_id", sa.BigInteger(), nullable=False),
        sa.Column("organization_id", sa.Integer(), nullable=True),
        sa.Column("repository_id", sa.Integer(), nullable=True),
        sa.Column("resource", sa.String(64), nullable=False),
        sa.Column("limit", sa.Integer(), nullable=False),
        sa.Column("remaining", sa.Integer(), nullable=False),
        sa.Column("used", sa.Integer(), nullable=False),
        sa.Column("reset_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "observed_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.ForeignKeyConstraint(
            ["organization_id"], ["organizations.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["repository_id"], ["repositories.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "installation_id",
            "resource",
            name="uq_github_rate_limits_installation_resource",
        ),
    )
    _index(
        "github_rate_limit_snapshots",
        "id",
        "installation_id",
        "organization_id",
        "repository_id",
        "observed_at",
    )

    op.create_table(
        "domain_events",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("event_type", sa.String(128), nullable=False),
        sa.Column("organization_id", sa.Integer(), nullable=False),
        sa.Column("repository_id", sa.Integer(), nullable=True),
        sa.Column("aggregate_type", sa.String(64), nullable=False),
        sa.Column("aggregate_id", sa.String(255), nullable=False),
        sa.Column("actor_user_id", sa.Integer(), nullable=True),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("event_key", sa.String(64), nullable=False),
        sa.Column(
            "occurred_at", sa.DateTime(), nullable=False, server_default=sa.func.now()
        ),
        sa.Column(
            "created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()
        ),
        sa.ForeignKeyConstraint(
            ["organization_id"], ["organizations.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["repository_id"], ["repositories.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["actor_user_id"], ["users.id"], ondelete="SET NULL"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("event_key", name="uq_domain_events_event_key"),
    )
    _index(
        "domain_events", "id", "event_type", "organization_id",
        "repository_id", "event_key"
    )

    op.create_table(
        "notification_policies",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("organization_id", sa.Integer(), nullable=False),
        sa.Column("event_type", sa.String(128), nullable=False),
        sa.Column("channel", notification_channel, nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("max_attempts", sa.Integer(), nullable=False, server_default="5"),
        sa.Column("configuration", sa.JSON(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()
        ),
        sa.Column(
            "updated_at", sa.DateTime(), nullable=False, server_default=sa.func.now()
        ),
        sa.ForeignKeyConstraint(
            ["organization_id"], ["organizations.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "organization_id",
            "event_type",
            "channel",
            name="uq_notification_policies_org_event_channel",
        ),
    )
    _index(
        "notification_policies",
        "id",
        "organization_id",
        "event_type",
        "channel",
    )
    for event_type in EVENT_TYPES:
        for channel in ("in_app", "email"):
            op.execute(
                sa.text(
                    """
                    INSERT INTO notification_policies (
                        organization_id, event_type, channel, enabled,
                        max_attempts, configuration
                    )
                    SELECT id, :event_type, CAST(:channel AS notificationchannel),
                           true, 5, CAST('{}' AS json)
                    FROM organizations
                    """
                ).bindparams(event_type=event_type, channel=channel)
            )

    op.create_table(
        "notifications",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("event_id", sa.Integer(), nullable=False),
        sa.Column("policy_id", sa.Integer(), nullable=False),
        sa.Column("recipient_user_id", sa.Integer(), nullable=False),
        sa.Column("channel", notification_channel, nullable=False),
        sa.Column("destination", sa.String(512), nullable=True),
        sa.Column("status", notification_status, nullable=False),
        sa.Column("subject", sa.String(255), nullable=False),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("idempotency_key", sa.String(64), nullable=False),
        sa.Column("attempt_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("next_retry_at", sa.DateTime(), nullable=True),
        sa.Column("delivered_at", sa.DateTime(), nullable=True),
        sa.Column("read_at", sa.DateTime(), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()
        ),
        sa.ForeignKeyConstraint(
            ["event_id"], ["domain_events.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["policy_id"], ["notification_policies.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["recipient_user_id"], ["users.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "event_id",
            "policy_id",
            "recipient_user_id",
            name="uq_notifications_event_policy_recipient",
        ),
        sa.UniqueConstraint(
            "idempotency_key", name="uq_notifications_idempotency_key"
        ),
    )
    _index(
        "notifications",
        "id",
        "event_id",
        "policy_id",
        "recipient_user_id",
        "channel",
        "status",
        "next_retry_at",
    )
    op.create_index(
        "ix_notifications_delivery_due",
        "notifications",
        ["status", "next_retry_at"],
    )

    op.execute(
        """
        CREATE FUNCTION prevent_domain_event_mutation()
        RETURNS trigger AS $$
        BEGIN
            RAISE EXCEPTION 'domain events are immutable';
        END;
        $$ LANGUAGE plpgsql
        """
    )
    op.execute(
        """
        CREATE TRIGGER trg_domain_events_immutable
        BEFORE UPDATE OR DELETE ON domain_events
        FOR EACH ROW EXECUTE FUNCTION prevent_domain_event_mutation()
        """
    )


def downgrade() -> None:
    op.execute(
        "DROP TRIGGER IF EXISTS trg_domain_events_immutable ON domain_events"
    )
    op.execute("DROP FUNCTION IF EXISTS prevent_domain_event_mutation()")
    op.drop_table("notifications")
    op.drop_table("notification_policies")
    op.drop_table("domain_events")
    op.drop_table("github_rate_limit_snapshots")
    op.drop_table("worker_heartbeats")
    op.drop_column("pull_requests", "merged_at")
    op.drop_column("pull_requests", "github_created_at")
    notification_status.drop(op.get_bind(), checkfirst=True)
    notification_channel.drop(op.get_bind(), checkfirst=True)
