from __future__ import annotations

import secrets
from datetime import datetime, timedelta, timezone

import jwt
from cryptography.fernet import Fernet, InvalidToken
from fastapi import HTTPException, status

from app.core.config import settings


def _keyring(raw: str, setting_name: str) -> list[tuple[str, str]]:
    keys: list[tuple[str, str]] = []
    for entry in raw.split(","):
        entry = entry.strip()
        if not entry:
            continue
        key_id, separator, secret = entry.partition(":")
        if not separator or not key_id or not secret:
            raise RuntimeError(f"{setting_name} entries must use key-id:secret")
        keys.append((key_id, secret))
    if not keys:
        raise RuntimeError(f"{setting_name} is not configured")
    return keys


def create_session_token(user_id: int, session_version: int = 0) -> str:
    key_id, secret = _keyring(settings.AUTH_JWT_KEYS, "AUTH_JWT_KEYS")[0]
    if len(secret.encode("utf-8")) < 32:
        raise RuntimeError("The primary JWT signing secret must be at least 32 bytes")
    now = datetime.now(timezone.utc)
    payload = {
        "sub": str(user_id),
        "type": "session",
        "ver": session_version,
        "jti": secrets.token_urlsafe(24),
        "iat": now,
        "nbf": now,
        "exp": now + timedelta(seconds=settings.AUTH_SESSION_TTL_SECONDS),
        "iss": settings.AUTH_JWT_ISSUER,
        "aud": settings.AUTH_JWT_AUDIENCE,
    }
    return jwt.encode(payload, secret, algorithm="HS256", headers={"kid": key_id})


def decode_session_token(token: str) -> tuple[int, int]:
    try:
        header = jwt.get_unverified_header(token)
        key_id = header.get("kid")
        keys = dict(_keyring(settings.AUTH_JWT_KEYS, "AUTH_JWT_KEYS"))
        secret = keys.get(key_id)
        if not secret:
            raise jwt.InvalidTokenError("Unknown signing key")
        payload = jwt.decode(
            token,
            secret,
            algorithms=["HS256"],
            issuer=settings.AUTH_JWT_ISSUER,
            audience=settings.AUTH_JWT_AUDIENCE,
            options={"require": ["sub", "type", "ver", "jti", "iat", "nbf", "exp"]},
        )
        if payload.get("type") != "session":
            raise jwt.InvalidTokenError("Wrong token type")
        return int(payload["sub"]), int(payload["ver"])
    except (jwt.PyJWTError, ValueError, RuntimeError) as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired session",
            headers={"WWW-Authenticate": "Bearer"},
        ) from exc


def encrypt_oauth_token(token: str) -> tuple[str, str]:
    key_id, key = _keyring(
        settings.TOKEN_ENCRYPTION_KEYS, "TOKEN_ENCRYPTION_KEYS"
    )[0]
    ciphertext = Fernet(key.encode("ascii")).encrypt(token.encode("utf-8"))
    return ciphertext.decode("ascii"), key_id


def decrypt_oauth_token(ciphertext: str, key_id: str) -> str:
    keys = dict(_keyring(settings.TOKEN_ENCRYPTION_KEYS, "TOKEN_ENCRYPTION_KEYS"))
    key = keys.get(key_id)
    if not key:
        raise RuntimeError(f"Encryption key {key_id!r} is unavailable")
    try:
        return (
            Fernet(key.encode("ascii"))
            .decrypt(ciphertext.encode("ascii"))
            .decode("utf-8")
        )
    except InvalidToken as exc:
        raise RuntimeError("Stored OAuth token could not be decrypted") from exc
