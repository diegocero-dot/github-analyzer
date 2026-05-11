"""Smoke tests for the FastAPI stub (M0.4)."""

from __future__ import annotations

from fastapi.testclient import TestClient

from github_analyzer import __version__
from github_analyzer.api import app

client = TestClient(app)


def test_root_returns_service_identity() -> None:
    """`GET /` returns the service name, current version, and ok status."""
    response = client.get("/")
    assert response.status_code == 200
    payload = response.json()
    assert payload["service"] == "github-analyzer"
    assert payload["version"] == __version__
    assert payload["status"] == "ok"


def test_health_returns_ok() -> None:
    """`GET /health` is a liveness probe — always returns 200 with status ok."""
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_openapi_schema_is_served() -> None:
    """FastAPI must expose its OpenAPI schema at `/openapi.json`."""
    response = client.get("/openapi.json")
    assert response.status_code == 200
    schema = response.json()
    assert schema["info"]["title"] == "github-analyzer"
    assert schema["info"]["version"] == __version__
