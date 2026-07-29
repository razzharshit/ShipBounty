"""Add issues, bounty policies, claims, and idempotent payouts.

Revision ID: 20260725_0010
Revises: 20260725_0009
Create Date: 2026-07-25
"""

from typing import Sequence, Union
import hashlib
import json

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "20260725_0010"
down_revision: Union[str, None] = "20260725_0009"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

DEFAULT_RULES = {
    "allowed_currencies": ["USDC"],
    "minimum_amount": 1.0,
    "maximum_amount": 10000.0,
    "require_funding": True,
    "require_assignment": True,
    "require_verified_wallet": True,
    "require_current_eligibility": True,
}


def _hash(value: dict) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def _enum(name: str, *values: str):
    return postgresql.ENUM(*values, name=name, create_type=False)


issue_state = _enum("issuestate", "open", "closed")
bounty_status = _enum(
    "bountystatus", "draft", "open", "assigned", "closed", "paid", "cancelled", "expired"
)
funding_status = _enum(
    "fundingstatus", "unfunded", "pending", "funded", "exhausted", "refunded"
)
assignment_status = _enum("assignmentstatus", "active", "completed", "cancelled")
claim_status = _enum("claimstatus", "approved", "rejected", "cancelled", "paid")
wallet_status = _enum("walletstatus", "active", "inactive")
payout_state = _enum(
    "payoutstate",
    "created",
    "authorized",
    "submitting",
    "submitted",
    "confirmed",
    "failed",
    "cancelled",
)
payout_attempt_state = _enum(
    "payoutattemptstate", "submitting", "submitted", "failed"
)


def _indexes(table: str, columns: tuple[str, ...]) -> None:
    for column in columns:
        op.create_index(f"ix_{table}_{column}", table, [column])


