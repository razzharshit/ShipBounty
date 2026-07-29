"""Add pull_request_files table

Revision ID: 20260430_0002
Revises: 20260429_0001
Create Date: 2026-04-30
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "20260430_0002"
down_revision: Union[str, None] = "20260429_0001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "pull_request_files",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("pr_id", sa.Integer(), nullable=False),
        sa.Column("filename", sa.String(length=1024), nullable=False),
        sa.Column("additions", sa.Integer(), nullable=False),
        sa.Column("deletions", sa.Integer(), nullable=False),
        sa.Column("patch", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["pr_id"], ["pull_requests.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("pr_id", "filename", name="uq_pull_request_files_pr_filename"),
    )
    op.create_index(op.f("ix_pull_request_files_id"), "pull_request_files", ["id"], unique=False)
    op.create_index(op.f("ix_pull_request_files_pr_id"), "pull_request_files", ["pr_id"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_pull_request_files_pr_id"), table_name="pull_request_files")
    op.drop_index(op.f("ix_pull_request_files_id"), table_name="pull_request_files")
    op.drop_table("pull_request_files")
