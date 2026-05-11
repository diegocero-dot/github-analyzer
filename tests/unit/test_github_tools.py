"""Unit tests for the github-tools tools (mocked HTTP + filesystem)."""

from __future__ import annotations

from pathlib import Path

import pytest
import respx
from httpx import Response

from github_analyzer.mcp_servers.github_tools.tools import (
    DEFAULT_EXTENSIONS,
    FetchError,
    FileTooLargeError,
    InvalidRepoUrlError,
    RepoNotFoundError,
    RepoTooLargeError,
    _classify_language,
    _parse_url,
    get_commits,
    get_file_content,
    list_files,
    repo_metadata,
)

# ─────────── URL parsing ───────────


@pytest.mark.parametrize(
    "url, expected",
    [
        ("https://github.com/octocat/Hello-World", ("octocat", "Hello-World")),
        ("https://github.com/octocat/Hello-World.git", ("octocat", "Hello-World")),
        ("https://github.com/octocat/Hello-World/", ("octocat", "Hello-World")),
        ("http://github.com/owner/repo", ("owner", "repo")),
    ],
)
def test_parse_url_accepts_valid(url: str, expected: tuple[str, str]) -> None:
    assert _parse_url(url) == expected


@pytest.mark.parametrize(
    "url",
    ["", "not-a-url", "https://gitlab.com/x/y", "https://github.com/onlyowner"],
)
def test_parse_url_rejects_invalid(url: str) -> None:
    with pytest.raises(InvalidRepoUrlError):
        _parse_url(url)


def test_classify_language_known_extension() -> None:
    assert _classify_language("foo.py") == "Python"
    assert _classify_language("Bar.TS") == "TypeScript"


def test_classify_language_unknown_extension() -> None:
    assert _classify_language("README") is None


# ─────────── repo_metadata ───────────


@respx.mock
async def test_repo_metadata_happy_path() -> None:
    respx.get("https://api.github.com/repos/octocat/Hello-World").mock(
        return_value=Response(
            200,
            json={
                "owner": {"login": "octocat"},
                "name": "Hello-World",
                "default_branch": "master",
                "language": "C",
                "size": 12,
                "private": False,
                "html_url": "https://github.com/octocat/Hello-World",
            },
        )
    )
    respx.get("https://api.github.com/repos/octocat/Hello-World/branches/master").mock(
        return_value=Response(
            200,
            json={"commit": {"sha": "abc1234def5678abc1234def5678abc1234def56"}},
        )
    )
    meta = await repo_metadata("https://github.com/octocat/Hello-World")
    assert meta.owner == "octocat"
    assert meta.latest_commit_sha.startswith("abc1234")
    assert meta.is_public is True


@respx.mock
async def test_repo_metadata_404_raises_repo_not_found() -> None:
    respx.get("https://api.github.com/repos/missing/repo").mock(return_value=Response(404, json={}))
    with pytest.raises(RepoNotFoundError):
        await repo_metadata("https://github.com/missing/repo")


@respx.mock
async def test_repo_metadata_too_large() -> None:
    respx.get("https://api.github.com/repos/big/repo").mock(
        return_value=Response(
            200,
            json={
                "owner": {"login": "big"},
                "name": "repo",
                "default_branch": "main",
                "language": "Go",
                "size": 600 * 1024,  # 600 MB
                "private": False,
                "html_url": "https://github.com/big/repo",
            },
        )
    )
    with pytest.raises(RepoTooLargeError):
        await repo_metadata("https://github.com/big/repo")


# ─────────── list_files / get_file_content ───────────


async def test_list_files_walks_directory(tmp_path: Path) -> None:
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "main.py").write_text("print('hi')\n")
    (tmp_path / "README.md").write_text("# hello\n")
    (tmp_path / "node_modules").mkdir()
    (tmp_path / "node_modules" / "bundle.js").write_text("noop")
    (tmp_path / "binary.png").write_bytes(b"\x00\x01\x02")

    entries = await list_files(tmp_path)
    paths = {e.relative_path for e in entries}
    assert "src/main.py" in paths
    assert "README.md" in paths
    assert "node_modules/bundle.js" not in paths
    assert "binary.png" not in paths


async def test_get_file_content_reads_text(tmp_path: Path) -> None:
    (tmp_path / "x.py").write_text("answer = 42\n")
    content = await get_file_content(tmp_path, "x.py")
    assert "answer = 42" in content


async def test_get_file_content_rejects_traversal(tmp_path: Path) -> None:
    (tmp_path / "x.py").write_text("ok")
    with pytest.raises(FetchError):
        await get_file_content(tmp_path, "../../etc/passwd")


async def test_get_file_content_rejects_too_large(tmp_path: Path) -> None:
    huge = tmp_path / "huge.txt"
    huge.write_bytes(b"x" * (1024 * 1024 + 1))
    with pytest.raises(FileTooLargeError):
        await get_file_content(tmp_path, "huge.txt")


# ─────────── get_commits ───────────


@respx.mock
async def test_get_commits_happy_path() -> None:
    respx.get("https://api.github.com/repos/octocat/Hello-World/commits").mock(
        return_value=Response(
            200,
            json=[
                {
                    "sha": "abc1234def5678",
                    "author": {"login": "octocat"},
                    "commit": {
                        "author": {
                            "name": "Mona",
                            "email": "mona@example.com",
                            "date": "2026-05-10T12:00:00Z",
                        },
                        "message": "Initial",
                    },
                }
            ],
        )
    )
    commits = await get_commits("octocat", "Hello-World", limit=1)
    assert len(commits) == 1
    assert commits[0].author_name == "Mona"
    assert commits[0].sha.startswith("abc1234")


def test_default_extensions_include_python_and_md() -> None:
    assert ".py" in DEFAULT_EXTENSIONS
    assert ".md" in DEFAULT_EXTENSIONS
