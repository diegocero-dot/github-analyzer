# github-tools — Tool I/O contract

> Per-tool schema for the `github-tools` MCP server. M1 ships the
> implementations; M3 wires the MCP transport.

## Errors (all tools)

All tools raise subclasses of `FetchError` defined in `tools.py`:

- `InvalidRepoUrlError` — URL is malformed.
- `RepoNotFoundError` — 404 from the GitHub API.
- `RepoTooLargeError` — repo > 500 MB.
- `FileTooLargeError` — file > 1 MB on `get_file_content`.
- `CloneFailedError` — `git clone`/`fetch`/`checkout` failed.
- `RateLimitExceededError` (in `rate_limit.py`) — backoff retries exhausted.

## Tools

### `repo_metadata(url) -> RepoMetadata`
- **Input:** `url` (HTTPS GitHub URL).
- **Output:** `RepoMetadata` (see `schemas/github.py`).
- **API calls:** `GET /repos/{owner}/{repo}`, `GET /repos/{owner}/{repo}/branches/{default_branch}`.
- **Side effects:** none.

### `clone_shallow(url, commit_sha=None) -> CloneResult`
- **Input:** `url` + optional explicit commit.
- **Output:** local Path + resolved SHA.
- **Side effects:** writes to `/tmp/github-analyzer/<correlation_id>/<repo>/`.
- **Subprocess:** `git clone --depth=1 --filter=blob:none`. If `commit_sha` is set, `git fetch --depth=1 origin <sha>` + `git checkout <sha>`.

### `list_files(local_path, extensions=None) -> list[FileEntry]`
- **Input:** `local_path` (Path returned by `clone_shallow`) + optional extension whitelist (defaults to `DEFAULT_EXTENSIONS`).
- **Output:** sorted list of `FileEntry`.
- **Side effects:** filesystem walk (no writes).
- **Skips:** `.git/`, `node_modules/`, build outputs, virtualenvs, IDE folders.

### `get_file_content(local_path, relative_path) -> str`
- **Input:** `local_path` + relative POSIX path inside the clone.
- **Output:** UTF-8 string (errors replaced).
- **Side effects:** filesystem read.
- **Limits:** refuses files > 1 MB. Refuses paths that traverse outside the clone.

### `get_commits(owner, repo, limit=10) -> list[Commit]`
- **Input:** owner + repo + optional `limit` in `[1, 100]`.
- **Output:** list of `Commit`.
- **API calls:** `GET /repos/{owner}/{repo}/commits?per_page={limit}`.

## Rate limiting

- Token auth via `GITHUB_TOKEN` env var.
- Backoff: 1s, 2s, 4s, 8s (4 retries). Then `RateLimitExceededError`.
- Trigger statuses: `403`, `429`.
- See `rate_limit.py::retry_with_backoff`.

## Configuration

| Constant | Default | Source |
|----------|---------|--------|
| `_MAX_REPO_SIZE_KB` | 512000 (500 MB) | CLAUDE.md product rules |
| `_MAX_FILE_SIZE_BYTES` | 1048576 (1 MB) | ARCHITECTURE.md §3.2 |
| `DEFAULT_EXTENSIONS` | ~35 code/docs/config extensions | M1 decision |
| Backoff schedule | (1s, 2s, 4s, 8s) | `rate_limit.py` |
