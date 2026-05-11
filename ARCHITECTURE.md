# Architecture — github-analyzer

> Status: draft for M0.2 — pending `/analyze-prompt` audit and Diego confirmation.
> When approved, decisions D-003 through D-008 in `../DECISIONS.md` flip from `🔄 in review` to `✅ active`.

---

## 1. Goals and non-goals

### Goals

- Given a public GitHub repo URL, return a structured technical report in Markdown answering: what it does, how it is built, what problems it has.
- Expose a RAG channel for follow-up natural-language questions about the analyzed repo.
- Be reproducible: the same repo at the same commit must produce the same report (idempotency by commit SHA).
- Be cheap to run: a single analysis should cost < USD 0.50 in LLM + embeddings for a medium repo (~500 files, ~50k LOC).

### Non-goals (v1)

- Private repos. v2 adds GitHub OAuth.
- Monorepo-aware decomposition (each subproject as a separate report). v1 treats the whole tree uniformly.
- Multi-tenancy / user accounts. v1 is a public stateless demo.
- Real-time updates / webhooks. Re-analysis is on-demand only.

---

## 2. Overview

```
                ┌──────────────────────────────────────────────────────────────┐
                │                      CLI / FastAPI                            │
                │  github-analyzer analyze <url>                                │
                │  POST /api/analyze  { url }                                   │
                └────────────────────────────┬─────────────────────────────────┘
                                             │
                              ┌──────────────▼──────────────┐
                              │      Orchestrator           │
                              │   (LangGraph state graph)   │
                              └──────────────┬──────────────┘
                                             │
            ┌────────────────────────────────┴────────────────────────────────┐
            │                                                                  │
   ┌────────▼───────┐                                                 ┌───────▼────────┐
   │  Fetch node    │                                                 │  Cache check    │
   │  - clone repo  │   ┌──────────────────────────────────────┐      │  by commit SHA  │
   │  - get SHA     │◄──┤  MCP server (github-tools)           │      └───────┬────────┘
   │  - size check  │   │  - clone (shallow, blobless)         │              │
   └────────┬───────┘   │  - list files                        │       cache hit ↘
            │            │  - rate-limit aware                  │              cached
            │            └──────────────────────────────────────┘              report
            ▼                                                                    │
   ┌────────────────┐                                                            │
   │  Index node    │                                                            │
   │  - chunk code  │     ──────────►   Qdrant collection                        │
   │  - embed       │                   { owner }_{ repo }_{ sha }               │
   └────────┬───────┘                                                            │
            │                                                                    │
            ▼                                                                    │
   ┌─────────────────────────────────────────────────────────────────┐           │
   │              4 specialized agents (parallel)                     │           │
   │                                                                  │           │
   │  ┌──────────────┐ ┌──────────────┐ ┌──────────────┐ ┌─────────┐ │           │
   │  │ Stack agent  │ │ Architecture │ │ Tech-debt    │ │ Docs    │ │           │
   │  │ langs/fw/dep │ │ patterns,    │ │ smells,      │ │ quality │ │           │
   │  │              │ │ layering     │ │ test cov     │ │ analysis│ │           │
   │  └──────┬───────┘ └──────┬───────┘ └──────┬───────┘ └────┬────┘ │           │
   └─────────┼────────────────┼────────────────┼──────────────┼──────┘           │
             │                │                │              │                  │
             └────────────────┴────────────────┴──────────────┘                  │
                                       │                                          │
                                       ▼                                          │
                              ┌────────────────┐                                  │
                              │  Synthesizer   │◄─────────────────────────────────┘
                              │  - scoring     │
                              │  - Markdown    │
                              └────────┬───────┘
                                       │
                                       ▼
                              ┌────────────────┐
                              │  Report cache  │
                              │  by commit SHA │
                              └────────────────┘
```

---

## 3. Components

### 3.1 Orchestrator (LangGraph)

Owns the state graph and node sequencing. Stateless from one analysis to another (each invocation gets a fresh graph instance).

