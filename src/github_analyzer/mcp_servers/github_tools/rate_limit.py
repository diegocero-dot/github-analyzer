"""Rate-limit handling for the GitHub REST API.

Approach (ARCHITECTURE.md §3.2):
- Track remaining quota from response headers (`X-RateLimit-*`).
- Exponential backoff (1s, 2s, 4s, 8s) on 403 + 429 responses.
- Cap retries at 4.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from github_analyzer.observability.logging import get_logger
from github_analyzer.schemas.github import RateLimitInfo

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

    import httpx

logger = get_logger(__name__)

# Backoff schedule (seconds). Tuned for GitHub's 60s reset window quirks.
_BACKOFF_SCHEDULE: tuple[float, ...] = (1.0, 2.0, 4.0, 8.0)
_RATE_LIMIT_STATUS_CODES: frozenset[int] = frozenset({403, 429})


class RateLimitExceededError(RuntimeError):
    """Raised when retries are exhausted on a rate-limited endpoint."""

    def __init__(self, info: RateLimitInfo | None) -> None:
        msg = (
            f"GitHub API rate limit exceeded. Remaining={info.remaining if info else 'unknown'}, "
            f"reset_at={info.reset_at.isoformat() if info else 'unknown'}"
        )
        super().__init__(msg)
        self.info = info


def parse_rate_limit_headers(response: httpx.Response) -> RateLimitInfo | None:
    """Extract `RateLimitInfo` from response headers, if present.

    Returns None if any of the expected headers are missing.
    """
    headers = response.headers
    limit_h = headers.get("X-RateLimit-Limit")
    remaining_h = headers.get("X-RateLimit-Remaining")
    reset_h = headers.get("X-RateLimit-Reset")
    resource_h = headers.get("X-RateLimit-Resource", "core")

    if not (limit_h and remaining_h and reset_h):
        return None

    return RateLimitInfo(
        limit=int(limit_h),
        remaining=int(remaining_h),
        reset_at=datetime.fromtimestamp(int(reset_h), tz=UTC),
        resource=resource_h,
    )


async def retry_with_backoff(
    request_fn: Callable[..., Awaitable[httpx.Response]],
    *args: object,
    **kwargs: object,
) -> httpx.Response:
    """Execute `request_fn(*args, **kwargs)` with exponential backoff on rate-limit errors.

    Raises `RateLimitExceededError` if all retries are exhausted.
    Non-rate-limit errors propagate immediately.
    """
    last_info: RateLimitInfo | None = None

    for attempt, delay in enumerate(_BACKOFF_SCHEDULE):
        response = await request_fn(*args, **kwargs)
        if response.status_code not in _RATE_LIMIT_STATUS_CODES:
            return response

        last_info = parse_rate_limit_headers(response)
        logger.warning(
            "github.rate_limit.hit",
            attempt=attempt + 1,
            status=response.status_code,
            backoff_s=delay,
            remaining=last_info.remaining if last_info else None,
        )
        await asyncio.sleep(delay)

    # Final attempt (no further sleep)
    response = await request_fn(*args, **kwargs)
    if response.status_code not in _RATE_LIMIT_STATUS_CODES:
        return response

    last_info = parse_rate_limit_headers(response) or last_info
    raise RateLimitExceededError(last_info)
