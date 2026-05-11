"""Pydantic schemas — inter-module contracts.

Each submodule groups schemas by domain:
- `github`: tool I/O for the GitHub fetcher (M1).
- `reports`: per-agent report schemas (M3+).
- `state`: LangGraph pipeline state (M4+).
- `final`: synthesized report payload (M5+).
"""