Responsibilities:
- Build the graph from the node definitions in `src/pipeline/`.
- Validate the initial input (`url`, optional `commit_sha`, optional `force_refresh`).
- Route control flow: cache check → fetch → index → 4 agents in parallel → synthesizer.
- Collect agent outputs, even partial ones if any agent fails (error handling, §8).
- Emit structured logs with `correlation_id` (§9).

### 3.2 MCP server — `github-tools`

A custom MCP server that wraps GitHub access. Lives in `src/mcp_servers/github_tools/`. Used by the Fetch node and (optionally) by specialized agents that need raw API access.

Tools exposed:

| Tool | Input | Output | Notes |
|------|-------|--------|-------|
| `repo_metadata` | `url` | `RepoMetadata` (owner, name, default_branch, language, size_kb, latest_commit_sha) | Single REST call to `GET /repos/{owner}/{repo}`. |
| `clone_shallow` | `url`, `commit_sha?` | `local_path` (str), `commit_sha` (str) | `git clone --depth=1 --filter=blob:none`. Returns path to the local clone in a temp dir. |
| `list_files` | `local_path`, `whitelist_extensions` | `list[FileEntry]` (path, size, language_hint) | Walks the clone, filters by extension whitelist. |
| `get_file_content` | `local_path`, `relative_path` | `str` | Reads the file. Fails if size > 1 MB (configurable). |
| `get_commits` | `owner`, `repo`, `limit?` | `list[Commit]` | API call to `/commits`. Rate-limit aware (exponential backoff on 403/429). |

Rate limit handling: the MCP server tracks remaining quota from response headers (`X-RateLimit-Remaining`). When < 100, switches to local clone exclusively and avoids further API calls.

### 3.3 Fetch node

Calls `repo_metadata` then `clone_shallow`. Validates:
- Repo is public (returns 404 → fail with clear message).
- Size <= 500 MB after exclusions. If oversized, fail fast.
- Latest commit SHA — used as the cache key for the rest of the pipeline.

Output: `FetchResult { local_path, commit_sha, owner, repo, default_branch, language_hint, size_kb }`.

### 3.4 Cache check node

Sits between Fetch and Index. Queries the report cache by `{owner}/{repo}@{commit_sha}`. If a cached report exists and `force_refresh` is false:
- Skip Index + all agents + Synthesizer.
- Return the cached report directly.

Cache storage: SQLite table `report_cache` (path: `~/.local/state/github-analyzer/cache.db` in CLI mode, `/data/cache.db` in Docker).

| column | type | notes |
|--------|------|-------|
| `id` | uuid pk |
| `owner` | text |
| `repo` | text |
| `commit_sha` | text |
| `report_md` | text |
| `report_json` | text (JSON) | stored as text in SQLite; `jsonb` if migrated to Postgres |
| `created_at` | timestamp |
| UNIQUE | `(owner, repo, commit_sha)` |

### 3.5 Index node

Chunks the codebase and embeds it into Qdrant.

Chunking strategy (D-005, see DECISIONS.md):
- **Structural via tree-sitter** for these languages: Python, JavaScript, TypeScript, Go, Rust, Java, C, C++. One chunk per top-level function or class, with the enclosing imports/types as preamble.
- **Token-based fallback** (700 tokens, 50 overlap) for everything else: Markdown, YAML, JSON, shell scripts, less common languages.
- **Max chunk size**: 2000 tokens. If a function exceeds it, fall back to token-based splitting within that function.

Embedding model: **OpenAI `text-embedding-3-small`** (D-004). 1536 dimensions. Batch size: 100 chunks per call.

Qdrant collection naming: `{owner}_{repo}_{commit_sha_8}` where `commit_sha_8` is the first 8 chars of the commit hash (D-006). Collection has:
- Vectors: 1536-dim, cosine distance.
- Payload: `{ path, language, chunk_kind (function|class|md|other), token_count, line_start, line_end, content }`.

If the collection already exists for this commit SHA, skip indexing (idempotency).

### 3.6 Specialized agents (parallel)

Four independent agents, each receives the same input (`AnalysisContext` with Qdrant collection name + repo metadata) and produces a structured output.

