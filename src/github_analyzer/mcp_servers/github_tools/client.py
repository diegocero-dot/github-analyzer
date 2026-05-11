"""Thin httpx.AsyncClient wrapper for the GitHub REST API.

- Adds `Authorization: Bearer <token>` if `GITHUB_TOKEN` is set.
- Sets `Accept: application/vnd.github+json` and the recommended
  `X-GitHub-Api-Version: 2022-11-28`.
- Wraps requests in `retry_with_backoff` for rate-limit resilience.

The client is constructed per-call (not a long-lived singleton) so that
test isolation via `respx` works without monkeypatching a global.
"""

from __future__ import annotations

from typing import Any

import httpx

from github_analyzer.config import get_settings
from github_analyzer.mcp_servers.github_tools.rate_limit import retry_with_backoff

_API_BASE = "https://api.github.com"
_DEFAULT_TIMEOUT = httpx.Timeout(connect=5.0, read=30.0, write=30.0, pool=5.0)


def _build_headers(token: str) -> dict[str, str]:
    headers: dict[str, str] = {
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
        "User-Agent": "github-analyzer/0.0.1 (+https://github.com/diegocero-dot/github-analyzer)",
    }
    if token:
        headers["Authorization"] = f"Bearer {token}"
    return headers


async def get_json(
    path: str, *, params: dict[str, Any] | None = None
) -> dict[str, Any] | list[Any]:
    """`GET {API_BASE}{path}` and return parsed JSON.

    Applies rate-limit backoff. Raises `httpx.HTTPStatusError` on non-2xx
    that is NOT a rate-limit response (those are retried internally).
    Raises `RateLimitExceededError` if rate-limit retries are exhausted.
    """
    settings = get_settings()
    headers = _build_headers(settings.github_token)
    url = f"{_API_BASE}{path}"

    async with httpx.AsyncClient(timeout=_DEFAULT_TIMEOUT, headers=headers) as client:

        async def _send() -> httpx.Response:
            return await client.get(url, params=params)

        response = await retry_with_backoff(_send)

    response.raise_for_status()
    return response.json()  # type: ignore[no-any-return]
