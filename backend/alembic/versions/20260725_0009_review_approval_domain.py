"""Add policy evaluation, human review, and approval gates.

Revision ID: 20260725_0009
Revises: 20260725_0008
Create Date: 2026-07-25
"""

from typing import Sequence, Union
import hashlib
import json

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "20260725_0009"
down_revision: Union[str, None] = "20260725_0008"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


DEFAULT_RULES = {
    "require_merged": True,
    "require_authoritative_score": True,
    "minimum_score": 70.0,
    "human_review_required": True,
    "required_approvals": 1,
    "review_roles": ["owner", "admin", "maintainer", "reviewer"],
    "approval_roles": ["owner", "admin"],
    "separation_of_duties": True,
    "allow_author_review": False,
    "allow_author_approval": False,
}


def _rules_hash(rules: dict) -> str:
    encoded = json.dumps(
        rules,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    )
    return hashlib.sha256(encoded.encode()).hexdigest()


human_review_status = postgresql.ENUM(
    "pending",
    "in_progress",
    "completed",
    "cancelled",
    name="humanreviewstatus",
    create_type=False,
)
review_recommendation = postgresql.ENUM(
    "approve",
    "request_changes",
    "reject",
    name="reviewrecommendation",
    create_type=False,
)
finding_severity = postgresql.ENUM(
    "info",
    "low",
    "medium",
    "high",
    "critical",
    name="findingseverity",
    create_type=False,
)
approval_outcome = postgresql.ENUM(
    "approved",
    "rejected",
    name="approvaloutcome",
    create_type=False,
)
eligibility_decision_status = postgresql.ENUM(
    "pending_review",
    "changes_requested",
    "pending_approval",
    "eligible",
    "ineligible",
    "superseded",
    name="eligibilitydecisionstatus",
    create_type=False,
)


