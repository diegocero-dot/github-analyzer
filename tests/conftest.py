"""Top-level pytest configuration.

Adds the `--integration` flag and auto-skips integration-marked tests when
the flag is absent (CLAUDE.md "Test Rules").
"""

from __future__ import annotations

import pytest


def pytest_addoption(parser: pytest.Parser) -> None:
    """Register the `--integration` flag."""
    parser.addoption(
        "--integration",
        action="store_true",
        default=False,
        help="Run integration tests (slow, requires live services + API keys).",
    )


def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    """Skip integration-marked tests unless `--integration` is passed."""
    if config.getoption("--integration"):
        return
    skip_integration = pytest.mark.skip(reason="needs --integration flag to run")
    for item in items:
        if "integration" in item.keywords:
            item.add_marker(skip_integration)
