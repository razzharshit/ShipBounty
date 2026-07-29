"""Add complete GitHub snapshots and analysis runs.

Revision ID: 20260725_0006
Revises: 20260725_0005
Create Date: 2026-07-25
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "20260725_0006"
down_revision: Union[str, None] = "20260725_0005"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


analysis_run_status = postgresql.ENUM(
    "complete",
    "incomplete",
    name="analysisrunstatus",
    create_type=False,
)


def upgrade() -> None:
    bind = op.get_bind()
    analysis_run_status.create(bind, checkfirst=True)

    op.add_column(
        "webhook_deliveries",
        sa.Column("incomplete_reason", sa.String(length=100), nullable=True),
    )

    op.add_column(
        "pull_requests",
        sa.Column("github_updated_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "pull_requests",
        sa.Column("head_sha", sa.String(length=64), nullable=True),
    )
    op.add_column(
        "pull_requests",
        sa.Column("last_processed_delivery_id", sa.String(length=255), nullable=True),
    )
    op.add_column(
        "pull_requests",
        sa.Column("last_synchronized_head_sha", sa.String(length=64), nullable=True),
    )
    op.add_column(
        "pull_requests",
        sa.Column(
            "file_sync_complete",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
    )
    op.add_column(
        "pull_requests",
        sa.Column("incomplete_reason", sa.String(length=100), nullable=True),
    )
    op.add_column(
        "pull_requests",
        sa.Column("synchronized_at", sa.DateTime(), nullable=True),
    )
    op.create_index("ix_pull_requests_head_sha", "pull_requests", ["head_sha"])

    op.add_column(
        "pull_request_files",
        sa.Column("previous_filename", sa.String(length=1024), nullable=True),
    )
    op.add_column(
        "pull_request_files",
        sa.Column(
            "github_status",
            sa.String(length=32),
            nullable=False,
            server_default="modified",
        ),
    )
    op.add_column(
        "pull_request_files",
        sa.Column("sha", sa.String(length=64), nullable=True),
    )
    op.add_column(
        "pull_request_files",
        sa.Column("changes", sa.Integer(), nullable=False, server_default="0"),
    )
    op.add_column(
        "pull_request_files",
        sa.Column(
            "patch_available",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
    )
    op.add_column(
        "pull_request_files",
        sa.Column(
            "patch_status",
            sa.String(length=32),
            nullable=False,
            server_default="not_returned",
        ),
    )
    op.add_column(
        "pull_request_files",
        sa.Column("contents_url", sa.String(length=2048), nullable=True),
    )
    op.add_column(
        "pull_request_files",
        sa.Column("blob_url", sa.String(length=2048), nullable=True),
    )
    op.add_column(
        "pull_request_files",
        sa.Column("raw_url", sa.String(length=2048), nullable=True),
    )
    op.add_column(
        "pull_request_files",
        sa.Column(
            "first_seen_at",
            sa.DateTime(),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )
    op.add_column(
        "pull_request_files",
        sa.Column(
            "last_seen_at",
            sa.DateTime(),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )
    op.add_column(
        "pull_request_files",
        sa.Column(
            "is_current",
            sa.Boolean(),
            nullable=False,
            server_default=sa.true(),
        ),
    )
    op.add_column(
        "pull_request_files",
        sa.Column("removed_at", sa.DateTime(), nullable=True),
    )
    op.execute(
        "UPDATE pull_request_files SET "
        "changes = additions + deletions, "
        "patch_available = (patch IS NOT NULL), "
        "patch_status = CASE WHEN patch IS NULL THEN 'not_returned' ELSE 'available' END, "
        "first_seen_at = created_at, "
        "last_seen_at = created_at"
    )
    op.create_index(
        "ix_pull_request_files_is_current",
        "pull_request_files",
        ["is_current"],
    )
    op.create_index(
        "ix_pull_request_files_pr_current",
        "pull_request_files",
        ["pr_id", "is_current"],
    )

    op.create_table(
        "analysis_runs",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("pr_id", sa.Integer(), nullable=False),
        sa.Column("delivery_pk", sa.Integer(), nullable=False),
        sa.Column("analysis_version", sa.String(length=64), nullable=False),
        sa.Column("head_sha", sa.String(length=64), nullable=True),
        sa.Column("status", analysis_run_status, nullable=False),
        sa.Column(
            "is_authoritative",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
        sa.Column("incomplete_reason", sa.String(length=100), nullable=True),
        sa.Column("metrics_snapshot", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("completed_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(
            ["pr_id"],
            ["pull_requests.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["delivery_pk"],
            ["webhook_deliveries.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "delivery_pk",
            "analysis_version",
            name="uq_analysis_runs_delivery_version",
        ),
    )
    op.create_index("ix_analysis_runs_id", "analysis_runs", ["id"])
    op.create_index("ix_analysis_runs_pr_id", "analysis_runs", ["pr_id"])
    op.create_index("ix_analysis_runs_delivery_pk", "analysis_runs", ["delivery_pk"])


def downgrade() -> None:
    op.drop_table("analysis_runs")

    op.drop_index("ix_pull_request_files_pr_current", table_name="pull_request_files")
    op.drop_index("ix_pull_request_files_is_current", table_name="pull_request_files")
    op.drop_column("pull_request_files", "removed_at")
    op.drop_column("pull_request_files", "is_current")
    op.drop_column("pull_request_files", "last_seen_at")
    op.drop_column("pull_request_files", "first_seen_at")
    op.drop_column("pull_request_files", "raw_url")
    op.drop_column("pull_request_files", "blob_url")
    op.drop_column("pull_request_files", "contents_url")
    op.drop_column("pull_request_files", "patch_status")
    op.drop_column("pull_request_files", "patch_available")
    op.drop_column("pull_request_files", "changes")
    op.drop_column("pull_request_files", "sha")
    op.drop_column("pull_request_files", "github_status")
    op.drop_column("pull_request_files", "previous_filename")

    op.drop_index("ix_pull_requests_head_sha", table_name="pull_requests")
    op.drop_column("pull_requests", "synchronized_at")
    op.drop_column("pull_requests", "incomplete_reason")
    op.drop_column("pull_requests", "file_sync_complete")
    op.drop_column("pull_requests", "last_synchronized_head_sha")
    op.drop_column("pull_requests", "last_processed_delivery_id")
    op.drop_column("pull_requests", "head_sha")
    op.drop_column("pull_requests", "github_updated_at")
    op.drop_column("webhook_deliveries", "incomplete_reason")

    analysis_run_status.drop(op.get_bind(), checkfirst=True)
