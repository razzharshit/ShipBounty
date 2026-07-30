"""Add privacy-aware, advisory AI review records.

Revision ID: 20260725_0011
Revises: 20260725_0010
Create Date: 2026-07-25
"""

from typing import Sequence, Union
import hashlib
import json

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "20260725_0011"
down_revision: Union[str, None] = "20260725_0010"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

DEFAULT_RULES = {
    "enabled": True,
    "allow_external_providers": True,
    "allow_private_repository_external": False,
    "include_patch_chunks": True,
    "max_patch_files": 12,
    "max_patch_characters": 12000,
    "max_summary_files": 250,
}


def _hash(value: dict) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


provider_kind = postgresql.ENUM(
    "local", "external", name="aiproviderkind", create_type=False
)
review_status = postgresql.ENUM(
    "pending", "complete", "failed", "blocked",
    name="aireviewstatus",
    create_type=False,
)


def upgrade() -> None:
    bind = op.get_bind()
    provider_kind.create(bind, checkfirst=True)
    review_status.create(bind, checkfirst=True)

    op.add_column(
        "pull_requests", sa.Column("description", sa.Text(), nullable=True)
    )
    op.add_column("issues", sa.Column("description", sa.Text(), nullable=True))

    op.create_table(
        "ai_review_policies",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("repository_id", sa.Integer(), nullable=False),
        sa.Column("version", sa.String(128), nullable=False),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("rules", sa.JSON(), nullable=False),
        sa.Column("policy_hash", sa.String(64), nullable=False),
        sa.Column("created_by_user_id", sa.Integer(), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()
        ),
        sa.ForeignKeyConstraint(
            ["repository_id"], ["repositories.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["created_by_user_id"], ["users.id"], ondelete="SET NULL"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "repository_id",
            "version",
            name="uq_ai_review_policies_repository_version",
        ),
        sa.UniqueConstraint(
            "repository_id",
            "policy_hash",
            name="uq_ai_review_policies_repository_hash",
        ),
    )
    op.create_index(
        "ix_ai_review_policies_id", "ai_review_policies", ["id"]
    )
    op.create_index(
        "ix_ai_review_policies_repository_id",
        "ai_review_policies",
        ["repository_id"],
    )
    op.execute(
        sa.text(
            """
            INSERT INTO ai_review_policies (
                repository_id, version, name, rules, policy_hash
            )
            SELECT id, 'default-v1',
                   'Default advisory AI and source privacy policy',
                   CAST(:rules AS json), :digest
            FROM repositories
            """
        ).bindparams(
            rules=json.dumps(DEFAULT_RULES, sort_keys=True),
            digest=_hash(DEFAULT_RULES),
        )
    )
    op.add_column(
        "repositories", sa.Column("ai_review_policy_id", sa.Integer(), nullable=True)
    )
    op.execute(
        """
        UPDATE repositories AS repository
        SET ai_review_policy_id = policy.id
        FROM ai_review_policies AS policy
        WHERE policy.repository_id = repository.id
          AND policy.version = 'default-v1'
        """
    )
    op.create_foreign_key(
        "fk_repositories_ai_review_policy_id",
        "repositories",
        "ai_review_policies",
        ["ai_review_policy_id"],
        ["id"],
        ondelete="RESTRICT",
        use_alter=True,
    )
    op.create_index(
        "ix_repositories_ai_review_policy_id",
        "repositories",
        ["ai_review_policy_id"],
    )

    op.create_table(
        "ai_reviews",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("pr_id", sa.Integer(), nullable=False),
        sa.Column("analysis_run_id", sa.Integer(), nullable=False),
        sa.Column("repository_policy_id", sa.Integer(), nullable=False),
        sa.Column("ai_review_policy_id", sa.Integer(), nullable=False),
        sa.Column("requested_by_user_id", sa.Integer(), nullable=True),
        sa.Column("provider", sa.String(128), nullable=False),
        sa.Column("model", sa.String(255), nullable=False),
        sa.Column("provider_kind", provider_kind, nullable=False),
        sa.Column("prompt_version", sa.String(128), nullable=False),
        sa.Column("input_commit_sha", sa.String(64), nullable=False),
        sa.Column("input_snapshot", sa.JSON(), nullable=False),
        sa.Column("input_hash", sa.String(64), nullable=False),
        sa.Column("privacy_decision", sa.JSON(), nullable=False),
        sa.Column("status", review_status, nullable=False),
        sa.Column("output", sa.JSON(), nullable=True),
        sa.Column("provider_request_id", sa.String(255), nullable=True),
        sa.Column("prompt_tokens", sa.Integer(), nullable=True),
        sa.Column("completion_tokens", sa.Integer(), nullable=True),
        sa.Column("total_tokens", sa.Integer(), nullable=True),
        sa.Column("cost_amount", sa.Numeric(18, 8), nullable=True),
        sa.Column("cost_currency", sa.String(16), nullable=True),
        sa.Column("moderation_result", sa.JSON(), nullable=True),
        sa.Column("failure_reason", sa.Text(), nullable=True),
        sa.Column(
            "advisory_only", sa.Boolean(), nullable=False, server_default=sa.true()
        ),
        sa.Column("review_key", sa.String(64), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()
        ),
        sa.Column("completed_at", sa.DateTime(), nullable=True),
        sa.CheckConstraint("advisory_only", name="ck_ai_reviews_advisory_only"),
        sa.ForeignKeyConstraint(
            ["pr_id"], ["pull_requests.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["analysis_run_id"], ["analysis_runs.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["repository_policy_id"], ["repository_policies.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["ai_review_policy_id"], ["ai_review_policies.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["requested_by_user_id"], ["users.id"], ondelete="SET NULL"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("review_key", name="uq_ai_reviews_review_key"),
    )
    for column in (
        "id",
        "pr_id",
        "analysis_run_id",
        "repository_policy_id",
        "ai_review_policy_id",
        "input_commit_sha",
        "input_hash",
        "status",
    ):
        op.create_index(f"ix_ai_reviews_{column}", "ai_reviews", [column])
    op.create_index(
        "ix_ai_reviews_pr_status", "ai_reviews", ["pr_id", "status"]
    )

    op.execute(
        """
        CREATE FUNCTION prevent_ai_review_policy_mutation()
        RETURNS trigger AS $$
        BEGIN
            RAISE EXCEPTION 'AI review policies are immutable';
        END;
        $$ LANGUAGE plpgsql
        """
    )
    op.execute(
        """
        CREATE FUNCTION protect_ai_review_record()
        RETURNS trigger AS $$
        BEGIN
            IF TG_OP = 'DELETE' THEN
                RAISE EXCEPTION 'AI review records are immutable';
            END IF;
            IF OLD.status IN ('complete', 'failed', 'blocked') THEN
                RAISE EXCEPTION 'terminal AI review records are immutable';
            END IF;
            IF (
                OLD.pr_id IS DISTINCT FROM NEW.pr_id OR
                OLD.analysis_run_id IS DISTINCT FROM NEW.analysis_run_id OR
                OLD.repository_policy_id IS DISTINCT FROM NEW.repository_policy_id OR
                OLD.ai_review_policy_id IS DISTINCT FROM NEW.ai_review_policy_id OR
                OLD.requested_by_user_id IS DISTINCT FROM NEW.requested_by_user_id OR
                OLD.provider IS DISTINCT FROM NEW.provider OR
                OLD.model IS DISTINCT FROM NEW.model OR
                OLD.provider_kind IS DISTINCT FROM NEW.provider_kind OR
                OLD.prompt_version IS DISTINCT FROM NEW.prompt_version OR
                OLD.input_commit_sha IS DISTINCT FROM NEW.input_commit_sha OR
                OLD.input_snapshot::text IS DISTINCT FROM NEW.input_snapshot::text OR
                OLD.input_hash IS DISTINCT FROM NEW.input_hash OR
                OLD.privacy_decision::text IS DISTINCT FROM NEW.privacy_decision::text OR
                OLD.advisory_only IS DISTINCT FROM NEW.advisory_only OR
                OLD.review_key IS DISTINCT FROM NEW.review_key
            ) THEN
                RAISE EXCEPTION 'AI review provenance is immutable';
            END IF;
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql
        """
    )
    op.execute(
        """
        CREATE TRIGGER trg_ai_review_policies_immutable
        BEFORE UPDATE OR DELETE ON ai_review_policies
        FOR EACH ROW EXECUTE FUNCTION prevent_ai_review_policy_mutation()
        """
    )
    op.execute(
        """
        CREATE TRIGGER trg_ai_reviews_immutable
        BEFORE UPDATE OR DELETE ON ai_reviews
        FOR EACH ROW EXECUTE FUNCTION protect_ai_review_record()
        """
    )


def downgrade() -> None:
    op.execute(
        "DROP TRIGGER IF EXISTS trg_ai_reviews_immutable ON ai_reviews"
    )
    op.execute(
        "DROP TRIGGER IF EXISTS trg_ai_review_policies_immutable ON ai_review_policies"
    )
    op.execute("DROP FUNCTION IF EXISTS protect_ai_review_record()")
    op.execute("DROP FUNCTION IF EXISTS prevent_ai_review_policy_mutation()")
    op.drop_table("ai_reviews")
    op.drop_index(
        "ix_repositories_ai_review_policy_id", table_name="repositories"
    )
    op.drop_constraint(
        "fk_repositories_ai_review_policy_id",
        "repositories",
        type_="foreignkey",
    )
    op.drop_column("repositories", "ai_review_policy_id")
    op.drop_table("ai_review_policies")
    op.drop_column("issues", "description")
    op.drop_column("pull_requests", "description")
    review_status.drop(op.get_bind(), checkfirst=True)
    provider_kind.drop(op.get_bind(), checkfirst=True)
