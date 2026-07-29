"""Persist early webhook tenant attribution.

Revision ID: 20260725_0016
Revises: 20260725_0015
Create Date: 2026-07-25
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "20260725_0016"
down_revision: Union[str, None] = "20260725_0015"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "webhook_deliveries",
        sa.Column("repository_full_name", sa.String(length=512), nullable=True),
    )
    op.add_column(
        "webhook_deliveries",
        sa.Column(
            "repository_owner_login", sa.String(length=255), nullable=True
        ),
    )
    op.create_index(
        "ix_webhook_deliveries_repository_full_name",
        "webhook_deliveries",
        ["repository_full_name"],
    )
    op.create_index(
        "ix_webhook_deliveries_repository_owner_login",
        "webhook_deliveries",
        ["repository_owner_login"],
    )
    if op.get_bind().dialect.name == "postgresql":
        op.execute(
            """
            UPDATE webhook_deliveries
            SET repository_full_name =
                    payload -> 'repository' ->> 'full_name',
                repository_owner_login =
                    payload -> 'repository' -> 'owner' ->> 'login'
            WHERE repository_full_name IS NULL
            """
        )


def downgrade() -> None:
    op.drop_index(
        "ix_webhook_deliveries_repository_owner_login",
        table_name="webhook_deliveries",
    )
    op.drop_index(
        "ix_webhook_deliveries_repository_full_name",
        table_name="webhook_deliveries",
    )
    op.drop_column("webhook_deliveries", "repository_owner_login")
    op.drop_column("webhook_deliveries", "repository_full_name")