| Agent | Output schema | Approach |
|-------|---------------|----------|
| **Stack** | `StackReport { languages: list[Language], frameworks: list[Framework], dependencies: list[Dependency], package_managers: list[str] }` | Parse manifests (`package.json`, `pyproject.toml`, `go.mod`, `Cargo.toml`, etc.) deterministically. Use LLM only to interpret framework signals from imports + structure. |
| **Architecture** | `ArchitectureReport { entrypoints, layers, patterns, modules, dependencies_internal }` | Query Qdrant for entrypoint files (`main.*`, `__init__.py`, `index.*`). Walk the import graph. LLM summarizes patterns. |
| **Technical debt** | `TechDebtReport { score, smells: list[Smell], test_coverage_est, hotspots, todo_fixme_count }` | Query Qdrant for known smell patterns. Count tests vs source. Detect TODO/FIXME density. LLM rates severity. |
| **Documentation** | `DocsReport { readme_quality, inline_docs_ratio, api_docs_present, examples_count }` | Read `README.md`, count docstrings, look for `examples/` dir. LLM scores README quality on rubric. |

Each agent runs in its own LangGraph node and writes to its own channel in the state. Agents do not communicate with each other.

### 3.7 Synthesizer

Reads all four agent reports plus the repo metadata. Produces:
- A Markdown report with sections per dimension and an executive summary.
- A numeric score per dimension (0-100) and an overall score.
- A concrete list of recommendations (top 3 priorities).

Synthesizer is a single LLM call with a structured prompt. Output is validated against the `FinalReport` schema before persisting.

### 3.8 RAG Q&A endpoint

Independent from the analysis pipeline. Lives at `POST /api/ask`:

```
{ "repo_url": "https://github.com/owner/repo", "commit_sha"?: "abc1234", "question": "..." }
```

Workflow:
1. Resolve to a Qdrant collection (latest commit SHA if not specified).
2. If collection does not exist, return `409 Conflict: please analyze first`.
3. Embed the question, retrieve top 8 chunks.
4. Re-rank with a small LLM call (Claude Haiku) to filter relevance.
5. Final answer via Claude Sonnet with the top 4 chunks as context.
6. Return `{ answer, citations: list[{ path, lines, snippet }] }`.

---

## 4. Data flow (end-to-end)

```
1. User: github-analyzer analyze https://github.com/owner/repo

2. CLI/FastAPI → Orchestrator (initial state: { url, force_refresh: false })

3. Fetch node:
   - MCP github-tools.repo_metadata(url) → { commit_sha: "a1b2c3d4..." }
   - MCP github-tools.clone_shallow(url, sha) → { local_path: "/tmp/.../repo" }
   - Validate size <= 500 MB
   - State: { ...prev, fetch_result: FetchResult }

4. Cache check:
   - SELECT * FROM report_cache WHERE owner=? AND repo=? AND commit_sha=?
   - HIT → return cached report → goto Step 10
   - MISS → continue

5. Index node:
   - List files via MCP, filter by whitelist
   - Chunk each file (structural or token fallback)
   - Embed chunks in batches of 100
   - Upsert into Qdrant collection {owner}_{repo}_{sha_8}
   - State: { ...prev, index_result: IndexResult { chunk_count, collection_name } }

6. 4 agents in parallel (LangGraph parallel branch):
   - Each agent reads from Qdrant + fetch_result
   - Each emits its report into its own state channel
   - Errors per agent are caught and stored as { agent: "stack", error: "..." } in state.errors

7. Wait for all 4 → join

8. Synthesizer:
   - Read 4 agent reports + state.errors
   - Build final report Markdown + scores
   - Validate against FinalReport schema

9. Persist:
   - INSERT INTO report_cache (owner, repo, commit_sha, report_md, report_json)

10. Return report to user (Markdown for CLI, JSON+rendered HTML for web)
```

---

## 5. State management

LangGraph state is a single Pydantic model with channels per stage. Reducer semantics:
- Most channels: replace (only one writer).
- `errors`: append (each agent may add its own error).

