"""Async tools that wrap GitHub access.

Each public function is testable in isolation (unit tests use `respx` for
the API calls and `monkeypatch` for subprocess + filesystem). The same
functions are exposed via MCP transport in M3.

Conventions:
- All functions are `async def`.
- All errors are domain-specific exceptions (FetchError subclasses), not
  raw httpx / OSError leaks.
- All file paths inside the repo are POSIX-style strings (relative).
- All filesystem paths returned (e.g. `local_path`) are `pathlib.Path`.
"""

from __future__ import annotations

import asyncio
import os
import re
import tempfile
import uuid
from datetime import datetime
from pathlib import Path
from typing import Final

from github_analyzer.mcp_servers.github_tools.client import get_json
from github_analyzer.observability.logging import get_logger
from github_analyzer.schemas.github import (
    CloneResult,
    Commit,
    FileEntry,
    RepoMetadata,
)

logger = get_logger(__name__)

# Hard cap from CLAUDE.md product rules.
_MAX_REPO_SIZE_KB: Final[int] = 500 * 1024  # 500 MB
_MAX_FILE_SIZE_BYTES: Final[int] = 1 * 1024 * 1024  # 1 MB

# Default file-extension whitelist (D-005-ish — code + docs + configs).
DEFAULT_EXTENSIONS: Final[frozenset[str]] = frozenset(
    {
        # Python
        ".py",
        ".pyi",
        # JS / TS
        ".js",
        ".jsx",
        ".ts",
        ".tsx",
        ".mjs",
        ".cjs",
        # Go / Rust
        ".go",
        ".rs",
        # JVM
        ".java",
        ".kt",
        ".scala",
        # C family
        ".c",
        ".h",
        ".cpp",
        ".hpp",
        ".cc",
        ".hh",
        ".cxx",
        # Web
        ".html",
        ".css",
        ".scss",
        ".vue",
        ".svelte",
        # Other languages
        ".rb",
        ".php",
        ".swift",
        ".cs",
        ".sh",
        ".bash",
        ".zsh",
        # Docs
        ".md",
        ".rst",
        ".txt",
        # Config
        ".toml",
        ".yaml",
        ".yml",
        ".json",
        ".ini",
        ".cfg",
        # Data
        ".sql",
    }
)

# Map common extensions to language names. Heuristic only.
_LANGUAGE_BY_EXT: Final[dict[str, str]] = {
    ".py": "Python",
    ".pyi": "Python",
    ".js": "JavaScript",
    ".jsx": "JavaScript",
    ".mjs": "JavaScript",
    ".cjs": "JavaScript",
    ".ts": "TypeScript",
    ".tsx": "TypeScript",
    ".go": "Go",
    ".rs": "Rust",
    ".java": "Java",
    ".kt": "Kotlin",
    ".scala": "Scala",
    ".c": "C",
    ".h": "C",
    ".cpp": "C++",
    ".hpp": "C++",
    ".cc": "C++",
    ".hh": "C++",
    ".cxx": "C++",
    ".rb": "Ruby",
    ".php": "PHP",
    ".swift": "Swift",
    ".cs": "C#",
    ".sh": "Shell",
    ".bash": "Shell",
    ".zsh": "Shell",
    ".md": "Markdown",
    ".rst": "reStructuredText",
    ".txt": "Text",
    ".toml": "TOML",
    ".yaml": "YAML",
    ".yml": "YAML",
    ".json": "JSON",
    ".ini": "INI",
    ".cfg": "INI",
    ".sql": "SQL",
    ".html": "HTML",
    ".css": "CSS",
    ".scss": "SCSS",
    ".vue": "Vue",
    ".svelte": "Svelte",
}

# Files / dirs we always skip even if they match the extension whitelist.
_SKIP_DIRS: Final[frozenset[str]] = frozenset(
    {
        ".git",
        "node_modules",
        ".next",
        "dist",
        "build",
        "out",
        ".venv",
        "venv",
        "__pycache__",
        ".mypy_cache",
        ".ruff_cache",
        ".pytest_cache",
        "target",
        ".gradle",
        ".idea",
        ".vscode",
    }
)

_GITHUB_URL_RE = re.compile(
    r"^https?://github\.com/(?P<owner>[A-Za-z0-9._-]+)/(?P<repo>[A-Za-z0-9._-]+?)(?:\.git)?/?$"
)


# ──────────────────────────────────────────────────────────────────────
# Errors
# ──────────────────────────────────────────────────────────────────────


