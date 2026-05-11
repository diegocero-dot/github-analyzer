"""Placeholder integration test — confirms the `--integration` gate works.

Real integration tests land in M1+ (MCP server, Qdrant, LLM clients).
"""

from __future__ import annotations

import pytest


@pytest.mark.integration
def test_integration_marker_is_active() -> None:
    """Trivial assertion — only runs when `--integration` is passed."""
    assert True
