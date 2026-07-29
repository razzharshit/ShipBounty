from __future__ import annotations

import hmac
import base64
import hashlib
import secrets
from datetime import datetime
from urllib.parse import urlencode

from fastapi import APIRouter, Cookie, Depends, HTTPException, Request, Response, status
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session

from app.api.authz import get_current_user
from app.core.config import settings
from app.core.security import create_session_token
from app.db.session import get_db
from app.models.authorization import Organization
from app.models.demo import DemoPersona
from app.models.user import User
from app.schemas.authorization import AuthenticatedUserRead
from app.schemas.demo import DemoLoginRead, DemoLoginRequest
from app.services.audit_service import record_audit_event
from app.services.demo_service import demo_mode_enabled
from app.services.identity_service import (
    GitHubIdentityError,
    exchange_oauth_code,
    synchronize_github_identity,
)


router = APIRouter(prefix="/auth", tags=["authentication"])
OAUTH_STATE_COOKIE = "gbd_oauth_state"
OAUTH_PKCE_COOKIE = "gbd_oauth_pkce"


def _secure_cookie() -> bool:
    return settings.APP_ENV.lower() == "production"


@router.get("/github/start")
def start_github_oauth() -> RedirectResponse:
    if not settings.GITHUB_OAUTH_CLIENT_ID:
        raise HTTPException(status_code=503, detail="GitHub OAuth is not configured")
    state_value = secrets.token_urlsafe(32)
    code_verifier = secrets.token_urlsafe(64)
    code_challenge = (
        base64.urlsafe_b64encode(hashlib.sha256(code_verifier.encode()).digest())
        .rstrip(b"=")
        .decode("ascii")
    )
    query = urlencode(
        {
            "client_id": settings.GITHUB_OAUTH_CLIENT_ID,
            "redirect_uri": settings.GITHUB_OAUTH_REDIRECT_URI,
            "state": state_value,
            "code_challenge": code_challenge,
            "code_challenge_method": "S256",
        }
    )
    response = RedirectResponse(
        f"https://github.com/login/oauth/authorize?{query}", status_code=302
    )
    response.set_cookie(
        OAUTH_STATE_COOKIE,
        state_value,
        max_age=600,
        httponly=True,
        secure=_secure_cookie(),
        samesite="lax",
        path="/",
    )
    response.set_cookie(
        OAUTH_PKCE_COOKIE,
        code_verifier,
        max_age=600,
        httponly=True,
        secure=_secure_cookie(),
        samesite="lax",
        path="/",
    )
    return response


@router.get("/github/callback")
def github_oauth_callback(
    request: Request,
    code: str,
    state: str,
    oauth_state: str | None = Cookie(default=None, alias=OAUTH_STATE_COOKIE),
    oauth_code_verifier: str | None = Cookie(default=None, alias=OAUTH_PKCE_COOKIE),
    db: Session = Depends(get_db),
) -> RedirectResponse:
    print("DEBUG OAUTH CALLBACK:")
    print("  request.cookies:", request.cookies)
    print("  oauth_state (from Cookie):", oauth_state)
    print("  oauth_code_verifier (from Cookie):", oauth_code_verifier)
    print("  state (from Query):", state)
    if (
        not oauth_state
        or not oauth_code_verifier
        or not hmac.compare_digest(state, oauth_state)
    ):
        raise HTTPException(status_code=400, detail="Invalid OAuth state")
    try:
        oauth_payload = exchange_oauth_code(code, oauth_code_verifier)
        user = synchronize_github_identity(db, oauth_payload)
        record_audit_event(
            db,
            action="auth.login",
            resource_type="user",
            actor_user_id=user.id,
            resource_id=user.id,
            event_metadata={"provider": "github"},
            request=request,
        )
        session_token = create_session_token(user.id, user.session_version)
        db.commit()
    except (GitHubIdentityError, RuntimeError) as exc:
        db.rollback()
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    response = RedirectResponse(f"{settings.FRONTEND_URL}/dashboard", status_code=302)
    response.delete_cookie(OAUTH_STATE_COOKIE, path="/")
    response.delete_cookie(OAUTH_PKCE_COOKIE, path="/")
    response.set_cookie(
        settings.SESSION_COOKIE_NAME,
        session_token,
        max_age=settings.AUTH_SESSION_TTL_SECONDS,
        httponly=True,
        secure=_secure_cookie(),
        samesite="lax",
        path="/",
        domain=settings.SESSION_COOKIE_DOMAIN or None,
    )
    return response


