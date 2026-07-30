"""Add reliable webhook ingestion and independent PR states.

Revision ID: 20260725_0005
Revises: 20260604_0004
Create Date: 2026-07-25
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "20260725_0005"
down_revision: Union[str, None] = "20260604_0004"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


review_state = postgresql.ENUM(
    "not_requested",
    "under_review",
    "changes_requested",
    "approved",
    name="reviewstate",
    create_type=False,
)
eligibility_state = postgresql.ENUM(
    "not_evaluated",
    "ineligible",
    "eligible",
    "claimed",
    "paid",
    name="eligibilitystate",
    create_type=False,
)
ingestion_state = postgresql.ENUM(
    "received",
    "queued",
    "processing",
    "complete",
    "incomplete",
    "failed",
    name="ingestionstate",
    create_type=False,
)
outbox_state = postgresql.ENUM(
    "pending",
    "published",
    "failed",
    name="outboxstate",
    create_type=False,
)


def upgrade() -> None:
    op.execute("ALTER TYPE pullrequeststate ADD VALUE IF NOT EXISTS 'draft'")
    op.execute("ALTER TYPE pullrequeststate ADD VALUE IF NOT EXISTS 'merged'")

    bind = op.get_bind()
    review_state.create(bind, checkfirst=True)
    eligibility_state.create(bind, checkfirst=True)
    ingestion_state.create(bind, checkfirst=True)
    outbox_state.create(bind, checkfirst=True)

    op.add_column(
        "pull_requests",
        sa.Column(
            "review_state",
            review_state,
            nullable=False,
            server_default="not_requested",
        ),
    )
    op.add_column(
        "pull_requests",
        sa.Column(
            "eligibility_state",
            eligibility_state,
            nullable=False,
            server_default="not_evaluated",
        ),
    )
    op.add_column(
        "pr_metrics",
        sa.Column("analysis_version", sa.String(length=64), nullable=False, server_default="v1"),
    )

    op.create_table(
        "webhook_deliveries",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("delivery_id", sa.String(length=255), nullable=False),
        sa.Column("event_type", sa.String(length=100), nullable=False),
        sa.Column("action", sa.String(length=100), nullable=True),
        sa.Column("installation_id", sa.BigInteger(), nullable=True),
        sa.Column("repository_id", sa.BigInteger(), nullable=True),
        sa.Column("payload", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("payload_hash", sa.String(length=64), nullable=False),
        sa.Column("status", ingestion_state, nullable=False, server_default="received"),
        sa.Column("attempt_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("received_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("started_at", sa.DateTime(), nullable=True),
        sa.Column("completed_at", sa.DateTime(), nullable=True),
        sa.Column("next_retry_at", sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("delivery_id"),
    )
    op.create_index("ix_webhook_deliveries_id", "webhook_deliveries", ["id"])
    op.create_index("ix_webhook_deliveries_delivery_id", "webhook_deliveries", ["delivery_id"])
    op.create_index("ix_webhook_deliveries_event_type", "webhook_deliveries", ["event_type"])
    op.create_index("ix_webhook_deliveries_installation_id", "webhook_deliveries", ["installation_id"])
    op.create_index("ix_webhook_deliveries_repository_id", "webhook_deliveries", ["repository_id"])
    op.create_index("ix_webhook_deliveries_status", "webhook_deliveries", ["status"])
    op.create_index("ix_webhook_deliveries_next_retry_at", "webhook_deliveries", ["next_retry_at"])

    op.create_table(
        "webhook_outbox",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("delivery_pk", sa.Integer(), nullable=False),
        sa.Column(
            "task_name",
            sa.String(length=255),
            nullable=False,
            server_default="app.worker.tasks.process_webhook_delivery",
        ),
        sa.Column("status", outbox_state, nullable=False, server_default="pending"),
        sa.Column("attempt_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("available_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("published_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(
            ["delivery_pk"],
            ["webhook_deliveries.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("delivery_pk"),
    )
    op.create_index("ix_webhook_outbox_id", "webhook_outbox", ["id"])
    op.create_index("ix_webhook_outbox_delivery_pk", "webhook_outbox", ["delivery_pk"])
    op.create_index("ix_webhook_outbox_status", "webhook_outbox", ["status"])
    op.create_index("ix_webhook_outbox_available_at", "webhook_outbox", ["available_at"])


def downgrade() -> None:
    op.drop_table("webhook_outbox")
    op.drop_table("webhook_deliveries")

    op.drop_column("pr_metrics", "analysis_version")
    op.drop_column("pull_requests", "eligibility_state")
    op.drop_column("pull_requests", "review_state")

    op.execute("UPDATE pull_requests SET state = 'open' WHERE state::text = 'draft'")
    op.execute("UPDATE pull_requests SET state = 'closed' WHERE state::text = 'merged'")
    op.execute("ALTER TABLE pull_requests ALTER COLUMN state DROP DEFAULT")
    op.execute("ALTER TYPE pullrequeststate RENAME TO pullrequeststate_phase1")
    op.execute("CREATE TYPE pullrequeststate AS ENUM ('open', 'closed')")
    op.execute(
        "ALTER TABLE pull_requests ALTER COLUMN state TYPE pullrequeststate "
        "USING state::text::pullrequeststate"
    )
    op.execute("DROP TYPE pullrequeststate_phase1")

    outbox_state.drop(op.get_bind(), checkfirst=True)
    ingestion_state.drop(op.get_bind(), checkfirst=True)
    eligibility_state.drop(op.get_bind(), checkfirst=True)
    review_state.drop(op.get_bind(), checkfirst=True)
