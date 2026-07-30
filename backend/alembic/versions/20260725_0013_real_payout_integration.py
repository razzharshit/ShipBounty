"""Add provider-neutral treasury controls and payout ledger.

Revision ID: 20260725_0013
Revises: 20260725_0012
Create Date: 2026-07-25
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "20260725_0013"
down_revision: Union[str, None] = "20260725_0012"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _enum(name: str, *values: str):
    return postgresql.ENUM(*values, name=name, create_type=False)


treasury_environment = _enum("treasuryenvironment", "testnet", "mainnet")
treasury_status = _enum("treasurystatus", "active", "paused")
treasury_approval_decision = _enum(
    "treasuryapprovaldecision", "approved", "rejected"
)
ledger_entry_type = _enum(
    "ledgerentrytype",
    "reservation",
    "release",
    "settlement",
    "reconciliation_adjustment",
)
reconciliation_outcome = _enum(
    "reconciliationoutcome",
    "pending",
    "submitted",
    "confirmed",
    "failed",
    "error",
)


def _indexes(table: str, *columns: str) -> None:
    for column in columns:
        op.create_index(f"ix_{table}_{column}", table, [column])


def _install_payout_snapshot_trigger() -> None:
    op.execute(
        """
        CREATE OR REPLACE FUNCTION protect_payout_financial_snapshot()
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
                OLD.idempotency_key IS DISTINCT FROM NEW.idempotency_key OR
                OLD.treasury_account_id IS DISTINCT FROM NEW.treasury_account_id OR
                OLD.provider_key IS DISTINCT FROM NEW.provider_key OR
                OLD.required_confirmations IS DISTINCT FROM NEW.required_confirmations
            ) THEN
                RAISE EXCEPTION 'payout authorization snapshot is immutable';
            END IF;
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql
        """
    )


def _restore_payout_snapshot_trigger() -> None:
    op.execute(
        """
        CREATE OR REPLACE FUNCTION protect_payout_financial_snapshot()
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