```python
class PipelineState(BaseModel):
    # Input (set by entrypoint)
    correlation_id: str
    url: str
    force_refresh: bool = False
    requested_commit_sha: str | None = None

    # Set by Fetch node
    fetch_result: FetchResult | None = None

    # Set by Cache check
    cache_hit: bool = False
    cached_report: FinalReport | None = None

    # Set by Index node
    index_result: IndexResult | None = None

    # Set by agents (one each)
    stack_report: StackReport | None = None
    architecture_report: ArchitectureReport | None = None
    techdebt_report: TechDebtReport | None = None
    docs_report: DocsReport | None = None

    # Append-only error channel
    errors: list[AgentError] = Field(default_factory=list)

    # Set by Synthesizer
    final_report: FinalReport | None = None
```

---

## 6. Schemas (Pydantic v2)

All schemas live in `src/schemas/`. The most important ones for inter-node contracts:

```python
class FetchResult(BaseModel):
    owner: str
    repo: str
    commit_sha: str
    default_branch: str
    local_path: Path
    language_hint: str | None
    size_kb: int

class IndexResult(BaseModel):
    collection_name: str           # qdrant collection
    chunk_count: int
    file_count: int
    skipped_files: list[str]       # too large, unsupported encoding, etc.

class StackReport(BaseModel):
    languages: list[Language]      # ordered by LOC
    frameworks: list[Framework]    # with confidence
    dependencies: list[Dependency] # parsed from manifests
    package_managers: list[str]
    confidence: float              # 0..1

class ArchitectureReport(BaseModel):
    entrypoints: list[str]
    layers: list[Layer]            # e.g. presentation/business/data
    patterns: list[str]            # detected patterns with evidence
    module_count: int
    cyclic_deps_detected: bool
    summary_md: str                # 3-5 paragraph prose

class TechDebtReport(BaseModel):
    score: int                     # 0..100, higher = healthier
    smells: list[Smell]            # top 10 max
    test_to_source_ratio: float
    todo_fixme_count: int
    hotspots: list[Hotspot]        # files with high smell density
    summary_md: str

class DocsReport(BaseModel):
    readme_score: int              # 0..100
    inline_docs_ratio: float
    api_docs_present: bool
    examples_count: int
    summary_md: str

class AgentError(BaseModel):
    agent: Literal["stack", "architecture", "techdebt", "docs"]
    error_type: str
    message: str
    traceback: str | None

class FinalReport(BaseModel):
    owner: str
    repo: str
    commit_sha: str
    generated_at: datetime

    # Per-dimension scores
    stack_score: int
    architecture_score: int
    techdebt_score: int
    docs_score: int
    overall_score: int             # weighted avg

    # Top 3 recommendations
    recommendations: list[Recommendation]

    # Full Markdown report (cached)
    report_md: str

    # Raw agent outputs for debugging
    raw: dict[str, Any]

    # Partial-failure tracking
    failed_agents: list[str] = []
```

---

## 7. Storage

| Store | Purpose | Location |
|-------|---------|----------|
| Local filesystem | Shallow clones (temp, deleted after analysis) | `/tmp/github-analyzer/<correlation_id>/` |
| Qdrant | Vector store for code chunks (per-commit) | localhost:6333 in dev (docker compose), managed Qdrant Cloud in prod |
| SQLite | Report cache by commit SHA | `~/.local/state/github-analyzer/cache.db` in CLI; `/data/cache.db` in Docker |
| Postgres | Optional — only if we add user accounts / historical reports / analytics (v2) | not used in v1 |
| Object storage (S3) | Optional — only if we want to host the rendered HTML reports as static assets (v2) | not used in v1 |

Qdrant collection retention: collections older than 30 days with no recent queries are eligible for cleanup. A periodic job (`scripts/cleanup_qdrant.py`) handles it. Not blocking for v1.

---

## 8. Error handling

