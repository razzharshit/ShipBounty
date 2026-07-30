"""Add organizations, installations, repository authorization, and audit logs.

Revision ID: 20260725_0007
Revises: 20260725_0006
Create Date: 2026-07-25
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "20260725_0007"
down_revision: Union[str, None] = "20260725_0006"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


authorization_role = postgresql.ENUM(
    "owner",
    "admin",
    "maintainer",
    "reviewer",
    "contributor",
    "viewer",
    name="authorizationrole",
    create_type=False,
)


def upgrade() -> None:
    bind = op.get_bind()
    authorization_role.create(bind, checkfirst=True)

    op.create_table(
        "organizations",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("github_org_id", sa.BigInteger(), nullable=True),
        sa.Column("login", sa.String(length=255), nullable=False),
        sa.Column("display_name", sa.String(length=255), nullable=True),
        sa.Column("avatar_url", sa.String(length=1024), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("github_org_id"),
        sa.UniqueConstraint("login"),
    )
    op.create_index("ix_organizations_id", "organizations", ["id"])
    op.create_index("ix_organizations_github_org_id", "organizations", ["github_org_id"])
    op.create_index("ix_organizations_login", "organizations", ["login"])

    op.add_column("users", sa.Column("email", sa.String(length=320), nullable=True))
    op.add_column("users", sa.Column("display_name", sa.String(length=255), nullable=True))
    op.add_column(
        "users",
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
    )
    op.add_column(
        "users",
        sa.Column("session_version", sa.Integer(), nullable=False, server_default="0"),
    )
    op.add_column("users", sa.Column("last_login_at", sa.DateTime(), nullable=True))
    op.add_column(
        "users",
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
    )

    # Existing repository owners become tenant records before organization_id is
    # made non-null. GitHub synchronization replaces missing account IDs later.
    op.execute(
        """
        INSERT INTO organizations (login, display_name, created_at, updated_at)
        SELECT lower(owner), min(owner), now(), now()
        FROM repositories
        GROUP BY lower(owner)
        ON CONFLICT (login) DO NOTHING
        """
    )
    op.add_column("repositories", sa.Column("organization_id", sa.Integer(), nullable=True))
    op.add_column(
        "repositories", sa.Column("github_installation_id", sa.Integer(), nullable=True)
    )
    op.add_column("repositories", sa.Column("full_name", sa.String(length=512), nullable=True))
    op.add_column(
        "repositories",
        sa.Column("is_private", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.add_column(
        "repositories",
        sa.Column("is_archived", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.add_column(
        "repositories",
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
    )
    op.execute(
        """
        UPDATE repositories AS r
        SET organization_id = o.id,
            full_name = r.owner || '/' || r.name
        FROM organizations AS o
        WHERE o.login = lower(r.owner)
        """
    )
    op.alter_column("repositories", "organization_id", nullable=False)
    op.alter_column("repositories", "full_name", nullable=False)
    op.create_foreign_key(
        "fk_repositories_organization_id",
        "repositories",
        "organizations",
        ["organization_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.create_index(
        "ix_repositories_organization_id", "repositories", ["organization_id"]
    )

    op.create_table(
        "organization_memberships",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("organization_id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("role", authorization_role, nullable=False),
        sa.Column("github_role", sa.String(length=32), nullable=True),
        sa.Column(
            "is_active", sa.Boolean(), nullable=False, server_default=sa.true()
        ),
        sa.Column(
            "github_verified", sa.Boolean(), nullable=False, server_default=sa.false()
        ),
        sa.Column("github_verified_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(
            ["organization_id"], ["organizations.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "organization_id", "user_id", name="uq_org_membership_org_user"
        ),
    )
    op.create_index("ix_organization_memberships_id", "organization_memberships", ["id"])
    op.create_index(
        "ix_organization_memberships_organization_id",
        "organization_memberships",
        ["organization_id"],
    )
    op.create_index(
        "ix_organization_memberships_user_id",
        "organization_memberships",
        ["user_id"],
    )

    op.create_table(
        "github_installations",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("installation_id", sa.BigInteger(), nullable=False),
        sa.Column("organization_id", sa.Integer(), nullable=False),
        sa.Column("account_id", sa.BigInteger(), nullable=False),
        sa.Column("account_login", sa.String(length=255), nullable=False),
        sa.Column("target_type", sa.String(length=32), nullable=False),
        sa.Column("repository_selection", sa.String(length=32), nullable=True),
        sa.Column(
            "permissions",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column(
            "events",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
        sa.Column("suspended_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(
            ["organization_id"], ["organizations.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("installation_id"),
    )
    op.create_index("ix_github_installations_id", "github_installations", ["id"])
    op.create_index(
        "ix_github_installations_installation_id",
        "github_installations",
        ["installation_id"],
    )
    op.create_index(
        "ix_github_installations_organization_id",
        "github_installations",
        ["organization_id"],
    )
    op.create_index(
        "ix_github_installations_account_id",
        "github_installations",
        ["account_id"],
    )

    op.create_foreign_key(
        "fk_repositories_github_installation_id",
        "repositories",
        "github_installations",
        ["github_installation_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index(
        "ix_repositories_github_installation_id",
        "repositories",
        ["github_installation_id"],
    )

    op.create_table(
        "repository_permissions",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("repository_id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("role", authorization_role, nullable=False),
        sa.Column(
            "source", sa.String(length=32), nullable=False, server_default="github"
        ),
        sa.Column("github_permission", sa.String(length=32), nullable=True),
        sa.Column("github_verified_at", sa.DateTime(), nullable=True),
        sa.Column("granted_by_user_id", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(
            ["repository_id"], ["repositories.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["granted_by_user_id"], ["users.id"], ondelete="SET NULL"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "repository_id", "user_id", name="uq_repo_permission_repo_user"
        ),
    )
    op.create_index("ix_repository_permissions_id", "repository_permissions", ["id"])
    op.create_index(
        "ix_repository_permissions_repository_id",
        "repository_permissions",
        ["repository_id"],
    )
    op.create_index(
        "ix_repository_permissions_user_id",
        "repository_permissions",
        ["user_id"],
    )

    op.create_table(
        "oauth_credentials",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column(
            "provider", sa.String(length=32), nullable=False, server_default="github"
        ),
        sa.Column("access_token_ciphertext", sa.Text(), nullable=False),
        sa.Column("refresh_token_ciphertext", sa.Text(), nullable=True),
        sa.Column("encryption_key_id", sa.String(length=64), nullable=False),
        sa.Column(
            "scopes",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("refresh_token_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "user_id", "provider", name="uq_oauth_credential_user_provider"
        ),
    )
    op.create_index("ix_oauth_credentials_id", "oauth_credentials", ["id"])
    op.create_index("ix_oauth_credentials_user_id", "oauth_credentials", ["user_id"])

    op.create_table(
        "audit_logs",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("organization_id", sa.Integer(), nullable=True),
        sa.Column("actor_user_id", sa.Integer(), nullable=True),
        sa.Column("repository_id", sa.Integer(), nullable=True),
        sa.Column("action", sa.String(length=128), nullable=False),
        sa.Column("resource_type", sa.String(length=64), nullable=False),
        sa.Column("resource_id", sa.String(length=255), nullable=True),
        sa.Column(
            "event_metadata",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column("request_id", sa.String(length=64), nullable=True),
        sa.Column("ip_address", sa.String(length=64), nullable=True),
        sa.Column("user_agent", sa.String(length=512), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(
            ["organization_id"], ["organizations.id"], ondelete="SET NULL"
        ),
        sa.ForeignKeyConstraint(["actor_user_id"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(
            ["repository_id"], ["repositories.id"], ondelete="SET NULL"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_audit_logs_id", "audit_logs", ["id"])
    op.create_index("ix_audit_logs_organization_id", "audit_logs", ["organization_id"])
    op.create_index("ix_audit_logs_actor_user_id", "audit_logs", ["actor_user_id"])
    op.create_index("ix_audit_logs_repository_id", "audit_logs", ["repository_id"])
    op.create_index("ix_audit_logs_action", "audit_logs", ["action"])
    op.create_index("ix_audit_logs_created_at", "audit_logs", ["created_at"])

    op.add_column(
        "webhook_deliveries", sa.Column("organization_id", sa.Integer(), nullable=True)
    )
    op.add_column(
        "webhook_deliveries", sa.Column("repository_pk", sa.Integer(), nullable=True)
    )
    op.create_foreign_key(
        "fk_webhook_deliveries_organization_id",
        "webhook_deliveries",
        "organizations",
        ["organization_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_foreign_key(
        "fk_webhook_deliveries_repository_pk",
        "webhook_deliveries",
        "repositories",
        ["repository_pk"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index(
        "ix_webhook_deliveries_organization_id",
        "webhook_deliveries",
        ["organization_id"],
    )
    op.create_index(
        "ix_webhook_deliveries_repository_pk",
        "webhook_deliveries",
        ["repository_pk"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_webhook_deliveries_repository_pk", table_name="webhook_deliveries"
    )
    op.drop_index(
        "ix_webhook_deliveries_organization_id", table_name="webhook_deliveries"
    )
    op.drop_constraint(
        "fk_webhook_deliveries_repository_pk",
        "webhook_deliveries",
        type_="foreignkey",
    )
    op.drop_constraint(
        "fk_webhook_deliveries_organization_id",
        "webhook_deliveries",
        type_="foreignkey",
    )
    op.drop_column("webhook_deliveries", "repository_pk")
    op.drop_column("webhook_deliveries", "organization_id")

    op.drop_table("audit_logs")
    op.drop_table("oauth_credentials")
    op.drop_table("repository_permissions")
    op.drop_index(
        "ix_repositories_github_installation_id", table_name="repositories"
    )
    op.drop_constraint(
        "fk_repositories_github_installation_id",
        "repositories",
        type_="foreignkey",
    )
    op.drop_table("github_installations")
    op.drop_table("organization_memberships")

    op.drop_index("ix_repositories_organization_id", table_name="repositories")
    op.drop_constraint(
        "fk_repositories_organization_id", "repositories", type_="foreignkey"
    )
    op.drop_column("repositories", "updated_at")
    op.drop_column("repositories", "is_archived")
    op.drop_column("repositories", "is_private")
    op.drop_column("repositories", "full_name")
    op.drop_column("repositories", "github_installation_id")
    op.drop_column("repositories", "organization_id")

    op.drop_column("users", "updated_at")
    op.drop_column("users", "last_login_at")
    op.drop_column("users", "is_active")
    op.drop_column("users", "display_name")
    op.drop_column("users", "email")
    op.drop_column("users", "session_version")

    op.drop_table("organizations")
    authorization_role.drop(op.get_bind(), checkfirst=True)
