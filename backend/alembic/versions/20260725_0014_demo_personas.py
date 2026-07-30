"""Add explicit demo personas and repository-scoped GitHub PR numbers.

Revision ID: 20260725_0014
Revises: 20260725_0013
Create Date: 2026-07-25
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "20260725_0014"
down_revision: Union[str, None] = "20260725_0013"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "pull_requests",
        sa.Column("github_pr_number", sa.Integer(), nullable=True),
    )
    if op.get_bind().dialect.name == "postgresql":
        op.execute(
            """
            UPDATE pull_requests AS pr
            SET github_pr_number = (
                SELECT (
                    candidate.payload -> 'pull_request' ->> 'number'
                )::integer
                FROM webhook_deliveries AS candidate
                JOIN repositories AS repository
                  ON repository.github_repo_id = candidate.repository_id
                WHERE repository.id = pr.repo_id
                  AND candidate.event_type = 'pull_request'
                  AND (
                      candidate.payload -> 'pull_request' ->> 'id'
                  )::bigint = pr.github_pr_id
                ORDER BY candidate.received_at DESC, candidate.id DESC
                LIMIT 1
            )
            WHERE pr.github_pr_number IS NULL
            """
        )
    op.create_index(
        "ix_pull_requests_github_pr_number",
        "pull_requests",
        ["github_pr_number"],
        unique=False,
    )
    op.create_unique_constraint(
        "uq_pull_requests_repo_github_pr_number",
        "pull_requests",
        ["repo_id", "github_pr_number"],
    )
    op.create_table(
        "demo_personas",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("organization_id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("persona", sa.String(length=32), nullable=False),
        sa.Column("label", sa.String(length=128), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.ForeignKeyConstraint(
            ["organization_id"], ["organizations.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "organization_id",
            "persona",
            name="uq_demo_personas_organization_persona",
        ),
        sa.UniqueConstraint(
            "organization_id",
            "user_id",
            name="uq_demo_personas_organization_user",
        ),
    )
    op.create_index(
        "ix_demo_personas_id", "demo_personas", ["id"], unique=False
    )
    op.create_index(
        "ix_demo_personas_organization_id",
        "demo_personas",
        ["organization_id"],
        unique=False,
    )
    op.create_index(
        "ix_demo_personas_user_id",
        "demo_personas",
        ["user_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_demo_personas_user_id", table_name="demo_personas")
    op.drop_index(
        "ix_demo_personas_organization_id", table_name="demo_personas"
    )
    op.drop_index("ix_demo_personas_id", table_name="demo_personas")
    op.drop_table("demo_personas")
    op.drop_constraint(
        "uq_pull_requests_repo_github_pr_number",
        "pull_requests",
        type_="unique",
    )
    op.drop_index(
        "ix_pull_requests_github_pr_number", table_name="pull_requests"
    )
    op.drop_column("pull_requests", "github_pr_number")
