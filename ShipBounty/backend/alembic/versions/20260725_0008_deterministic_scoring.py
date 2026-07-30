"""Add immutable deterministic scoring runs, analyzer results, and evidence.

Revision ID: 20260725_0008
Revises: 20260725_0007
Create Date: 2026-07-25
"""

from typing import Sequence, Union
import hashlib
import json

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "20260725_0008"
down_revision: Union[str, None] = "20260725_0007"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


DEFAULT_WEIGHTS = {
    "correctness": 0.30,
    "tests": 0.20,
    "maintainability": 0.15,
    "security": 0.15,
    "documentation": 0.05,
    "architecture": 0.10,
    "change_risk": 0.05,
}
DEFAULT_REQUIRED_ANALYZERS = [
    "diff_size_concentration",
    "documentation_changes",
    "dependency_changes",
]


def _policy_hash(weights: dict, required_analyzers: list[str], settings: dict) -> str:
    encoded = json.dumps(
        {
            "weights": weights,
            "analyzer_weights": {},
            "required_analyzers": required_analyzers,
            "settings": settings,
        },
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(encoded.encode()).hexdigest()


analyzer_result_status = postgresql.ENUM(
    "available",
    "unavailable",
    "inconclusive",
    "error",
    name="analyzerresultstatus",
    create_type=False,
)


def upgrade() -> None:
    bind = op.get_bind()
    analyzer_result_status.create(bind, checkfirst=True)
    op.execute("ALTER TYPE analysisrunstatus ADD VALUE IF NOT EXISTS 'pending'")
    op.execute("ALTER TYPE analysisrunstatus ADD VALUE IF NOT EXISTS 'running'")
    op.execute("ALTER TYPE analysisrunstatus ADD VALUE IF NOT EXISTS 'failed'")
    op.drop_constraint(
        "uq_analysis_runs_delivery_version",
        "analysis_runs",
        type_="unique",
    )

    op.create_table(
        "score_versions",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("version", sa.String(length=128), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("weights", sa.JSON(), nullable=False),
        sa.Column("analyzer_weights", sa.JSON(), nullable=False),
        sa.Column("required_analyzers", sa.JSON(), nullable=False),
        sa.Column("settings", sa.JSON(), nullable=False),
        sa.Column("policy_hash", sa.String(length=64), nullable=False),
        sa.Column("created_by_user_id", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(
            ["created_by_user_id"], ["users.id"], ondelete="SET NULL"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("policy_hash"),
    )
    op.create_index("ix_score_versions_id", "score_versions", ["id"])
    op.create_index(
        "ix_score_versions_version",
        "score_versions",
        ["version"],
        unique=True,
    )

    # Literal JSON makes `alembic upgrade --sql` deterministic; SQLAlchemy's
    # generic JSON bulk renderer cannot emit offline literals.
    def json_literal(value: object) -> str:
        return json.dumps(
            value, sort_keys=True, separators=(",", ":")
        ).replace("'", "''").replace(":", r"\:")

    default_hash = _policy_hash(
        DEFAULT_WEIGHTS,
        DEFAULT_REQUIRED_ANALYZERS,
        {"minimum_confidence": 0.30},
    )
    legacy_hash = _policy_hash(DEFAULT_WEIGHTS, [], {"legacy": True})
    op.execute(
        f"""
        INSERT INTO score_versions (
            version, name, description, weights, analyzer_weights,
            required_analyzers, settings, policy_hash
        ) VALUES
        (
            'default-v1',
            'Default balanced policy',
            'Balanced deterministic policy for general repositories.',
            '{json_literal(DEFAULT_WEIGHTS)}'::json,
            '{{}}'::json,
            '{json_literal(DEFAULT_REQUIRED_ANALYZERS)}'::json,
            '{json_literal({"minimum_confidence": 0.30})}'::json,
            '{default_hash}'
        ),
        (
            'legacy-v1',
            'Legacy mutable score',
            'Preserved pre-Phase-3 score; never authoritative.',
            '{json_literal(DEFAULT_WEIGHTS)}'::json,
            '{{}}'::json,
            '[]'::json,
            '{json_literal({"legacy": True})}'::json,
            '{legacy_hash}'
        )
        """
    )

    op.add_column(
        "repositories", sa.Column("scoring_policy_id", sa.Integer(), nullable=True)
    )
    op.execute(
        "UPDATE repositories SET scoring_policy_id = "
        "(SELECT id FROM score_versions WHERE version = 'default-v1')"
    )
    op.create_foreign_key(
        "fk_repositories_scoring_policy_id",
        "repositories",
        "score_versions",
        ["scoring_policy_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.create_index(
        "ix_repositories_scoring_policy_id",
        "repositories",
        ["scoring_policy_id"],
    )

    op.add_column(
        "analysis_runs", sa.Column("analyzer_version", sa.String(length=128), nullable=True)
    )
    op.add_column(
        "analysis_runs",
        sa.Column("scoring_policy_version", sa.String(length=128), nullable=True),
    )
    op.add_column(
        "analysis_runs", sa.Column("run_key", sa.String(length=64), nullable=True)
    )
    op.add_column(
        "analysis_runs", sa.Column("input_hash", sa.String(length=64), nullable=True)
    )
    op.add_column(
        "analysis_runs",
        sa.Column(
            "analyzer_manifest",
            sa.JSON(),
            nullable=True,
        ),
    )
    op.add_column(
        "analysis_runs",
        sa.Column(
            "input_complete",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
    )
    op.add_column(
        "analysis_runs", sa.Column("started_at", sa.DateTime(), nullable=True)
    )
    op.alter_column("analysis_runs", "completed_at", nullable=True)
    op.execute(
        """
        UPDATE analysis_runs
        SET analyzer_version = analysis_version,
            scoring_policy_version = 'legacy-v1',
            run_key = md5('legacy-run-' || id::text) || md5(id::text || '-run'),
            input_hash = md5('legacy-input-' || id::text) || md5(id::text || '-input'),
            analyzer_manifest = '[]'::json,
            input_complete = (status::text = 'complete'),
            started_at = created_at
        """
    )
    op.alter_column("analysis_runs", "analyzer_version", nullable=False)
    op.alter_column("analysis_runs", "scoring_policy_version", nullable=False)
    op.alter_column("analysis_runs", "run_key", nullable=False)
    op.alter_column("analysis_runs", "input_hash", nullable=False)
    op.alter_column("analysis_runs", "analyzer_manifest", nullable=False)
    op.alter_column("analysis_runs", "started_at", nullable=False)
    op.create_unique_constraint(
        "uq_analysis_runs_run_key", "analysis_runs", ["run_key"]
    )
    op.create_index("ix_analysis_runs_run_key", "analysis_runs", ["run_key"])

    op.create_table(
        "analyzer_results",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("analysis_run_id", sa.Integer(), nullable=False),
        sa.Column("analyzer_name", sa.String(length=128), nullable=False),
        sa.Column("analyzer_version", sa.String(length=64), nullable=False),
        sa.Column("category", sa.String(length=64), nullable=False),
        sa.Column("status", analyzer_result_status, nullable=False),
        sa.Column("score", sa.Numeric(precision=5, scale=2), nullable=True),
        sa.Column(
            "confidence",
            sa.Numeric(precision=5, scale=4),
            nullable=False,
            server_default="0",
        ),
        sa.Column("findings", sa.JSON(), nullable=False),
        sa.Column("evidence", sa.JSON(), nullable=False),
        sa.Column("errors", sa.JSON(), nullable=False),
        sa.Column("duration_ms", sa.Integer(), nullable=False),
        sa.Column("result_hash", sa.String(length=64), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(
            ["analysis_run_id"], ["analysis_runs.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "analysis_run_id",
            "analyzer_name",
            "analyzer_version",
            name="uq_analyzer_results_run_analyzer",
        ),
    )
    op.create_index("ix_analyzer_results_id", "analyzer_results", ["id"])
    op.create_index(
        "ix_analyzer_results_analysis_run_id",
        "analyzer_results",
        ["analysis_run_id"],
    )

    op.drop_constraint("scores_pr_id_key", "scores", type_="unique")
    op.add_column(
        "scores", sa.Column("analysis_run_id", sa.Integer(), nullable=True)
    )
    op.add_column(
        "scores", sa.Column("score_version_id", sa.Integer(), nullable=True)
    )
    op.add_column("scores", sa.Column("head_sha", sa.String(length=64), nullable=True))
    op.add_column(
        "scores",
        sa.Column("analyzer_suite_version", sa.String(length=128), nullable=True),
    )
    op.add_column(
        "scores",
        sa.Column("scoring_policy_version", sa.String(length=128), nullable=True),
    )
    op.add_column("scores", sa.Column("category_scores", sa.JSON(), nullable=True))
    op.add_column(
        "scores", sa.Column("category_confidence", sa.JSON(), nullable=True)
    )
    op.add_column(
        "scores", sa.Column("unavailable_categories", sa.JSON(), nullable=True)
    )
    op.add_column(
        "scores",
        sa.Column(
            "confidence",
            sa.Numeric(precision=5, scale=4),
            nullable=True,
        ),
    )
    op.add_column(
        "scores",
        sa.Column(
            "input_complete", sa.Boolean(), nullable=True
        ),
    )
    op.add_column(
        "scores", sa.Column("is_authoritative", sa.Boolean(), nullable=True)
    )
    op.add_column("scores", sa.Column("explanation", sa.JSON(), nullable=True))
    op.add_column(
        "scores", sa.Column("deterministic_hash", sa.String(length=64), nullable=True)
    )
    op.execute(
        """
        UPDATE scores AS s
        SET score_version_id = (
                SELECT id FROM score_versions WHERE version = 'legacy-v1'
            ),
            head_sha = pr.head_sha,
            analyzer_suite_version = 'legacy-v1',
            scoring_policy_version = 'legacy-v1',
            category_scores = json_build_object(
                'maintainability', s.quality_score,
                'change_risk', s.activity_score,
                'tests', s.test_score
            ),
            category_confidence = '{}'::json,
            unavailable_categories = '[
                "correctness", "security", "documentation", "architecture"
            ]'::json,
            confidence = 0,
            input_complete = false,
            is_authoritative = false,
            explanation = json_build_object(
                'legacy', true,
                'message', 'Preserved pre-Phase-3 mutable score'
            ),
            deterministic_hash = md5('legacy-score-' || s.id::text)
                || md5(s.id::text || '-score')
        FROM pull_requests AS pr
        WHERE pr.id = s.pr_id
        """
    )
    op.drop_column("scores", "test_score")
    op.drop_column("scores", "activity_score")
    op.drop_column("scores", "quality_score")
    op.alter_column("scores", "score_version_id", nullable=False)
    op.alter_column("scores", "analyzer_suite_version", nullable=False)
    op.alter_column("scores", "scoring_policy_version", nullable=False)
    op.alter_column("scores", "category_scores", nullable=False)
    op.alter_column("scores", "category_confidence", nullable=False)
    op.alter_column("scores", "unavailable_categories", nullable=False)
    op.alter_column("scores", "final_score", type_=sa.Numeric(5, 2))
    op.alter_column("scores", "confidence", nullable=False)
    op.alter_column("scores", "input_complete", nullable=False)
    op.alter_column("scores", "is_authoritative", nullable=False)
    op.alter_column("scores", "explanation", nullable=False)
    op.alter_column("scores", "deterministic_hash", nullable=False)
    op.create_foreign_key(
        "fk_scores_analysis_run_id",
        "scores",
        "analysis_runs",
        ["analysis_run_id"],
        ["id"],
        ondelete="CASCADE",
    )
    op.create_foreign_key(
        "fk_scores_score_version_id",
        "scores",
        "score_versions",
        ["score_version_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.create_unique_constraint(
        "uq_scores_analysis_run_id", "scores", ["analysis_run_id"]
    )
    op.create_unique_constraint(
        "uq_scores_deterministic_hash", "scores", ["deterministic_hash"]
    )
    op.create_index("ix_scores_analysis_run_id", "scores", ["analysis_run_id"])
    op.create_index("ix_scores_score_version_id", "scores", ["score_version_id"])

    op.create_table(
        "score_evidence",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("score_id", sa.Integer(), nullable=False),
        sa.Column("analyzer_result_id", sa.Integer(), nullable=False),
        sa.Column("category", sa.String(length=64), nullable=False),
        sa.Column("evidence_type", sa.String(length=64), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("location", sa.String(length=2048), nullable=True),
        sa.Column("evidence_data", sa.JSON(), nullable=False),
        sa.Column("evidence_hash", sa.String(length=64), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(
            ["score_id"], ["scores.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["analyzer_result_id"], ["analyzer_results.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_score_evidence_id", "score_evidence", ["id"])
    op.create_index("ix_score_evidence_score_id", "score_evidence", ["score_id"])
    op.create_index(
        "ix_score_evidence_analyzer_result_id",
        "score_evidence",
        ["analyzer_result_id"],
    )
    op.create_index("ix_score_evidence_category", "score_evidence", ["category"])
    op.create_index(
        "ix_score_evidence_evidence_hash", "score_evidence", ["evidence_hash"]
    )

    op.add_column(
        "pull_requests", sa.Column("latest_score_id", sa.Integer(), nullable=True)
    )
    op.create_foreign_key(
        "fk_pull_requests_latest_score_id",
        "pull_requests",
        "scores",
        ["latest_score_id"],
        ["id"],
        ondelete="SET NULL",
        use_alter=True,
    )
    op.create_index(
        "ix_pull_requests_latest_score_id",
        "pull_requests",
        ["latest_score_id"],
    )

    op.execute(
        """
        CREATE FUNCTION prevent_immutable_scoring_change()
        RETURNS trigger AS $$
        BEGIN
            RAISE EXCEPTION '% records are immutable', TG_TABLE_NAME;
        END;
        $$ LANGUAGE plpgsql
        """
    )
    for table_name in ("scores", "analyzer_results", "score_evidence"):
        op.execute(
            f"""
            CREATE TRIGGER trg_{table_name}_immutable
            BEFORE UPDATE OR DELETE ON {table_name}
            FOR EACH ROW EXECUTE FUNCTION prevent_immutable_scoring_change()
            """
        )
    op.execute(
        """
        CREATE FUNCTION prevent_terminal_analysis_run_change()
        RETURNS trigger AS $$
        BEGIN
            IF OLD.status::text IN ('complete', 'incomplete', 'failed') THEN
                RAISE EXCEPTION 'terminal analysis_runs records are immutable';
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
        CREATE TRIGGER trg_analysis_runs_terminal_immutable
        BEFORE UPDATE OR DELETE ON analysis_runs
        FOR EACH ROW EXECUTE FUNCTION prevent_terminal_analysis_run_change()
        """
    )


def downgrade() -> None:
    op.execute(
        "DROP TRIGGER IF EXISTS trg_analysis_runs_terminal_immutable ON analysis_runs"
    )
    op.execute("DROP FUNCTION IF EXISTS prevent_terminal_analysis_run_change()")
    for table_name in ("scores", "analyzer_results", "score_evidence"):
        op.execute(f"DROP TRIGGER IF EXISTS trg_{table_name}_immutable ON {table_name}")
    op.execute("DROP FUNCTION IF EXISTS prevent_immutable_scoring_change()")

    op.drop_index("ix_pull_requests_latest_score_id", table_name="pull_requests")
    op.drop_constraint(
        "fk_pull_requests_latest_score_id", "pull_requests", type_="foreignkey"
    )
    op.drop_column("pull_requests", "latest_score_id")

    op.drop_table("score_evidence")

    op.add_column(
        "scores",
        sa.Column("quality_score", sa.Float(), nullable=True),
    )
    op.add_column(
        "scores",
        sa.Column("activity_score", sa.Float(), nullable=True),
    )
    op.add_column(
        "scores",
        sa.Column("test_score", sa.Float(), nullable=True),
    )
    op.execute(
        """
        UPDATE scores
        SET quality_score = COALESCE(
                (category_scores ->> 'maintainability')::float,
                final_score::float
            ),
            activity_score = COALESCE(
                (category_scores ->> 'change_risk')::float,
                final_score::float
            ),
            test_score = COALESCE(
                (category_scores ->> 'tests')::float,
                0
            )
        """
    )
    op.execute(
        """
        DELETE FROM scores AS older
        USING scores AS newer
        WHERE older.pr_id = newer.pr_id
          AND (
              older.created_at < newer.created_at
              OR (older.created_at = newer.created_at AND older.id < newer.id)
          )
        """
    )
    op.drop_index("ix_scores_score_version_id", table_name="scores")
    op.drop_index("ix_scores_analysis_run_id", table_name="scores")
    op.drop_constraint("uq_scores_deterministic_hash", "scores", type_="unique")
    op.drop_constraint("uq_scores_analysis_run_id", "scores", type_="unique")
    op.drop_constraint("fk_scores_score_version_id", "scores", type_="foreignkey")
    op.drop_constraint("fk_scores_analysis_run_id", "scores", type_="foreignkey")
    op.drop_column("scores", "deterministic_hash")
    op.drop_column("scores", "explanation")
    op.drop_column("scores", "is_authoritative")
    op.drop_column("scores", "input_complete")
    op.drop_column("scores", "confidence")
    op.drop_column("scores", "unavailable_categories")
    op.drop_column("scores", "category_confidence")
    op.drop_column("scores", "category_scores")
    op.drop_column("scores", "scoring_policy_version")
    op.drop_column("scores", "analyzer_suite_version")
    op.drop_column("scores", "head_sha")
    op.drop_column("scores", "score_version_id")
    op.drop_column("scores", "analysis_run_id")
    op.alter_column("scores", "final_score", type_=sa.Float())
    op.alter_column("scores", "quality_score", nullable=False)
    op.alter_column("scores", "activity_score", nullable=False)
    op.alter_column("scores", "test_score", nullable=False)
    op.create_unique_constraint("scores_pr_id_key", "scores", ["pr_id"])

    op.drop_table("analyzer_results")

    op.drop_index("ix_analysis_runs_run_key", table_name="analysis_runs")
    op.drop_constraint("uq_analysis_runs_run_key", "analysis_runs", type_="unique")
    op.drop_column("analysis_runs", "started_at")
    op.drop_column("analysis_runs", "input_complete")
    op.drop_column("analysis_runs", "analyzer_manifest")
    op.drop_column("analysis_runs", "input_hash")
    op.drop_column("analysis_runs", "run_key")
    op.drop_column("analysis_runs", "scoring_policy_version")
    op.drop_column("analysis_runs", "analyzer_version")
    op.execute(
        "UPDATE analysis_runs SET status = 'incomplete' "
        "WHERE status::text IN ('pending', 'running', 'failed')"
    )
    op.alter_column("analysis_runs", "completed_at", nullable=False)
    op.execute("ALTER TYPE analysisrunstatus RENAME TO analysisrunstatus_phase3")
    op.execute("CREATE TYPE analysisrunstatus AS ENUM ('complete', 'incomplete')")
    op.execute(
        "ALTER TABLE analysis_runs ALTER COLUMN status TYPE analysisrunstatus "
        "USING status::text::analysisrunstatus"
    )
    op.create_unique_constraint(
        "uq_analysis_runs_delivery_version",
        "analysis_runs",
        ["delivery_pk", "analysis_version"],
    )
    op.execute("DROP TYPE analysisrunstatus_phase3")

    op.drop_index(
        "ix_repositories_scoring_policy_id", table_name="repositories"
    )
    op.drop_constraint(
        "fk_repositories_scoring_policy_id", "repositories", type_="foreignkey"
    )
    op.drop_column("repositories", "scoring_policy_id")
    op.drop_table("score_versions")
    analyzer_result_status.drop(op.get_bind(), checkfirst=True)
