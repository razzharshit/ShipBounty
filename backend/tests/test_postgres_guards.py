from __future__ import annotations

import os
import subprocess
import sys

import pytest
from sqlalchemy import create_engine, text


pytestmark = pytest.mark.integration


def _url() -> str:
    value = os.getenv("TEST_POSTGRES_URL")
    if not value:
        pytest.skip("TEST_POSTGRES_URL is not configured")
    return value


def test_migrations_render_offline_and_round_trip():
    env = {**os.environ, "DATABASE_URL": _url()}
    rendered = subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", "head", "--sql"],
        cwd=os.path.dirname(os.path.dirname(__file__)),
        env=env,
        check=True,
        capture_output=True,
        text=True,
    ).stdout
    assert "default-v1" in rendered
    subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", "head"],
        cwd=os.path.dirname(os.path.dirname(__file__)),
        env=env,
        check=True,
    )
    subprocess.run(
        [sys.executable, "-m", "alembic", "downgrade", "20260725_0007"],
        cwd=os.path.dirname(os.path.dirname(__file__)),
        env=env,
        check=True,
    )
    subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", "head"],
        cwd=os.path.dirname(os.path.dirname(__file__)),
        env=env,
        check=True,
    )


def test_confirmed_payout_guard_is_installed():
    engine = create_engine(_url())
    try:
        with engine.connect() as connection:
            row = connection.execute(
                text(
                    """
                    SELECT pg_get_triggerdef(trigger.oid),
                           pg_get_functiondef(trigger.tgfoid)
                    FROM pg_trigger AS trigger
                    WHERE trigger.tgname = 'trg_provider_confirmed_payout'
                      AND NOT trigger.tgisinternal
                    """
                )
            ).one()
        trigger_definition, function_definition = row
        assert "DEFERRABLE INITIALLY DEFERRED" in trigger_definition
        assert "provider_reference IS NULL" in function_definition
        assert "transaction_hash IS NULL" in function_definition
        assert "payout_reconciliations" in function_definition
        assert "outcome = 'confirmed'" in function_definition
    finally:
        engine.dispose()
