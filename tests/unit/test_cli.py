"""Smoke tests for the Typer CLI stub (M0.3)."""

from __future__ import annotations

from typer.testing import CliRunner

from github_analyzer import __version__
from github_analyzer.cli import app

runner = CliRunner()


def test_cli_help_exits_zero() -> None:
    """`github-analyzer --help` exits 0 and mentions the project name."""
    result = runner.invoke(app, ["--help"])
    assert result.exit_code == 0
    assert "github-analyzer" in result.stdout.lower()


def test_cli_version_prints_and_exits_zero() -> None:
    """`github-analyzer --version` prints the version and exits 0."""
    result = runner.invoke(app, ["--version"])
    assert result.exit_code == 0
    assert __version__ in result.stdout