class FetchError(RuntimeError):
    """Base error for the fetcher layer."""


class InvalidRepoUrlError(FetchError):
    """URL does not parse as a GitHub repo URL."""


class RepoNotFoundError(FetchError):
    """Repo is missing or private (we cannot tell which without auth)."""


class RepoTooLargeError(FetchError):
    """Repo exceeds the 500 MB hard cap."""


class FileTooLargeError(FetchError):
    """File exceeds the 1 MB read cap."""


class CloneFailedError(FetchError):
    """`git clone` returned a non-zero exit code."""


# ──────────────────────────────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────────────────────────────


def _parse_url(url: str) -> tuple[str, str]:
    """Extract `(owner, repo)` from a GitHub URL. Raises `InvalidRepoUrlError`."""
    match = _GITHUB_URL_RE.match(url.strip())
    if not match:
        raise InvalidRepoUrlError(f"Not a valid GitHub repo URL: {url!r}")
    return match.group("owner"), match.group("repo")


def _classify_language(filename: str) -> str | None:
    """Guess the language from the file extension. None if unknown."""
    suffix = Path(filename).suffix.lower()
    return _LANGUAGE_BY_EXT.get(suffix)


# ──────────────────────────────────────────────────────────────────────
# Tools
# ──────────────────────────────────────────────────────────────────────


async def repo_metadata(url: str) -> RepoMetadata:
    """Fetch metadata for the repo at `url`.

    Raises:
        InvalidRepoUrlError: URL is malformed.
        RepoNotFoundError: GitHub returns 404 (repo missing or private).
        RepoTooLargeError: repo size > 500 MB.
    """
    owner, repo = _parse_url(url)
    logger.info("github.repo_metadata.start", owner=owner, repo=repo)

    import httpx  # local import — keeps the public API import-free of httpx symbols

    try:
        payload = await get_json(f"/repos/{owner}/{repo}")
    except httpx.HTTPStatusError as e:
        if e.response.status_code == 404:
            raise RepoNotFoundError(f"Repo not found or private: {owner}/{repo}") from e
        raise

    if not isinstance(payload, dict):
        raise FetchError(f"Unexpected payload type from GitHub: {type(payload).__name__}")

    size_kb = int(payload["size"])
    if size_kb > _MAX_REPO_SIZE_KB:
        raise RepoTooLargeError(
            f"Repo {owner}/{repo} is {size_kb} KB; limit is {_MAX_REPO_SIZE_KB} KB"
        )

    default_branch = payload["default_branch"]
    # Resolve HEAD SHA of the default branch.
    branch_payload = await get_json(f"/repos/{owner}/{repo}/branches/{default_branch}")
    if not isinstance(branch_payload, dict):
        raise FetchError("Unexpected branch payload type from GitHub")
    latest_sha = branch_payload["commit"]["sha"]

    return RepoMetadata(
        owner=payload["owner"]["login"],
        name=payload["name"],
        default_branch=default_branch,
        language_hint=payload.get("language"),
        size_kb=size_kb,
        latest_commit_sha=latest_sha,
        is_public=not payload.get("private", False),
        html_url=payload["html_url"],
    )


