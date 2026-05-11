"""github-tools — async tools that wrap GitHub access.

Public API (M1):
- `repo_metadata(url) -> RepoMetadata`
- `clone_shallow(url, commit_sha?) -> CloneResult`
- `list_files(local_path, extensions?) -> list[FileEntry]`
- `get_file_content(local_path, relative_path) -> str`
- `get_commits(owner, repo, limit?) -> list[Commit]`

These functions are also exposed as MCP tools (M3+).
"""

from github_analyzer.mcp_servers.github_tools.tools import (
    clone_shallow,
    get_commits,
    get_file_content,
    list_files,
    repo_metadata,
)

__all__ = [
    "clone_shallow",
    "get_commits",
    "get_file_content",
    "list_files",
    "repo_metadata",
]