def upgrade() -> None:
    bind = op.get_bind()
    for enum_type in (
        issue_state,
        bounty_status,
        funding_status,
        assignment_status,
        claim_status,
        wallet_status,
        payout_state,
        payout_attempt_state,
    ):
        enum_type.create(bind, checkfirst=True)

    op.create_table(
        "bounty_policies",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("organization_id", sa.Integer(), nullable=False),
        sa.Column("repository_id", sa.Integer(), nullable=False),
        sa.Column("version", sa.String(128), nullable=False),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("rules", sa.JSON(), nullable=False),
        sa.Column("policy_hash", sa.String(64), nullable=False),
        sa.Column("created_by_user_id", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["repository_id"], ["repositories.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["created_by_user_id"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "repository_id", "version", name="uq_bounty_policies_repository_version"
        ),
        sa.UniqueConstraint(
            "repository_id", "policy_hash", name="uq_bounty_policies_repository_hash"
        ),
    )
    _indexes("bounty_policies", ("id", "organization_id", "repository_id"))
    op.execute(
        sa.text(
            """
            INSERT INTO bounty_policies (
                organization_id, repository_id, version, name, rules, policy_hash
            )
            SELECT organization_id, id, 'default-v1',
                   'Default funded bounty policy', CAST(:rules AS json), :digest
            FROM repositories
            """
        ).bindparams(
            rules=json.dumps(DEFAULT_RULES, sort_keys=True),
            digest=_hash(DEFAULT_RULES),
        )
    )
    op.add_column(
        "repositories", sa.Column("bounty_policy_id", sa.Integer(), nullable=True)
    )
    op.execute(
        """
        UPDATE repositories AS repository
        SET bounty_policy_id = policy.id
        FROM bounty_policies AS policy
        WHERE policy.repository_id = repository.id
          AND policy.version = 'default-v1'
        """
    )
    op.create_foreign_key(
        "fk_repositories_bounty_policy_id",
        "repositories",
        "bounty_policies",
        ["bounty_policy_id"],
        ["id"],
        ondelete="RESTRICT",
        use_alter=True,
    )
    op.create_index(
        "ix_repositories_bounty_policy_id", "repositories", ["bounty_policy_id"]
    )

    op.create_table(
        "issues",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("organization_id", sa.Integer(), nullable=False),
        sa.Column("repository_id", sa.Integer(), nullable=False),
        sa.Column("github_issue_id", sa.BigInteger(), nullable=False),
        sa.Column("number", sa.Integer(), nullable=False),
        sa.Column("title", sa.String(512), nullable=False),
        sa.Column("url", sa.String(2048), nullable=True),
        sa.Column("state", issue_state, nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["repository_id"], ["repositories.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "repository_id", "github_issue_id", name="uq_issues_repository_github_id"
        ),
        sa.UniqueConstraint(
            "repository_id", "number", name="uq_issues_repository_number"
        ),
    )
    _indexes("issues", ("id", "organization_id", "repository_id", "state"))

    op.create_table(
        "bounties",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("organization_id", sa.Integer(), nullable=False),
        sa.Column("repository_id", sa.Integer(), nullable=False),
        sa.Column("issue_id", sa.Integer(), nullable=False),
        sa.Column("bounty_policy_id", sa.Integer(), nullable=False),
        sa.Column("eligibility_policy_id", sa.Integer(), nullable=False),
        sa.Column("amount", sa.Numeric(18, 6), nullable=False),
        sa.Column("currency", sa.String(16), nullable=False),
        sa.Column("status", bounty_status, nullable=False),
        sa.Column("funding_status", funding_status, nullable=False),
        sa.Column("expires_at", sa.DateTime(), nullable=True),
        sa.Column("created_by_user_id", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["repository_id"], ["repositories.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["issue_id"], ["issues.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["bounty_policy_id"], ["bounty_policies.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["eligibility_policy_id"], ["repository_policies.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["created_by_user_id"], ["users.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
    )
    _indexes(
        "bounties",
        (
            "id",
            "organization_id",
            "repository_id",
            "issue_id",
            "bounty_policy_id",
            "eligibility_policy_id",
            "status",
            "funding_status",
        ),
    )

    op.create_table(
        "bounty_assignments",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("bounty_id", sa.Integer(), nullable=False),
        sa.Column("assignee_user_id", sa.Integer(), nullable=False),
        sa.Column("pull_request_id", sa.Integer(), nullable=True),
        sa.Column("status", assignment_status, nullable=False),
        sa.Column("assigned_by_user_id", sa.Integer(), nullable=False),
        sa.Column("assigned_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("completed_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["bounty_id"], ["bounties.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["assignee_user_id"], ["users.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["pull_request_id"], ["pull_requests.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["assigned_by_user_id"], ["users.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
    )
    _indexes(
        "bounty_assignments",
        ("id", "bounty_id", "assignee_user_id", "pull_request_id", "status"),
    )
    op.create_index(
        "uq_bounty_assignments_active_bounty",
        "bounty_assignments",
        ["bounty_id"],
        unique=True,
        postgresql_where=sa.text("status = 'active'"),
    )

    op.create_table(
        "wallets",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("chain", sa.String(64), nullable=False),
        sa.Column("address", sa.String(255), nullable=False),
        sa.Column("normalized_address", sa.String(255), nullable=False),
        sa.Column("status", wallet_status, nullable=False),
        sa.Column("verified", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "user_id", "chain", "normalized_address", name="uq_wallets_user_chain_address"
        ),
    )
    _indexes("wallets", ("id", "user_id", "status"))

    op.create_table(
        "claims",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("bounty_id", sa.Integer(), nullable=False),
        sa.Column("assignment_id", sa.Integer(), nullable=False),
        sa.Column("pull_request_id", sa.Integer(), nullable=False),
        sa.Column("eligibility_decision_id", sa.Integer(), nullable=False),
        sa.Column("approval_id", sa.Integer(), nullable=False),
        sa.Column("claimant_user_id", sa.Integer(), nullable=False),
        sa.Column("wallet_id", sa.Integer(), nullable=False),
        sa.Column("amount", sa.Numeric(18, 6), nullable=False),
        sa.Column("currency", sa.String(16), nullable=False),
        sa.Column("destination_chain", sa.String(64), nullable=False),
        sa.Column("destination_address", sa.String(255), nullable=False),
        sa.Column("status", claim_status, nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["bounty_id"], ["bounties.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["assignment_id"], ["bounty_assignments.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["pull_request_id"], ["pull_requests.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["eligibility_decision_id"], ["eligibility_decisions.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["approval_id"], ["approvals.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["claimant_user_id"], ["users.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["wallet_id"], ["wallets.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
    )
    _indexes(
        "claims",
        (
            "id",
            "bounty_id",
            "assignment_id",
            "pull_request_id",
            "eligibility_decision_id",
            "approval_id",
            "claimant_user_id",
            "status",
        ),
    )
    op.create_index(
        "uq_claims_payable_bounty",
        "claims",
        ["bounty_id"],
        unique=True,
        postgresql_where=sa.text("status IN ('approved', 'paid')"),
    )

    op.create_table(
        "payouts",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("claim_id", sa.Integer(), nullable=False),
        sa.Column("approval_id", sa.Integer(), nullable=False),
        sa.Column("amount", sa.Numeric(18, 6), nullable=False),
        sa.Column("currency", sa.String(16), nullable=False),
        sa.Column("destination_chain", sa.String(64), nullable=False),
        sa.Column("destination_address", sa.String(255), nullable=False),
        sa.Column("idempotency_key", sa.String(128), nullable=False),
        sa.Column("state", payout_state, nullable=False),
        sa.Column("authorized_by_user_id", sa.Integer(), nullable=True),
        sa.Column("authorized_at", sa.DateTime(), nullable=True),
        sa.Column("transaction_hash", sa.String(255), nullable=True),
        sa.Column("confirmed_at", sa.DateTime(), nullable=True),
        sa.Column("failure_reason", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["claim_id"], ["claims.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["approval_id"], ["approvals.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["authorized_by_user_id"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("claim_id", name="uq_payouts_claim"),
        sa.UniqueConstraint("idempotency_key", name="uq_payouts_idempotency_key"),
    )
    _indexes("payouts", ("id", "claim_id", "approval_id", "state"))

    op.create_table(
        "payout_attempts",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("payout_id", sa.Integer(), nullable=False),
        sa.Column("attempt_number", sa.Integer(), nullable=False),
        sa.Column("idempotency_key", sa.String(128), nullable=False),
        sa.Column("state", payout_attempt_state, nullable=False),
        sa.Column("provider", sa.String(64), nullable=False),
        sa.Column("request_hash", sa.String(64), nullable=False),
        sa.Column("transaction_hash", sa.String(255), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("submitted_at", sa.DateTime(), nullable=True),
        sa.Column("completed_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["payout_id"], ["payouts.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("payout_id", "attempt_number", name="uq_payout_attempts_number"),
        sa.UniqueConstraint("idempotency_key", name="uq_payout_attempts_idempotency_key"),
    )
    _indexes("payout_attempts", ("id", "payout_id", "state"))

    op.execute(
        """
        CREATE FUNCTION prevent_bounty_policy_mutation()
        RETURNS trigger AS $$
        BEGIN
            RAISE EXCEPTION 'bounty policies are immutable';
        END;
        $$ LANGUAGE plpgsql
        """
    )
    op.execute(
        """
        CREATE FUNCTION protect_claim_financial_snapshot()
        RETURNS trigger AS $$
        BEGIN
            IF TG_OP = 'DELETE' THEN
                RAISE EXCEPTION 'claim authorization snapshot is immutable';
            END IF;
            IF (
                OLD.bounty_id IS DISTINCT FROM NEW.bounty_id OR
                OLD.assignment_id IS DISTINCT FROM NEW.assignment_id OR
                OLD.pull_request_id IS DISTINCT FROM NEW.pull_request_id OR
                OLD.eligibility_decision_id IS DISTINCT FROM NEW.eligibility_decision_id OR
                OLD.approval_id IS DISTINCT FROM NEW.approval_id OR
                OLD.claimant_user_id IS DISTINCT FROM NEW.claimant_user_id OR
                OLD.wallet_id IS DISTINCT FROM NEW.wallet_id OR
                OLD.amount IS DISTINCT FROM NEW.amount OR
                OLD.currency IS DISTINCT FROM NEW.currency OR
                OLD.destination_chain IS DISTINCT FROM NEW.destination_chain OR
                OLD.destination_address IS DISTINCT FROM NEW.destination_address
            ) THEN
                RAISE EXCEPTION 'claim authorization snapshot is immutable';
            END IF;
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql
        """
    )
    op.execute(
        """
        CREATE FUNCTION protect_payout_financial_snapshot()
        RETURNS trigger AS $$
        BEGIN
            IF TG_OP = 'DELETE' THEN
                RAISE EXCEPTION 'payout authorization snapshot is immutable';
            END IF;
            IF (
                OLD.claim_id IS DISTINCT FROM NEW.claim_id OR
                OLD.approval_id IS DISTINCT FROM NEW.approval_id OR
                OLD.amount IS DISTINCT FROM NEW.amount OR
                OLD.currency IS DISTINCT FROM NEW.currency OR
                OLD.destination_chain IS DISTINCT FROM NEW.destination_chain OR
                OLD.destination_address IS DISTINCT FROM NEW.destination_address OR
                OLD.idempotency_key IS DISTINCT FROM NEW.idempotency_key
            ) THEN
                RAISE EXCEPTION 'payout authorization snapshot is immutable';
            END IF;
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql
        """
    )
    op.execute(
        """
        CREATE TRIGGER trg_bounty_policies_financial_snapshot
        BEFORE UPDATE OR DELETE ON bounty_policies
        FOR EACH ROW EXECUTE FUNCTION prevent_bounty_policy_mutation()
        """
    )
    op.execute(
        """
        CREATE TRIGGER trg_claims_financial_snapshot
        BEFORE UPDATE OR DELETE ON claims
        FOR EACH ROW EXECUTE FUNCTION protect_claim_financial_snapshot()
        """
    )
    op.execute(
        """
        CREATE TRIGGER trg_payouts_financial_snapshot
        BEFORE UPDATE OR DELETE ON payouts
        FOR EACH ROW EXECUTE FUNCTION protect_payout_financial_snapshot()
        """
    )


def downgrade() -> None:
    for table in ("bounty_policies", "claims", "payouts"):
        op.execute(f"DROP TRIGGER IF EXISTS trg_{table}_financial_snapshot ON {table}")
    op.execute("DROP FUNCTION IF EXISTS protect_payout_financial_snapshot()")
    op.execute("DROP FUNCTION IF EXISTS protect_claim_financial_snapshot()")
    op.execute("DROP FUNCTION IF EXISTS prevent_bounty_policy_mutation()")
    op.execute("DROP FUNCTION IF EXISTS protect_bounty_financial_snapshots()")
    for table in (
        "payout_attempts",
        "payouts",
        "claims",
        "wallets",
        "bounty_assignments",
        "bounties",
        "issues",
    ):
        op.drop_table(table)
    op.drop_index("ix_repositories_bounty_policy_id", table_name="repositories")
    op.drop_constraint(
        "fk_repositories_bounty_policy_id", "repositories", type_="foreignkey"
    )
    op.drop_column("repositories", "bounty_policy_id")
    op.drop_table("bounty_policies")
    for enum_type in (
        payout_attempt_state,
        payout_state,
        wallet_status,
        claim_status,
        assignment_status,
        funding_status,
        bounty_status,
        issue_state,
    ):
        enum_type.drop(op.get_bind(), checkfirst=True)
