import logging
import time

import jwt
import requests
from fastapi import HTTPException, status

from app.core.config import settings


logger = logging.getLogger(__name__)


def generate_jwt() -> str:
    if not settings.GITHUB_APP_ID or not settings.GITHUB_PRIVATE_KEY:
        logger.error("GitHub App credentials are missing in environment variables.")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="GitHub App credentials are not configured",
        )

    now = int(time.time())
    payload = {
        "iat": now,
        "exp": now + 600,
        "iss": settings.GITHUB_APP_ID,
    }
    private_key = settings.GITHUB_PRIVATE_KEY.replace("\\n", "\n")
    encoded = jwt.encode(payload, private_key, algorithm="RS256")
    return encoded if isinstance(encoded, str) else encoded.decode("utf-8")


def get_installation_token(installation_id: int) -> str:
    app_jwt = generate_jwt()
    url = f"https://api.github.com/app/installations/{installation_id}/access_tokens"
    headers = {
        "Authorization": f"Bearer {app_jwt}",
        "Accept": "application/vnd.github+json",
    }

    try:
        response = requests.post(url, headers=headers, timeout=15)
    except requests.RequestException as exc:
        logger.exception("Failed to request installation token: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Unable to reach GitHub for installation token",
        ) from exc

    if response.status_code >= 400:
        logger.error(
            "GitHub installation token request failed: installation_id=%s status=%s",
            installation_id,
            response.status_code,
        )
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Failed to generate installation access token",
        )

    token = response.json().get("token")
    if not token:
        logger.error("Installation token missing in GitHub response for installation_id=%s", installation_id)
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="GitHub did not return an installation token",
        )

    return token