def upgrade() -> None:
    bind = op.get_bind()
    for enum_type in (
        human_review_status,
        review_recommendation,
        finding_severity,
        approval_outcome,
        eligibility_decision_status,
    ):
        enum_type.create(bind, checkfirst=True)

    op.create_table(
        "repository_policies",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("repository_id", sa.Integer(), nullable=False),
        sa.Column("version", sa.String(length=128), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("rules", sa.JSON(), nullable=False),
        sa.Column("policy_hash", sa.String(length=64), nullable=False),
        sa.Column("created_by_user_id", sa.Integer(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(),
            nullable=False,
            server_default=sa.func.now(),
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
            name="uq_repository_policies_repository_version",
        ),
        sa.UniqueConstraint(
            "repository_id",
            "policy_hash",
            name="uq_repository_policies_repository_hash",
        ),
    )
    op.create_index("ix_repository_policies_id", "repository_policies", ["id"])
    op.create_index(
        "ix_repository_policies_repository_id",
        "repository_policies",
        ["repository_id"],
    )

    rules_json = json.dumps(DEFAULT_RULES, sort_keys=True)
    op.execute(
        sa.text(
            """
            INSERT INTO repository_policies (
                repository_id,
                version,
                name,
                description,
                rules,
                policy_hash
            )
            SELECT
                id,
                'default-v1',
                'Default review and approval policy',
                'Merged, authoritative scores require human review and admin approval.',
                CAST(:rules AS json),
                :policy_hash
            FROM repositories
            """
        ).bindparams(rules=rules_json, policy_hash=_rules_hash(DEFAULT_RULES))
    )

    op.add_column(
        "repositories",
        sa.Column("eligibility_policy_id", sa.Integer(), nullable=True),
    )
    op.execute(
        """
        UPDATE repositories AS repository
        SET eligibility_policy_id = policy.id
        FROM repository_policies AS policy
        WHERE policy.repository_id = repository.id
          AND policy.version = 'default-v1'
        """
    )
    op.create_foreign_key(
        "fk_repositories_eligibility_policy_id",
        "repositories",
        "repository_policies",
        ["eligibility_policy_id"],
        ["id"],
        ondelete="RESTRICT",
        use_alter=True,
    )
    op.create_index(
        "ix_repositories_eligibility_policy_id",
        "repositories",
        ["eligibility_policy_id"],
    )

    op.create_table(
        "eligibility_decisions",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("pr_id", sa.Integer(), nullable=False),
        sa.Column("score_id", sa.Integer(), nullable=False),
        sa.Column("score_version_id", sa.Integer(), nullable=False),
        sa.Column("repository_policy_id", sa.Integer(), nullable=False),
        sa.Column("status", eligibility_decision_status, nullable=False),
        sa.Column(
            "is_current",
            sa.Boolean(),
            nullable=False,
            server_default=sa.true(),
        ),
        sa.Column("evaluation_result", sa.JSON(), nullable=False),
        sa.Column("failure_reasons", sa.JSON(), nullable=False),
        sa.Column("requires_human_review", sa.Boolean(), nullable=False),
        sa.Column("required_approvals", sa.Integer(), nullable=False),
        sa.Column("evaluation_hash", sa.String(length=64), nullable=False),
        sa.Column("evaluated_by_user_id", sa.Integer(), nullable=True),
        sa.Column("final_approved_by_user_id", sa.Integer(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column("finalized_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(
            ["pr_id"], ["pull_requests.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["score_id"], ["scores.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["score_version_id"], ["score_versions.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["repository_policy_id"],
            ["repository_policies.id"],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["evaluated_by_user_id"], ["users.id"], ondelete="SET NULL"
        ),
        sa.ForeignKeyConstraint(
            ["final_approved_by_user_id"], ["users.id"], ondelete="SET NULL"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("evaluation_hash"),
    )
    for column in (
        "id",
        "pr_id",
        "score_id",
        "score_version_id",
        "repository_policy_id",
        "status",
        "is_current",
    ):
        op.create_index(
            f"ix_eligibility_decisions_{column}",
            "eligibility_decisions",
            [column],
        )
    op.create_index(
        "uq_eligibility_decisions_current_pr",
        "eligibility_decisions",
        ["pr_id"],
        unique=True,
        postgresql_where=sa.text("is_current"),
    )

    op.create_table(
        "reviews",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("eligibility_decision_id", sa.Integer(), nullable=False),
        sa.Column("reviewer_user_id", sa.Integer(), nullable=False),
        sa.Column("status", human_review_status, nullable=False),
        sa.Column("recommendation", review_recommendation, nullable=True),
        sa.Column("summary", sa.Text(), nullable=True),
        sa.Column(
            "started_at",
            sa.DateTime(),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column("completed_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(
            ["eligibility_decision_id"],
            ["eligibility_decisions.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["reviewer_user_id"], ["users.id"], ondelete="RESTRICT"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    for column in ("id", "eligibility_decision_id", "reviewer_user_id", "status"):
        op.create_index(f"ix_reviews_{column}", "reviews", [column])

    op.create_table(
        "review_findings",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("review_id", sa.Integer(), nullable=False),
        sa.Column("severity", finding_severity, nullable=False),
        sa.Column("category", sa.String(length=64), nullable=False),
        sa.Column("code", sa.String(length=128), nullable=False),
        sa.Column("message", sa.Text(), nullable=False),
        sa.Column("evidence", sa.JSON(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.ForeignKeyConstraint(
            ["review_id"], ["reviews.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_review_findings_id", "review_findings", ["id"])
    op.create_index(
        "ix_review_findings_review_id", "review_findings", ["review_id"]
    )
    op.create_index(
        "ix_review_findings_severity", "review_findings", ["severity"]
    )

    op.create_table(
        "approvals",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("eligibility_decision_id", sa.Integer(), nullable=False),
        sa.Column("approver_user_id", sa.Integer(), nullable=False),
        sa.Column("outcome", approval_outcome, nullable=False),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column("score_id", sa.Integer(), nullable=False),
        sa.Column("score_version_id", sa.Integer(), nullable=False),
        sa.Column("repository_policy_id", sa.Integer(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.ForeignKeyConstraint(
            ["eligibility_decision_id"],
            ["eligibility_decisions.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["approver_user_id"], ["users.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["score_id"], ["scores.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["score_version_id"], ["score_versions.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["repository_policy_id"],
            ["repository_policies.id"],
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "eligibility_decision_id",
            "approver_user_id",
            name="uq_approvals_decision_approver",
        ),
    )
    for column in (
        "id",
        "eligibility_decision_id",
        "approver_user_id",
        "outcome",
    ):
        op.create_index(f"ix_approvals_{column}", "approvals", [column])

    # Phase 4 decisions, rather than mutable input or a score, now control these
    # non-terminal eligibility values. Paid/claimed rows are preserved.
    op.execute(
        """
        UPDATE pull_requests
        SET eligibility_state = 'not_evaluated'
        WHERE eligibility_state::text IN ('eligible', 'ineligible')
        """
    )

    op.execute(
        """
        CREATE FUNCTION prevent_review_domain_change()
        RETURNS trigger AS $$
        BEGIN
            RAISE EXCEPTION '% records are immutable', TG_TABLE_NAME;
        END;
        $$ LANGUAGE plpgsql
        """
    )
    for table_name in ("repository_policies", "review_findings", "approvals"):
        op.execute(
            f"""
            CREATE TRIGGER trg_{table_name}_immutable
            BEFORE UPDATE OR DELETE ON {table_name}
            FOR EACH ROW EXECUTE FUNCTION prevent_review_domain_change()
            """
        )
    op.execute(
        """
        CREATE FUNCTION prevent_terminal_review_change()
        RETURNS trigger AS $$
        BEGIN
            IF OLD.status::text IN ('completed', 'cancelled') THEN
                RAISE EXCEPTION 'terminal reviews are immutable';
            END IF;
            IF TG_OP = 'DELETE' THEN
                RETURN OLD;
            END IF;
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql
        """
    )
    op.execute(
        """
        CREATE TRIGGER trg_reviews_terminal_immutable
        BEFORE UPDATE OR DELETE ON reviews
        FOR EACH ROW EXECUTE FUNCTION prevent_terminal_review_change()
        """
    )
def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS trg_reviews_terminal_immutable ON reviews")
    op.execute("DROP FUNCTION IF EXISTS prevent_terminal_review_change()")
    for table_name in ("repository_policies", "review_findings", "approvals"):
        op.execute(
            f"DROP TRIGGER IF EXISTS trg_{table_name}_immutable ON {table_name}"
        )
    op.execute("DROP FUNCTION IF EXISTS prevent_review_domain_change()")

    op.drop_table("approvals")
    op.drop_table("review_findings")
    op.drop_table("reviews")
    op.drop_table("eligibility_decisions")

    op.drop_index(
        "ix_repositories_eligibility_policy_id", table_name="repositories"
    )
    op.drop_constraint(
        "fk_repositories_eligibility_policy_id",
        "repositories",
        type_="foreignkey",
    )
    op.drop_column("repositories", "eligibility_policy_id")
    op.drop_table("repository_policies")

    for enum_type in (
        eligibility_decision_status,
        approval_outcome,
        finding_severity,
        review_recommendation,
        human_review_status,
    ):
        enum_type.drop(op.get_bind(), checkfirst=True)
