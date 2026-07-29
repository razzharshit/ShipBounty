from __future__ import annotations

from fastapi.testclient import TestClient
import pytest

from app.core.config import Settings, settings
from app.db.session import get_db
from app.main import app
from app.models.authorization import (
    AuthorizationRole,
    AuditLog,
    Organization,
    OrganizationMembership,
    RepositoryPermission,
)
from app.models.demo import DemoPersona
from app.models.pull_request import PullRequest
from app.models.repository import Repository
from app.models.user import User
from app.services.demo_service import bootstrap_demo_workspace
from app.services.demo_service import demo_mode_enabled


def test_production_configuration_rejects_demo_mode(monkeypatch):
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.setenv("DEMO_MODE", "true")
    with pytest.raises(RuntimeError, match="cannot be enabled in production"):
        Settings()


def _ingested_pull_request(db):
    author = User(github_id=101, username="real-contributor")
    organization = Organization(github_org_id=201, login="demo-acme")
    db.add_all([author, organization])
    db.flush()
    repository = Repository(
        github_repo_id=301,
        organization_id=organization.id,
        name="showcase",
        owner="demo-acme",
        full_name="demo-acme/showcase",
    )
    db.add(repository)
    db.flush()
    pull_request = PullRequest(
        github_pr_id=7,
        github_pr_number=7,
        title="Showcase contribution",
        author_id=author.id,
        repo_id=repository.id,
    )
    db.add(pull_request)
    db.commit()
    return author, organization, repository, pull_request


def test_demo_bootstrap_is_idempotent_and_maps_real_author(session_factory):
    db = session_factory()
    author, organization, repository, pull_request = _ingested_pull_request(db)

    first = bootstrap_demo_workspace(
        db,
        repository_full_name=repository.full_name,
        pull_request_number=7,
    )
    second = bootstrap_demo_workspace(
        db,
        repository_full_name=repository.full_name,
        pull_request_number=7,
    )
    db.commit()

    assert first == second
    assert first.pull_request_id == pull_request.id
    assert db.query(DemoPersona).count() == 4
    contributor = (
        db.query(DemoPersona)
        .filter(
            DemoPersona.organization_id == organization.id,
            DemoPersona.persona == "contributor",
        )
        .one()
    )
    assert contributor.user_id == author.id
    assert db.query(OrganizationMembership).count() == 4
    assert db.query(RepositoryPermission).count() == 4
    assert {
        permission.role for permission in db.query(RepositoryPermission).all()
    } == {
        AuthorizationRole.OWNER,
        AuthorizationRole.REVIEWER,
        AuthorizationRole.ADMIN,
        AuthorizationRole.CONTRIBUTOR,
    }
    db.close()


def test_demo_login_is_fail_closed_and_audited(session_factory):
    db = session_factory()
    _, _, repository, _ = _ingested_pull_request(db)
    workspace = bootstrap_demo_workspace(
        db,
        repository_full_name=repository.full_name,
        pull_request_number=7,
    )
    db.commit()

    def override_db():
        try:
            yield db
        finally:
            pass

    old_mode = settings.DEMO_MODE
    old_environment = settings.APP_ENV
    old_key = settings.DEMO_ACCESS_KEY
    old_jwt_keys = settings.AUTH_JWT_KEYS
    app.dependency_overrides[get_db] = override_db
    try:
        settings.DEMO_MODE = False
        response = TestClient(app).post(
            "/auth/demo",
            json={
                "workspace": workspace.workspace,
                "persona": "owner",
                "access_key": "correct-demo-access-key",
            },
        )
        assert response.status_code == 404

        settings.DEMO_MODE = True
        settings.APP_ENV = "development"
        settings.DEMO_ACCESS_KEY = "correct-demo-access-key"
        settings.AUTH_JWT_KEYS = (
            "demo:test-signing-key-with-at-least-32-bytes"
        )
        client = TestClient(app)
        response = client.post(
            "/auth/demo",
            json={
                "workspace": workspace.workspace,
                "persona": "owner",
                "access_key": "wrong-demo-access-key",
            },
        )
        assert response.status_code == 401

        response = client.post(
            "/auth/demo",
            json={
                "workspace": workspace.workspace,
                "persona": "owner",
                "access_key": settings.DEMO_ACCESS_KEY,
            },
        )
        assert response.status_code == 200
        assert response.json()["persona"] == "owner"
        assert response.json()["user"]["username"].endswith("-owner")
        assert client.get("/auth/me").status_code == 200
        assert (
            db.query(AuditLog)
            .filter(AuditLog.action == "auth.demo_login")
            .count()
            == 1
        )

        settings.APP_ENV = "production"
        assert demo_mode_enabled() is False
    finally:
        app.dependency_overrides.clear()
        settings.DEMO_MODE = old_mode
        settings.APP_ENV = old_environment
        settings.DEMO_ACCESS_KEY = old_key
        settings.AUTH_JWT_KEYS = old_jwt_keys
        db.close()