async def clone_shallow(url: str, commit_sha: str | None = None) -> CloneResult:
    """Shallow-clone the repo into a fresh temp directory.

    Strategy: `git clone --depth=1 --filter=blob:none <url> <tmp>` + optional
    checkout of a specific commit.

    Returns the local path and the resolved commit SHA.
    """
    owner, repo = _parse_url(url)
    correlation_id = uuid.uuid4().hex[:12]
    base = Path(tempfile.gettempdir()) / "github-analyzer" / correlation_id
    base.mkdir(parents=True, exist_ok=True)
    target = base / repo

    logger.info("github.clone.start", owner=owner, repo=repo, target=str(target))

    cmd = [
        "git",
        "clone",
        "--depth=1",
        "--filter=blob:none",
        "--quiet",
        url,
        str(target),
    ]
    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    _stdout, stderr = await proc.communicate()

    if proc.returncode != 0:
        raise CloneFailedError(
            f"git clone failed for {url}: exit={proc.returncode} "
            f"stderr={stderr.decode('utf-8', errors='replace').strip()}"
        )

    # If a specific commit was requested, fetch it and check it out.
    if commit_sha is not None:
        fetch = await asyncio.create_subprocess_exec(
            "git",
            "-C",
            str(target),
            "fetch",
            "--depth=1",
            "origin",
            commit_sha,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        _, fetch_err = await fetch.communicate()
        if fetch.returncode != 0:
            msg = fetch_err.decode("utf-8", errors="replace").strip()
            raise CloneFailedError(f"git fetch {commit_sha} failed: {msg}")
        checkout = await asyncio.create_subprocess_exec(
            "git",
            "-C",
            str(target),
            "checkout",
            commit_sha,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        _, co_err = await checkout.communicate()
        if checkout.returncode != 0:
            msg = co_err.decode("utf-8", errors="replace").strip()
            raise CloneFailedError(f"git checkout {commit_sha} failed: {msg}")
        resolved_sha = commit_sha
    else:
        # Read HEAD's SHA.
        rev = await asyncio.create_subprocess_exec(
            "git",
            "-C",
            str(target),
            "rev-parse",
            "HEAD",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        rev_out, _ = await rev.communicate()
        if rev.returncode != 0:
            raise CloneFailedError("git rev-parse HEAD failed after clone")
        resolved_sha = rev_out.decode("ascii").strip()

    logger.info("github.clone.done", owner=owner, repo=repo, sha=resolved_sha)
    return CloneResult(local_path=target, commit_sha=resolved_sha)


def _walk_files(root: Path, extensions: frozenset[str]) -> list[FileEntry]:
    """Synchronous helper for `list_files`. Runs inside `asyncio.to_thread`."""
    results: list[FileEntry] = []
    for dirpath, dirnames, filenames in os.walk(root):
        # Mutate dirnames in-place so os.walk skips the excluded dirs.
        dirnames[:] = [d for d in dirnames if d not in _SKIP_DIRS]
        for fname in filenames:
            full = Path(dirpath) / fname
            if full.suffix.lower() not in extensions and fname not in {"Dockerfile", "Makefile"}:
                continue
            try:
                size = full.stat().st_size
            except OSError:
                continue
            rel = str(full.relative_to(root))
            results.append(
                FileEntry(
                    relative_path=rel,
                    size_bytes=size,
                    language_hint=_classify_language(fname),
                )
            )
    return results


async def list_files(local_path: Path, extensions: frozenset[str] | None = None) -> list[FileEntry]:
    """Walk `local_path` and return every file matching the extension whitelist.

    Skips `.git/`, `node_modules/`, build outputs, virtualenvs, IDE folders.
    """
    if not local_path.exists() or not local_path.is_dir():
        raise FetchError(f"local_path does not exist or is not a directory: {local_path}")
    selected = extensions if extensions is not None else DEFAULT_EXTENSIONS
    entries = await asyncio.to_thread(_walk_files, local_path, selected)
    logger.info("github.list_files.done", path=str(local_path), count=len(entries))
    return sorted(entries, key=lambda e: e.relative_path)


async def get_file_content(local_path: Path, relative_path: str) -> str:
    """Read a file inside the clone. Refuses files larger than 1 MB."""
    full = local_path / relative_path
    try:
        # Prevent path traversal.
        full.resolve().relative_to(local_path.resolve())
    except ValueError as e:
        raise FetchError(f"path escapes clone root: {relative_path!r}") from e

    if not full.is_file():
        raise FetchError(f"not a file: {relative_path!r}")

    size = full.stat().st_size
    if size > _MAX_FILE_SIZE_BYTES:
        raise FileTooLargeError(f"{relative_path} is {size} bytes; limit is {_MAX_FILE_SIZE_BYTES}")

    def _read() -> str:
        return full.read_text(encoding="utf-8", errors="replace")

    return await asyncio.to_thread(_read)


async def get_commits(owner: str, repo: str, limit: int = 10) -> list[Commit]:
    """Fetch the latest commits on the default branch via the GitHub REST API."""
    if limit < 1 or limit > 100:
        raise FetchError(f"limit must be in [1, 100]; got {limit}")
    payload = await get_json(f"/repos/{owner}/{repo}/commits", params={"per_page": limit})
    if not isinstance(payload, list):
        raise FetchError("Unexpected commits payload type from GitHub")

    commits: list[Commit] = []
    for item in payload:
        commit_data = item["commit"]
        author = item.get("author") or {}
        commits.append(
            Commit(
                sha=item["sha"],
                author_login=author.get("login"),
                author_name=commit_data["author"]["name"],
                author_email=commit_data["author"]["email"],
                message=commit_data["message"],
                committed_at=datetime.fromisoformat(
                    commit_data["author"]["date"].replace("Z", "+00:00")
                ),
            )
        )
    return commits
