from __future__ import annotations

import logging
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from typing import Optional
from urllib.parse import urlparse

import requests
from fastapi import HTTPException, status


logger = logging.getLogger(__name__)
GITHUB_API_ROOT = "https://api.github.com"
GITHUB_PR_FILE_LIMIT = 3000


@dataclass(frozen=True)
class GitHubFileSnapshot:
    files: list[dict]
    limit_reached: bool


@dataclass(frozen=True)
class GitHubCheckSnapshot:
    check_runs: list[dict]
    limit_reached: bool
    error: Optional[str] = None


@dataclass(frozen=True)
class _PaginatedResult:
    items: list[dict]
    limit_reached: bool = False


@dataclass(frozen=True)
class GitHubRateLimitContext:
    installation_id: int
    organization_id: int | None
    repository_id: int | None


_rate_limit_context: ContextVar[GitHubRateLimitContext | None] = ContextVar(
    "github_rate_limit_context", default=None
)


@contextmanager
def github_rate_limit_scope(
    *,
    installation_id: int,
    organization_id: int | None,
    repository_id: int | None,
):
    token = _rate_limit_context.set(
        GitHubRateLimitContext(
            installation_id=installation_id,
            organization_id=organization_id,
            repository_id=repository_id,
        )
    )
    try:
        yield
    finally:
        _rate_limit_context.reset(token)


def _request(
    url: str,
    token: str,
    params: Optional[dict] = None,
    *,
    allowed_error_statuses: tuple[int, ...] = (),
) -> requests.Response:
    parsed_url = urlparse(url)
    if parsed_url.scheme != "https" or parsed_url.netloc != "api.github.com":
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="GitHub returned an invalid pagination URL",
        )

    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    try:
        response = requests.get(url, headers=headers, params=params, timeout=20)
    except requests.RequestException as exc:
        logger.exception("Failed to fetch GitHub data: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Unable to reach GitHub",
        ) from exc

    if response.status_code >= 400 and response.status_code not in allowed_error_statuses:
        logger.error(
            "GitHub request failed: url=%s status=%s body=%s",
            url,
            response.status_code,
            response.text,
        )
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="GitHub API request failed",
        )
    context = _rate_limit_context.get()
    if context is not None:
        try:
            from app.services.operations_service import record_github_rate_limit

            record_github_rate_limit(
                installation_id=context.installation_id,
                organization_id=context.organization_id,
                repository_id=context.repository_id,
                headers=response.headers,
            )
        except Exception:
            logger.exception("Failed to persist GitHub API rate-limit headers")
    return response


def _response_json(response: requests.Response) -> dict | list:
    try:
        return response.json()
    except requests.JSONDecodeError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="GitHub returned invalid JSON",
        ) from exc


def _get_json(url: str, token: str, params: Optional[dict] = None) -> dict | list:
    return _response_json(_request(url, token, params))


def get_pull_request(repo_full_name: str, pr_number: int, token: str) -> dict:
    result = _get_json(
        f"{GITHUB_API_ROOT}/repos/{repo_full_name}/pulls/{pr_number}",
        token,
    )
    if not isinstance(result, dict):
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Invalid pull request response from GitHub",
        )
    return result


def get_all_pull_requests(repo_full_name: str, token: str) -> list[dict]:
    """Return open and closed pull requests for operator identity backfills."""
    return _get_paginated_list(
        (
            f"{GITHUB_API_ROOT}/repos/{repo_full_name}/pulls"
            "?state=all&sort=updated&direction=desc"
        ),
        token,
    ).items


def _get_paginated_list(
    url: str,
    token: str,
    *,
    max_items: Optional[int] = None,
) -> _PaginatedResult:
    items: list[dict] = []
    next_url: Optional[str] = url
    params: Optional[dict] = {"per_page": 100, "page": 1}
    fallback_page = 1

    while next_url:
        response = _request(next_url, token, params)
        result = _response_json(response)
        if not isinstance(result, list):
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail="Invalid paginated response from GitHub",
            )
        items.extend(item for item in result if isinstance(item, dict))

        if max_items is not None and len(items) >= max_items:
            return _PaginatedResult(items=items[:max_items], limit_reached=True)

        link_next = (response.links.get("next") or {}).get("url")
        if link_next:
            fallback_page += 1
            next_url = str(link_next)
            params = None
            continue

        # GitHub normally supplies rel="next". The arithmetic fallback protects
        # against proxies that strip Link while retaining the documented page API.
        if len(result) == 100:
            fallback_page += 1
            next_url = url
            params = {"per_page": 100, "page": fallback_page}
            continue

        next_url = None

    return _PaginatedResult(items=items)


def get_pr_files(repo_full_name: str, pr_number: int, token: str) -> GitHubFileSnapshot:
    result = _get_paginated_list(
        f"{GITHUB_API_ROOT}/repos/{repo_full_name}/pulls/{pr_number}/files",
        token,
        max_items=GITHUB_PR_FILE_LIMIT,
    )
    logger.info(
        "Fetched %s PR files for %s#%s (limit_reached=%s)",
        len(result.items),
        repo_full_name,
        pr_number,
        result.limit_reached,
    )
    return GitHubFileSnapshot(
        files=result.items,
        limit_reached=result.limit_reached,
    )


def get_pr_reviews(repo_full_name: str, pr_number: int, token: str) -> list[dict]:
    return _get_paginated_list(
        f"{GITHUB_API_ROOT}/repos/{repo_full_name}/pulls/{pr_number}/reviews",
        token,
    ).items


def get_check_runs(
    repo_full_name: str,
    head_sha: str,
    token: str,
) -> GitHubCheckSnapshot:
    items: list[dict] = []
    base_url = (
        f"{GITHUB_API_ROOT}/repos/{repo_full_name}/commits/{head_sha}/check-runs"
    )
    next_url: Optional[str] = base_url
    params: Optional[dict] = {"per_page": 100, "page": 1, "filter": "latest"}
    fallback_page = 1
    while next_url:
        response = _request(
            next_url,
            token,
            params,
            allowed_error_statuses=(403, 404),
        )
        if response.status_code == 403:
            return GitHubCheckSnapshot(
                check_runs=[],
                limit_reached=False,
                error="GitHub Checks permission is unavailable",
            )
        if response.status_code == 404:
            return GitHubCheckSnapshot(
                check_runs=[],
                limit_reached=False,
                error="GitHub check runs were not found for the head SHA",
            )
        payload = _response_json(response)
        if not isinstance(payload, dict) or not isinstance(
            payload.get("check_runs"), list
        ):
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail="Invalid check-runs response from GitHub",
            )
        page = [item for item in payload["check_runs"] if isinstance(item, dict)]
        items.extend(page)
        if len(items) >= 1000:
            return GitHubCheckSnapshot(
                check_runs=items[:1000],
                limit_reached=True,
            )

        link_next = (response.links.get("next") or {}).get("url")
        if link_next:
            fallback_page += 1
            next_url = str(link_next)
            params = None
            continue
        if len(page) == 100:
            fallback_page += 1
            next_url = base_url
            params = {
                "per_page": 100,
                "page": fallback_page,
                "filter": "latest",
            }
            continue
        next_url = None

    return GitHubCheckSnapshot(check_runs=items, limit_reached=False)
