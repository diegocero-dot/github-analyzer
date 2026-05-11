"""Smoke tests for Pydantic Settings."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import pytest

from github_analyzer.config import Settings, get_settings


def test_settings_defaults_are_empty_strings(monkeypatch: pytest.MonkeyPatch) -> None:
    """With no env vars set, every secret defaults to an empty string."""
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("QDRANT_API_KEY", raising=False)

    settings = Settings(_env_file=None)  # type: ignore[call-arg]
    assert settings.github_token == ""
    assert settings.anthropic_api_key == ""
    assert settings.openai_api_key == ""
    assert settings.qdrant_url == "http://localhost:6333"
    assert settings.qdrant_api_key == ""


def test_get_settings_reads_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    """`get_settings()` picks up env vars at call time."""
    monkeypatch.setenv("GITHUB_TOKEN", "ghp_test")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test")

    settings = get_settings()
    assert settings.github_token == "ghp_test"
    assert settings.anthropic_api_key == "sk-ant-test"