| Failure | Behavior |
|---------|----------|
| Repo not found (404) or private | Return `404 RepoNotFound` with explanation. Do not retry. |
| Repo too large (>500 MB) | Return `413 RepoTooLarge`. Do not partial-analyze. |
| GitHub API rate limit hit | Exponential backoff (1s, 2s, 4s, 8s, max 4 retries). If still failing, switch to local clone exclusively. |
| Clone failure (network, disk) | Retry once. On second failure, return `500 FetchFailed`. |
| Qdrant down | Fatal for analysis (but not for cache hits). Return `503 IndexUnavailable`. Cached reports for the requested SHA still serve. |
| One agent fails | Log to `state.errors`, continue. Synthesizer sees partial reports and notes which agents failed in `FinalReport.failed_agents`. Score for failed dimension defaults to `null` (excluded from overall avg). |
| Two or more agents fail | Same as above. If all 4 fail, return `500 AnalysisFailed`. |
| Synthesizer fails | Retry once with a temperature increase. Second failure → `500 SynthesisFailed`, but state.errors and raw agent reports are returned for debugging. |
| LLM provider 5xx | Retry with backoff up to 3 times. Then propagate as `503 LLMUnavailable`. |

Errors do not get cached — only successful `FinalReport`s.

---

## 9. Observability

Structured logging via `structlog` in JSON line format. Every log line carries:

- `timestamp` (ISO 8601 UTC)
- `level` (INFO / WARNING / ERROR)
- `correlation_id` (UUID per analysis request, propagated through all nodes)
- `node` (which pipeline node emitted the log)
- `event` (machine-readable event name)
- `latency_ms` (when applicable)

Key events to log:
- `analysis.started`, `analysis.completed`, `analysis.cache_hit`, `analysis.failed`
- `fetch.started`, `fetch.completed` with size, language
- `index.started`, `index.completed` with chunk count
- `agent.started`, `agent.completed`, `agent.failed` for each of the 4 agents
- `synthesis.started`, `synthesis.completed`
- `llm.call` with model, input tokens, output tokens, latency, cost estimate
- `qdrant.upsert`, `qdrant.search` with batch size and latency

In dev: pretty-print via `structlog.dev.ConsoleRenderer`.
In prod: JSON lines stdout, scraped by the deployment platform (Railway logs).

Metrics (v2, not v1): Prometheus counters for analyses/hour, cost/analysis, cache hit rate.

---

## 10. External integrations

### 10.1 GitHub API

- Authentication: `GITHUB_TOKEN` env var (Personal Access Token with `public_repo` scope).
- Endpoints used: `/repos/{owner}/{repo}`, `/repos/{owner}/{repo}/commits`, `/repos/{owner}/{repo}/contents/*` (only as fallback when local clone fails).
- Rate limit: 5000/hour with token. Tracked via response headers.
- Prefer `git clone --depth=1 --filter=blob:none` over REST file listing for bulk reads.

### 10.2 LLM provider — Anthropic API

- Authentication: `ANTHROPIC_API_KEY` env var.
- Models:
  - `claude-sonnet-4-6` for synthesis and per-agent analysis where reasoning quality matters.
  - `claude-haiku-4-5-20251001` for re-ranking RAG results and lightweight classifications.
- Streaming: not used in v1 (we want full response for schema validation).
- Cost budget: hard cap of USD 0.50 per analysis. If exceeded, abort with `429 BudgetExceeded`.

### 10.3 Embedding provider — OpenAI API

- Authentication: `OPENAI_API_KEY` env var.
- Model: `text-embedding-3-small` (1536 dim).
- Used only for embeddings. No completion calls.
- Cost: ~USD 0.02 per 1M input tokens. A 50k-LOC repo with ~5k chunks ~ 2M tokens = ~USD 0.04.

### 10.4 Qdrant

- Local dev: docker compose service exposing port 6333.
- Production: Qdrant Cloud (free tier covers v1 traffic).
- Auth: API key in prod via `QDRANT_API_KEY` env var.
- Idempotent upsert: collection creation is wrapped in `try/except CollectionExistsError`.

---

## 11. Module layout

