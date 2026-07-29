"""Add ambiguous payout recovery and provider-confirmation guards.

Revision ID: 20260725_0015
Revises: 20260725_0014
Create Date: 2026-07-25
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "20260725_0015"
down_revision: Union[str, None] = "20260725_0014"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        # PostgreSQL enum additions are intentionally retained on downgrade.
        op.execute(
            "ALTER TYPE payoutstate ADD VALUE IF NOT EXISTS "
            "'submission_unknown' AFTER 'submitting'"
        )
        op.execute(
            "ALTER TYPE payoutattemptstate ADD VALUE IF NOT EXISTS "
            "'submission_unknown' AFTER 'submitting'"
        )
    op.add_column(
        "payout_attempts",
        sa.Column(
            "recovery_attempt_count",
            sa.Integer(),
            nullable=False,
            server_default="0",
        ),
    )
    if bind.dialect.name == "postgresql":
        op.execute(
            """
            CREATE OR REPLACE FUNCTION enforce_provider_confirmed_payout()
            RETURNS trigger AS $$
            BEGIN
                IF NEW.state = 'confirmed' THEN
                    IF NEW.provider_reference IS NULL
                       OR NEW.transaction_hash IS NULL
                       OR NOT EXISTS (
                           SELECT 1
                           FROM payout_reconciliations reconciliation
                           WHERE reconciliation.payout_id = NEW.id
                             AND reconciliation.outcome = 'confirmed'
                             AND reconciliation.provider_reference =
                                 NEW.provider_reference
                             AND reconciliation.transaction_hash =
                                 NEW.transaction_hash
                       )
                    THEN
                        RAISE EXCEPTION
                            'confirmed payout requires matching provider reconciliation';
                    END IF;
                END IF;
                RETURN NEW;
            END;
            $$ LANGUAGE plpgsql
            """
        )
        op.execute(
            """
            CREATE CONSTRAINT TRIGGER trg_provider_confirmed_payout
            AFTER INSERT OR UPDATE OF state ON payouts
            DEFERRABLE INITIALLY DEFERRED
            FOR EACH ROW EXECUTE FUNCTION enforce_provider_confirmed_payout()
            """
        )


def downgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        op.execute(
            "DROP TRIGGER IF EXISTS trg_provider_confirmed_payout ON payouts"
        )
        op.execute(
            "DROP FUNCTION IF EXISTS enforce_provider_confirmed_payout()"
        )
    op.drop_column("payout_attempts", "recovery_attempt_count")
