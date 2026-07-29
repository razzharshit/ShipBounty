"""Initial schema

Revision ID: 20260429_0001
Revises:
Create Date: 2026-04-29
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "20260429_0001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


pull_request_state = sa.Enum("open", "closed", name="pullrequeststate")


def upgrade() -> None:
    op.create_table(
        "users",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("github_id", sa.BigInteger(), nullable=False),
        sa.Column("username", sa.String(length=255), nullable=False),
        sa.Column("avatar_url", sa.String(length=512), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("github_id"),
    )
    op.create_index(op.f("ix_users_github_id"), "users", ["github_id"], unique=False)
    op.create_index(op.f("ix_users_id"), "users", ["id"], unique=False)

    op.create_table(
        "repositories",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("github_repo_id", sa.BigInteger(), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("owner", sa.String(length=255), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("github_repo_id"),
    )
    op.create_index(op.f("ix_repositories_github_repo_id"), "repositories", ["github_repo_id"], unique=False)
    op.create_index(op.f("ix_repositories_id"), "repositories", ["id"], unique=False)

    op.create_table(
        "pull_requests",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("github_pr_id", sa.BigInteger(), nullable=False),
        sa.Column("title", sa.String(length=512), nullable=False),
        sa.Column("author_id", sa.Integer(), nullable=False),
        sa.Column("repo_id", sa.Integer(), nullable=False),
        sa.Column("state", pull_request_state, nullable=False),
        sa.Column("additions", sa.Integer(), nullable=False),
        sa.Column("deletions", sa.Integer(), nullable=False),
        sa.Column("changed_files", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["author_id"], ["users.id"]),
        sa.ForeignKeyConstraint(["repo_id"], ["repositories.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("github_pr_id"),
    )
    op.create_index(op.f("ix_pull_requests_author_id"), "pull_requests", ["author_id"], unique=False)
    op.create_index(op.f("ix_pull_requests_github_pr_id"), "pull_requests", ["github_pr_id"], unique=False)
    op.create_index(op.f("ix_pull_requests_id"), "pull_requests", ["id"], unique=False)
    op.create_index(op.f("ix_pull_requests_repo_id"), "pull_requests", ["repo_id"], unique=False)

    op.create_table(
        "scores",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("pr_id", sa.Integer(), nullable=False),
        sa.Column("quality_score", sa.Float(), nullable=False),
        sa.Column("activity_score", sa.Float(), nullable=False),
        sa.Column("test_score", sa.Float(), nullable=False),
        sa.Column("final_score", sa.Float(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["pr_id"], ["pull_requests.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("pr_id"),
    )
    op.create_index(op.f("ix_scores_id"), "scores", ["id"], unique=False)
    op.create_index(op.f("ix_scores_pr_id"), "scores", ["pr_id"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_scores_pr_id"), table_name="scores")
    op.drop_index(op.f("ix_scores_id"), table_name="scores")
    op.drop_table("scores")

    op.drop_index(op.f("ix_pull_requests_repo_id"), table_name="pull_requests")
    op.drop_index(op.f("ix_pull_requests_id"), table_name="pull_requests")
    op.drop_index(op.f("ix_pull_requests_github_pr_id"), table_name="pull_requests")
    op.drop_index(op.f("ix_pull_requests_author_id"), table_name="pull_requests")
    op.drop_table("pull_requests")

    op.drop_index(op.f("ix_repositories_id"), table_name="repositories")
    op.drop_index(op.f("ix_repositories_github_repo_id"), table_name="repositories")
    op.drop_table("repositories")

    op.drop_index(op.f("ix_users_id"), table_name="users")
    op.drop_index(op.f("ix_users_github_id"), table_name="users")
    op.drop_table("users")