def upgrade() -> None:
    bind = op.get_bind()
    for enum_type in (
        treasury_environment,
        treasury_status,
        treasury_approval_decision,
        ledger_entry_type,
        reconciliation_outcome,
    ):
        enum_type.create(bind, checkfirst=True)

    op.create_table(
        "treasury_accounts",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("organization_id", sa.Integer(), nullable=False),
        sa.Column("provider_key", sa.String(64), nullable=False),
        sa.Column("environment", treasury_environment, nullable=False),
        sa.Column("chain", sa.String(64), nullable=False),
        sa.Column("currency", sa.String(16), nullable=False),
        sa.Column("treasury_address", sa.String(255), nullable=False),
        sa.Column("asset_contract_address", sa.String(255), nullable=True),
        sa.Column("asset_decimals", sa.Integer(), nullable=False, server_default="6"),
        sa.Column(
            "custody_model",
            sa.String(32),
            nullable=False,
            server_default="multisig",
        ),
        sa.Column(
            "opening_balance",
            sa.Numeric(24, 6),
            nullable=False,
            server_default="0",
        ),
        sa.Column("observed_balance", sa.Numeric(24, 6), nullable=True),
        sa.Column("per_payout_limit", sa.Numeric(24, 6), nullable=False),
        sa.Column("daily_spending_limit", sa.Numeric(24, 6), nullable=False),
        sa.Column("manual_approval_threshold", sa.Numeric(24, 6), nullable=True),
        sa.Column(
            "standard_required_approvals",
            sa.Integer(),
            nullable=False,
            server_default="1",
        ),
        sa.Column(
            "high_value_required_approvals",
            sa.Integer(),
            nullable=False,
            server_default="2",
        ),
        sa.Column(
            "required_confirmations",
            sa.Integer(),
            nullable=False,
            server_default="1",
        ),
        sa.Column(
            "simulation_required",
            sa.Boolean(),
            nullable=False,
            server_default=sa.true(),
        ),
        sa.Column("status", treasury_status, nullable=False),
        sa.Column("provider_config", sa.JSON(), nullable=False),
        sa.Column("paused_reason", sa.Text(), nullable=True),
        sa.Column("last_balance_checked_at", sa.DateTime(), nullable=True),
        sa.Column("created_by_user_id", sa.Integer(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.ForeignKeyConstraint(
            ["organization_id"], ["organizations.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["created_by_user_id"], ["users.id"], ondelete="RESTRICT"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "organization_id",
            "provider_key",
            "environment",
            "chain",
            "currency",
            "treasury_address",
            name="uq_treasury_accounts_scope",
        ),
    )
    _indexes(
        "treasury_accounts",
        "id",
        "organization_id",
        "provider_key",
        "environment",
        "chain",
        "currency",
        "status",
    )

    op.add_column(
        "payouts", sa.Column("treasury_account_id", sa.Integer(), nullable=True)
    )
    op.add_column(
        "payouts", sa.Column("provider_key", sa.String(64), nullable=True)
    )
    op.add_column(
        "payouts", sa.Column("provider_reference", sa.String(255), nullable=True)
    )
    op.add_column(
        "payouts", sa.Column("explorer_url", sa.String(2048), nullable=True)
    )
    op.add_column(
        "payouts",
        sa.Column(
            "required_confirmations",
            sa.Integer(),
            nullable=False,
            server_default="1",
        ),
    )
    op.add_column(
        "payouts",
        sa.Column(
            "observed_confirmations",
            sa.Integer(),
            nullable=False,
            server_default="0",
        ),
    )
    op.add_column(
        "payouts", sa.Column("last_status_checked_at", sa.DateTime(), nullable=True)
    )
    op.add_column(
        "payouts", sa.Column("next_reconciliation_at", sa.DateTime(), nullable=True)
    )
    op.create_foreign_key(
        "fk_payouts_treasury_account_id",
        "payouts",
        "treasury_accounts",
        ["treasury_account_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    _indexes(
        "payouts",
        "treasury_account_id",
        "provider_key",
        "provider_reference",
        "next_reconciliation_at",
    )

    op.add_column(
        "payout_attempts",
        sa.Column("provider_reference", sa.String(255), nullable=True),
    )
    op.add_column(
        "payout_attempts",
        sa.Column("explorer_url", sa.String(2048), nullable=True),
    )
    op.add_column(
        "payout_attempts",
        sa.Column(
            "simulation_result",
            sa.JSON(),
            nullable=False,
            server_default=sa.text("'{}'::json"),
        ),
    )
    op.add_column(
        "payout_attempts",
        sa.Column(
            "provider_response",
            sa.JSON(),
            nullable=False,
            server_default=sa.text("'{}'::json"),
        ),
    )
    op.add_column(
        "payout_attempts",
        sa.Column("last_checked_at", sa.DateTime(), nullable=True),
    )
    op.create_index(
        "ix_payout_attempts_provider_reference",
        "payout_attempts",
        ["provider_reference"],
    )

    op.create_table(
        "treasury_approvals",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("payout_id", sa.Integer(), nullable=False),
        sa.Column("treasury_account_id", sa.Integer(), nullable=False),
        sa.Column("approver_user_id", sa.Integer(), nullable=False),
        sa.Column("decision", treasury_approval_decision, nullable=False),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column("amount", sa.Numeric(24, 6), nullable=False),
        sa.Column("currency", sa.String(16), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.ForeignKeyConstraint(
            ["payout_id"], ["payouts.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["treasury_account_id"], ["treasury_accounts.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["approver_user_id"], ["users.id"], ondelete="RESTRICT"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "payout_id",
            "approver_user_id",
            name="uq_treasury_approvals_payout_approver",
        ),
    )
    _indexes(
        "treasury_approvals",
        "id",
        "payout_id",
        "treasury_account_id",
        "approver_user_id",
        "decision",
    )

    op.create_table(
        "payout_ledger_entries",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("treasury_account_id", sa.Integer(), nullable=False),
        sa.Column("payout_id", sa.Integer(), nullable=True),
        sa.Column("entry_type", ledger_entry_type, nullable=False),
        sa.Column("currency", sa.String(16), nullable=False),
        sa.Column(
            "available_delta",
            sa.Numeric(24, 6),
            nullable=False,
            server_default="0",
        ),
        sa.Column(
            "reserved_delta",
            sa.Numeric(24, 6),
            nullable=False,
            server_default="0",
        ),
        sa.Column(
            "settled_delta",
            sa.Numeric(24, 6),
            nullable=False,
            server_default="0",
        ),
        sa.Column("idempotency_key", sa.String(128), nullable=False),
        sa.Column("entry_metadata", sa.JSON(), nullable=False),
        sa.Column("created_by_user_id", sa.Integer(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.ForeignKeyConstraint(
            ["treasury_account_id"], ["treasury_accounts.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["payout_id"], ["payouts.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["created_by_user_id"], ["users.id"], ondelete="SET NULL"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "idempotency_key",
            name="uq_payout_ledger_entries_idempotency_key",
        ),
    )
    _indexes(
        "payout_ledger_entries",
        "id",
        "treasury_account_id",
        "payout_id",
        "entry_type",
    )
    op.create_index(
        "ix_payout_ledger_entries_treasury_created",
        "payout_ledger_entries",
        ["treasury_account_id", "created_at"],
    )

    op.create_table(
        "payout_reconciliations",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("payout_id", sa.Integer(), nullable=False),
        sa.Column("payout_attempt_id", sa.Integer(), nullable=True),
        sa.Column("provider_key", sa.String(64), nullable=False),
        sa.Column("provider_reference", sa.String(255), nullable=False),
        sa.Column("outcome", reconciliation_outcome, nullable=False),
        sa.Column("confirmations", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("transaction_hash", sa.String(255), nullable=True),
        sa.Column("provider_status_hash", sa.String(64), nullable=False),
        sa.Column("provider_response", sa.JSON(), nullable=False),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column(
            "checked_at",
            sa.DateTime(),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.ForeignKeyConstraint(
            ["payout_id"], ["payouts.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["payout_attempt_id"], ["payout_attempts.id"], ondelete="SET NULL"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "payout_id",
            "provider_status_hash",
            name="uq_payout_reconciliations_status_hash",
        ),
    )
    _indexes(
        "payout_reconciliations",
        "id",
        "payout_id",
        "payout_attempt_id",
        "outcome",
    )

    op.create_table(
        "treasury_balance_snapshots",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("treasury_account_id", sa.Integer(), nullable=False),
        sa.Column("provider_key", sa.String(64), nullable=False),
        sa.Column("currency", sa.String(16), nullable=False),
        sa.Column("observed_balance", sa.Numeric(24, 6), nullable=False),
        sa.Column("balance_hash", sa.String(64), nullable=False),
        sa.Column("provider_response", sa.JSON(), nullable=False),
        sa.Column(
            "observed_at",
            sa.DateTime(),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.ForeignKeyConstraint(
            ["treasury_account_id"], ["treasury_accounts.id"], ondelete="RESTRICT"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "treasury_account_id",
            "balance_hash",
            name="uq_treasury_balance_snapshots_hash",
        ),
    )
    _indexes("treasury_balance_snapshots", "id", "treasury_account_id")

    op.execute(
        """
        CREATE FUNCTION prevent_payout_integration_audit_mutation()
        RETURNS trigger AS $$
        BEGIN
            RAISE EXCEPTION 'payout integration audit records are immutable';
        END;
        $$ LANGUAGE plpgsql
        """
    )
    for table in (
        "treasury_approvals",
        "payout_ledger_entries",
        "payout_reconciliations",
        "treasury_balance_snapshots",
    ):
        op.execute(
            f"""
            CREATE TRIGGER trg_{table}_immutable
            BEFORE UPDATE OR DELETE ON {table}
            FOR EACH ROW EXECUTE FUNCTION prevent_payout_integration_audit_mutation()
            """
        )
    _install_payout_snapshot_trigger()


def downgrade() -> None:
    _restore_payout_snapshot_trigger()
    for table in (
        "treasury_balance_snapshots",
        "payout_reconciliations",
        "payout_ledger_entries",
        "treasury_approvals",
    ):
        op.execute(f"DROP TRIGGER IF EXISTS trg_{table}_immutable ON {table}")
    op.execute(
        "DROP FUNCTION IF EXISTS prevent_payout_integration_audit_mutation()"
    )
    op.drop_table("treasury_balance_snapshots")
    op.drop_table("payout_reconciliations")
    op.drop_table("payout_ledger_entries")
    op.drop_table("treasury_approvals")

    op.drop_index(
        "ix_payout_attempts_provider_reference", table_name="payout_attempts"
    )
    for column in (
        "last_checked_at",
        "provider_response",
        "simulation_result",
        "explorer_url",
        "provider_reference",
    ):
        op.drop_column("payout_attempts", column)

    op.drop_constraint(
        "fk_payouts_treasury_account_id", "payouts", type_="foreignkey"
    )
    for index in (
        "ix_payouts_next_reconciliation_at",
        "ix_payouts_provider_reference",
        "ix_payouts_provider_key",
        "ix_payouts_treasury_account_id",
    ):
        op.drop_index(index, table_name="payouts")
    for column in (
        "next_reconciliation_at",
        "last_status_checked_at",
        "observed_confirmations",
        "required_confirmations",
        "explorer_url",
        "provider_reference",
        "provider_key",
        "treasury_account_id",
    ):
        op.drop_column("payouts", column)

    op.drop_table("treasury_accounts")
    for enum_type in (
        reconciliation_outcome,
        ledger_entry_type,
        treasury_approval_decision,
        treasury_status,
        treasury_environment,
    ):
        enum_type.drop(op.get_bind(), checkfirst=True)
