"""Unit tests for the github schemas."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from github_analyzer.schemas.github import (
    Commit,
    FileEntry,
    RateLimitInfo,
    RepoMetadata,
)


def test_repo_metadata_minimal() -> None:
    meta = RepoMetadata(
        owner="octocat",
        name="Hello-World",
        default_branch="master",
        language_hint="C",
        size_kb=12,
        latest_commit_sha="abc1234def5678",
        is_public=True,
        html_url="https://github.com/octocat/Hello-World",
    )
    assert meta.owner == "octocat"
    assert meta.is_public is True


def test_repo_metadata_is_frozen() -> None:
    meta = RepoMetadata(
        owner="o",
        name="r",
        default_branch="main",
        size_kb=1,
        latest_commit_sha="abcdefg",
        is_public=True,
        html_url="https://github.com/o/r",
    )
    with pytest.raises(ValidationError):
        meta.size_kb = 999  # type: ignore[misc]


def test_file_entry_size_negative_rejected() -> None:
    with pytest.raises(ValidationError):
        FileEntry(relative_path="x.py", size_bytes=-1, language_hint="Python")


def test_commit_round_trip() -> None:
    c = Commit(
        sha="abcdef1234",
        author_login="octocat",
        author_name="Mona",
        author_email="mona@example.com",
        message="initial",
        committed_at=datetime(2026, 5, 11, tzinfo=UTC),
    )
    assert c.sha.startswith("abcdef")


def test_rate_limit_info_resource_default() -> None:
    info = RateLimitInfo(
        limit=5000,
        remaining=4900,
        reset_at=datetime(2026, 5, 11, tzinfo=UTC),
        resource="core",
    )
    assert info.resource == "core"
