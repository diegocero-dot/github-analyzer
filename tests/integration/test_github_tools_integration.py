"""Integration tests against real GitHub + real git clone.

Requires GITHUB_TOKEN in the environment. Skipped without --integration.
"""

from __future__ import annotations

import os
import shutil

import pytest

from github_analyzer.mcp_servers.github_tools import (
    clone_shallow,
    get_commits,
    list_files,
    repo_metadata,
)

_TEST_REPO = "https://github.com/octocat/Hello-World"
_TEST_OWNER = "octocat"
_TEST_REPO_NAME = "Hello-World"


@pytest.fixture
def require_token() -> str:
    token = os.environ.get("GITHUB_TOKEN", "")
    if not token:
        pytest.skip("GITHUB_TOKEN not set — skipping live GitHub integration tests.")
    return token


@pytest.mark.integration
async def test_repo_metadata_live(require_token: str) -> None:
    meta = await repo_metadata(_TEST_REPO)
    assert meta.owner == _TEST_OWNER
    assert meta.name == _TEST_REPO_NAME
    assert meta.is_public is True
    assert len(meta.latest_commit_sha) == 40


@pytest.mark.integration
async def test_clone_and_list_files_live(require_token: str) -> None:
    clone = await clone_shallow(_TEST_REPO)
    try:
        files = await list_files(clone.local_path)
        # Hello-World contains at minimum a README.
        assert any(
            f.relative_path.lower() == "readme" or f.relative_path.lower().startswith("readme")
            for f in files
        )
    finally:
        shutil.rmtree(clone.local_path.parent, ignore_errors=True)


@pytest.mark.integration
async def test_get_commits_live(require_token: str) -> None:
    commits = await get_commits(_TEST_OWNER, _TEST_REPO_NAME, limit=3)
    assert 1 <= len(commits) <= 3
    for c in commits:
        assert len(c.sha) == 40