```
code/
├── ARCHITECTURE.md                   ← this file
├── DECISIONS.md                      ← link from architecture decisions
├── README.md
├── LICENSE
├── pyproject.toml
├── .env.example
├── docker-compose.yml                ← qdrant + (later) fastapi
├── Dockerfile
├── src/
│   └── github_analyzer/
│       ├── __init__.py
│       ├── cli.py                    ← Typer CLI entrypoint
│       ├── api.py                    ← FastAPI app (M7)
│       ├── config.py                 ← Pydantic Settings (env vars)
│       ├── schemas/
│       │   ├── __init__.py
│       │   ├── state.py              ← PipelineState
│       │   ├── fetch.py              ← FetchResult, IndexResult
│       │   ├── reports.py            ← StackReport, ArchitectureReport, etc.
│       │   └── final.py              ← FinalReport, Recommendation
│       ├── pipeline/
│       │   ├── __init__.py
│       │   ├── graph.py              ← LangGraph wiring
│       │   ├── nodes/
│       │   │   ├── fetch.py
│       │   │   ├── cache_check.py
│       │   │   ├── index.py
│       │   │   ├── synthesizer.py
│       │   │   └── agents/
│       │   │       ├── stack.py
│       │   │       ├── architecture.py
│       │   │       ├── techdebt.py
│       │   │       └── docs.py
│       ├── mcp_servers/
│       │   └── github_tools/
│       │       ├── server.py
│       │       └── SPEC.md           ← per-tool I/O contract
│       ├── indexing/
│       │   ├── chunking.py           ← structural + token fallback
│       │   ├── embeddings.py         ← OpenAI client
│       │   └── qdrant_client.py
│       ├── storage/
│       │   ├── cache.py              ← SQLite report cache
│       │   └── models.py             ← SQLAlchemy models (or raw sqlite)
│       ├── llm/
│       │   ├── client.py             ← Anthropic wrapper with budget tracking
│       │   └── prompts/              ← per-agent system prompts
│       └── observability/
│           └── logging.py            ← structlog setup
└── tests/
    ├── unit/
    │   ├── test_chunking.py
    │   ├── test_schemas.py
    │   └── test_agents/
    └── integration/
        ├── test_pipeline_e2e.py      ← real qdrant + real LLM (--integration)
        └── test_mcp_github_tools.py
```

---

## 12. Decisions referenced

The architecture decisions on this document are recorded in `../DECISIONS.md`:

- **D-003** — Pipeline orchestration via LangGraph state graph (single-process, no Celery / Redis).
- **D-004** — Embedding model: OpenAI `text-embedding-3-small` (1536 dim).
- **D-005** — Chunking strategy: structural via tree-sitter for top 8 languages, token-fallback for the rest.
- **D-006** — Qdrant collection naming: `{owner}_{repo}_{commit_sha_8}`, one collection per repo+commit.
- **D-007** — Report cache: SQLite local, keyed by `(owner, repo, commit_sha)`.
- **D-008** — Partial-failure tolerance: 1-3 agents may fail without aborting the analysis; only all-4 fails as fatal.

All decisions start `🔄 in review` and become `✅ active` once Diego approves this document.

---

## 13. Open questions for v2

These are intentionally deferred — not blockers for v1, recorded so they are not forgotten:

- How to handle monorepos: detect at fetch time, offer to scope to a subpath.
- How to surface comparative reports (this repo vs N similar repos).
- Whether to add a `score over time` chart (requires tracking analyses over multiple commits of the same repo).
- GitHub OAuth for private repos.
- Multi-tenancy + user accounts.

---

## 14. Next milestones referencing this doc

| Milestone | Needs this doc | Note |
|-----------|----------------|------|
| M0.3 | Yes | Scaffold `src/` matches §11 module layout. |
| M1   | Yes | Implement MCP `github-tools` against §3.2 spec. |
| M2   | Yes | Indexing pipeline against §3.5 + chunking strategy in §5. |
| M3   | Yes | Single-agent baseline implements §3.6 contract for one agent. |
| M4   | Yes | Parallel agents wire into LangGraph per §5 state model. |
| M5   | Yes | Synthesizer produces `FinalReport` per §6 schema. |
| M6   | Yes | RAG endpoint per §3.8. |
| M7   | Partial | FastAPI wraps existing CLI per §11. |
| M8   | Partial | Docker compose extends §7. |
