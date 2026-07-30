"""Add pr_metrics table

Revision ID: 20260604_0004
Revises: 20260430_0003
Create Date: 2026-06-04
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "20260604_0004"
down_revision: Union[str, None] = "20260430_0003"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "pr_metrics",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("pr_id", sa.Integer(), nullable=False),
        sa.Column("total_files", sa.Integer(), nullable=False),
        sa.Column("total_additions", sa.Integer(), nullable=False),
        sa.Column("total_deletions", sa.Integer(), nullable=False),
        sa.Column("has_tests", sa.Boolean(), nullable=False),
        sa.Column("has_docs", sa.Boolean(), nullable=False),
        sa.Column("language_breakdown", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["pr_id"], ["pull_requests.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_pr_metrics_id"), "pr_metrics", ["id"], unique=False)
    op.create_index(op.f("ix_pr_metrics_pr_id"), "pr_metrics", ["pr_id"], unique=True)


def downgrade() -> None:
    op.drop_index(op.f("ix_pr_metrics_pr_id"), table_name="pr_metrics")
    op.drop_index(op.f("ix_pr_metrics_id"), table_name="pr_metrics")
    op.drop_table("pr_metrics")
