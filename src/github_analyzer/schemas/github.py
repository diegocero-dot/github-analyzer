"""Schemas for the GitHub fetcher tools (`github-tools`).

Defines the I/O contracts referenced by `mcp_servers/github_tools/tools.py`
and consumed by the CLI `fetch` subcommand. All schemas are immutable
(frozen) so they can be passed across async boundaries safely.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, HttpUrl


class RepoMetadata(BaseModel):
    """Metadata returned by `repo_metadata(url)`.

    Sourced from `GET /repos/{owner}/{repo}` of the GitHub REST API.
    """

    model_config = ConfigDict(frozen=True)

    owner: str
    name: str
    default_branch: str
    language_hint: str | None = Field(
        default=None,
        description="GitHub's auto-detected primary language. Heuristic — do not over-trust.",
    )
    size_kb: int = Field(ge=0, description="Repo size as reported by GitHub (kilobytes).")
    latest_commit_sha: str = Field(min_length=7, description="Full SHA of the default branch HEAD.")
    is_public: bool
    html_url: HttpUrl


class CloneResult(BaseModel):
    """Result of `clone_shallow(url, commit_sha?)`."""

    model_config = ConfigDict(frozen=True)

    local_path: Path
    commit_sha: str = Field(min_length=7)


class FileEntry(BaseModel):
    """One file inside a cloned repo, surfaced by `list_files(...)`."""

    model_config = ConfigDict(frozen=True)

    relative_path: str
    size_bytes: int = Field(ge=0)
    language_hint: str | None = Field(
        default=None,
        description="Best-effort language guess from the file extension. May be None.",
    )


class Commit(BaseModel):
    """One commit returned by `get_commits(...)`."""

    model_config = ConfigDict(frozen=True)

    sha: str = Field(min_length=7)
    author_login: str | None = Field(
        default=None, description="GitHub username; None for unattributed."
    )
    author_name: str
    author_email: str
    message: str
    committed_at: datetime


class RateLimitInfo(BaseModel):
    """Snapshot of the GitHub API rate-limit window for the current token."""

    model_config = ConfigDict(frozen=True)

    limit: int = Field(ge=0)
    remaining: int = Field(ge=0)
    reset_at: datetime
    resource: Annotated[str, Field(description="GitHub resource bucket — usually 'core'.")]
