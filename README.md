# github-analyzer

CLI and web tool that analyzes any public GitHub repository and produces a technical report on its stack, architecture, technical debt, and documentation quality. Includes natural-language Q&A over the codebase via RAG.

> Status: early development. M0 — Setup + Architecture.

## What it does

Given the URL of a public GitHub repository, the tool:

1. Clones (or fetches via API) the repo and indexes its code into a vector database.
2. Runs a pipeline of specialized agents in parallel — stack detection, architecture analysis, technical-debt review, documentation quality — orchestrated by LangGraph.
3. Synthesizes the individual reports into a structured Markdown report with numeric scores per dimension.
4. Exposes a RAG channel so users can ask natural-language questions about the codebase after analysis.

## Stack

- **Python 3.12+** with strict type hints (`mypy --strict`).
- **LangGraph** — agent pipeline orchestration.
- **Qdrant** — vector DB for indexing and RAG.
- **MCP server** (custom) — GitHub API access with rate-limit awareness.
- **FastAPI** — web backend.
- **Anthropic API (Claude)** — primary LLM provider.
- **Docker** + **Railway** (or Fly.io) — deployment.

Full architecture in [`ARCHITECTURE.md`](./ARCHITECTURE.md).

## Status

Project is in M0 — Setup + Architecture (M0.1 + M0.2 + M0.3 done). See [`PROJECT.md`](../PROJECT.md) (workspace-level) for the live roadmap and milestones.

## Quickstart (dev)

Requires `uv` (https://docs.astral.sh/uv/) and Python 3.12+.

```bash
cd code
uv sync                    # create virtualenv + install deps
uv run github-analyzer --help    # smoke test the CLI stub
uv run pytest tests/unit/        # run the unit test suite
```

Set up secrets by copying `.env.example` to `.env` and filling the keys for the
milestone you are working on (see comments inside `.env.example`).

## License

MIT — see [`LICENSE`](./LICENSE).
