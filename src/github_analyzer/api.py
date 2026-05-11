"""FastAPI application for github-analyzer.

M0.4 ships a minimal stub:
- `GET /`        — service identity (name, version, status).
- `GET /health`  — liveness probe; returns 200 as long as the process is up.

Real analysis endpoints (`POST /api/analyze`, `POST /api/ask`) land in M7.
A readiness probe that checks Qdrant connectivity also lands in M7.
"""

from __future__ import annotations

from fastapi import FastAPI
from pydantic import BaseModel

from github_analyzer import __version__

app = FastAPI(
    title="github-analyzer",
    version=__version__,
    description=(
        "Analyze any public GitHub repository — stack, architecture, "
        "technical debt, and documentation quality."
    ),
)


class ServiceIdentity(BaseModel):
    """Response payload for the root endpoint."""

    service: str
    version: str
    status: str


class HealthStatus(BaseModel):
    """Response payload for the liveness probe."""

    status: str


@app.get("/", response_model=ServiceIdentity, tags=["meta"])
def root() -> ServiceIdentity:
    """Return the service identity. Used by load balancers and monitoring dashboards."""
    return ServiceIdentity(
        service="github-analyzer",
        version=__version__,
        status="ok",
    )


@app.get("/health", response_model=HealthStatus, tags=["meta"])
def health() -> HealthStatus:
    """Liveness probe.

    Returns 200 as long as the Python process can respond. Does NOT verify
    downstream dependencies (Qdrant, LLM APIs) — that's a readiness probe
    coming in M7.
    """
    return HealthStatus(status="ok")