@router.get("/me", response_model=AuthenticatedUserRead)
def auth_me(user: User = Depends(get_current_user)) -> User:
    return user


@router.post("/demo", response_model=DemoLoginRead)
def demo_login(
    payload: DemoLoginRequest,
    request: Request,
    response: Response,
    db: Session = Depends(get_db),
) -> DemoLoginRead:
    # Return 404 when disabled so production does not advertise a dormant
    # alternate authentication surface.
    if not demo_mode_enabled():
        raise HTTPException(status_code=404, detail="Not found")
    if len(settings.DEMO_ACCESS_KEY) < 16:
        raise HTTPException(
            status_code=503,
            detail="Demo access is not configured safely",
        )
    if not hmac.compare_digest(payload.access_key, settings.DEMO_ACCESS_KEY):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid demo workspace or access key",
        )

    from app.services.demo_service import ensure_demo_personas_for_organization

    workspace_slug = payload.workspace.strip().lower()
    mapping = (
        db.query(DemoPersona)
        .join(Organization, Organization.id == DemoPersona.organization_id)
        .filter(
            Organization.login == workspace_slug,
            DemoPersona.persona == payload.persona,
        )
        .first()
    )
    if mapping is None:
        if ensure_demo_personas_for_organization(db, workspace_slug):
            mapping = (
                db.query(DemoPersona)
                .join(Organization, Organization.id == DemoPersona.organization_id)
                .filter(
                    DemoPersona.persona == payload.persona,
                )
                .first()
            )

    if mapping is None or not mapping.user.is_active:
        available_orgs = [o.login for o in db.query(Organization).all()]
        org_hint = f" Available organizations: {', '.join(available_orgs)}" if available_orgs else " No organizations found in DB."
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f"Invalid demo workspace or access key.{org_hint}",
        )

    user = mapping.user
    user.last_login_at = datetime.utcnow()
    record_audit_event(
        db,
        action="auth.demo_login",
        resource_type="user",
        actor_user_id=user.id,
        organization_id=mapping.organization_id,
        resource_id=user.id,
        event_metadata={
            "provider": "demo",
            "persona": mapping.persona,
            "workspace": mapping.organization.login,
        },
        request=request,
    )
    session_token = create_session_token(user.id, user.session_version)
    db.commit()
    response.set_cookie(
        settings.SESSION_COOKIE_NAME,
        session_token,
        max_age=settings.AUTH_SESSION_TTL_SECONDS,
        httponly=True,
        secure=_secure_cookie(),
        samesite="lax",
        path="/",
        domain=settings.SESSION_COOKIE_DOMAIN or None,
    )
    return DemoLoginRead(
        workspace=mapping.organization.login,
        persona=mapping.persona,
        user=AuthenticatedUserRead.model_validate(user),
    )


@router.post("/logout", status_code=204)
def logout(
    request: Request,
    response: Response,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> None:
    record_audit_event(
        db,
        action="auth.logout",
        resource_type="user",
        actor_user_id=user.id,
        resource_id=user.id,
        request=request,
    )
    user.session_version += 1
    db.commit()
    response.delete_cookie(
        settings.SESSION_COOKIE_NAME,
        path="/",
        domain=settings.SESSION_COOKIE_DOMAIN or None,
    )
