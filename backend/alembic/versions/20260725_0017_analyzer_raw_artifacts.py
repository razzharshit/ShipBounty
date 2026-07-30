"""Store isolated analyzer raw output separately from normalized evidence.

Revision ID: 20260725_0017
Revises: 20260725_0016
Create Date: 2026-07-25
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "20260725_0017"
down_revision: Union[str, None] = "20260725_0016"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


tool_status = postgresql.ENUM(
    "passed",
    "failed",
    "unavailable",
    "timed_out",
    "tool_error",
    name="analyzertoolstatus",
    create_type=False,
)


def upgrade() -> None:
    bind = op.get_bind()
    tool_status.create(bind, checkfirst=True)
    op.create_table(
        "analyzer_raw_artifacts",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("analyzer_result_id", sa.Integer(), nullable=False),
        sa.Column("tool_status", tool_status, nullable=False),
        sa.Column("command", sa.JSON(), nullable=False),
        sa.Column("image", sa.String(length=512), nullable=False),
        sa.Column("exit_code", sa.Integer(), nullable=True),
        sa.Column("stdout", sa.Text(), nullable=False),
        sa.Column("stderr", sa.Text(), nullable=False),
        sa.Column("output_hash", sa.String(length=64), nullable=False),
        sa.Column("duration_ms", sa.Integer(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.ForeignKeyConstraint(
            ["analyzer_result_id"],
            ["analyzer_results.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "analyzer_result_id",
            name="uq_analyzer_raw_artifacts_result",
        ),
    )
    op.create_index(
        "ix_analyzer_raw_artifacts_id",
        "analyzer_raw_artifacts",
        ["id"],
    )
    op.create_index(
        "ix_analyzer_raw_artifacts_analyzer_result_id",
        "analyzer_raw_artifacts",
        ["analyzer_result_id"],
    )
    op.create_index(
        "ix_analyzer_raw_artifacts_tool_status",
        "analyzer_raw_artifacts",
        ["tool_status"],
    )


def downgrade() -> None:
    op.drop_table("analyzer_raw_artifacts")
    tool_status.drop(op.get_bind(), checkfirst=True)
