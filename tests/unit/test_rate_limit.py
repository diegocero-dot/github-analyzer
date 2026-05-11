"""Unit tests for the rate-limit backoff helper."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime

import httpx
import pytest

from github_analyzer.mcp_servers.github_tools.rate_limit import (
    RateLimitExceededError,
    parse_rate_limit_headers,
    retry_with_backoff,
)


def _make_response(status: int) -> httpx.Response:
    headers = {
        "X-RateLimit-Limit": "5000",
        "X-RateLimit-Remaining": "0",
        "X-RateLimit-Reset": str(int(datetime(2026, 5, 11, tzinfo=UTC).timestamp())),
        "X-RateLimit-Resource": "core",
    }
    return httpx.Response(status_code=status, headers=headers)


async def _no_sleep(_delay: float) -> None:
    """Replacement for `asyncio.sleep` used in tests — instant, non-recursive.

    DO NOT use `lambda _t: asyncio.sleep(0)` as a monkeypatch target: once
    `asyncio.sleep` is patched, the lambda calls the patched version (itself)
    and recurses infinitely. A plain `async def` that returns None is safe.
    """
    return None


def test_parse_rate_limit_headers_present() -> None:
    info = parse_rate_limit_headers(_make_response(200))
    assert info is not None
    assert info.limit == 5000
    assert info.remaining == 0


def test_parse_rate_limit_headers_absent() -> None:
    response = httpx.Response(status_code=200)
    assert parse_rate_limit_headers(response) is None


async def test_retry_with_backoff_returns_first_2xx(monkeypatch: pytest.MonkeyPatch) -> None:
    """If the first response is 200, no backoff is needed."""
    monkeypatch.setattr(asyncio, "sleep", _no_sleep)

    async def request() -> httpx.Response:
        return httpx.Response(status_code=200)

    result = await retry_with_backoff(request)
    assert result.status_code == 200


async def test_retry_with_backoff_exhausts(monkeypatch: pytest.MonkeyPatch) -> None:
    """All 5 attempts return 429 → RateLimitExceededError."""
    monkeypatch.setattr(asyncio, "sleep", _no_sleep)

    async def request() -> httpx.Response:
        return _make_response(429)

    with pytest.raises(RateLimitExceededError):
        await retry_with_backoff(request)


async def test_retry_with_backoff_recovers(monkeypatch: pytest.MonkeyPatch) -> None:
    """Returns the first non-rate-limit response after some retries."""
    monkeypatch.setattr(asyncio, "sleep", _no_sleep)
    calls = {"n": 0}

    async def request() -> httpx.Response:
        calls["n"] += 1
        if calls["n"] < 3:
            return _make_response(403)
        return httpx.Response(status_code=200)

    result = await retry_with_backoff(request)
    assert result.status_code == 200
    assert calls["n"] == 3
