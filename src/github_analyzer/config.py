"""Pydantic Settings — environment-driven configuration.

Loads from `.env` (CLI / dev) or real environment variables (Docker / prod).
Every secret is sourced from env; defaults are intentionally empty so that
missing values surface as `ValueError` at first use, not as silent runtime bugs.
"""

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Runtime configuration for github-analyzer.

    See `.env.example` for the required keys per milestone.
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # Required from M1 onwards (GitHub fetcher MVP).
    github_token: str = Field(default="", description="GitHub PAT, public_repo scope.")

    # Required from M3 onwards (single-agent baseline + synthesis).
    anthropic_api_key: str = Field(default="", description="Anthropic API key for Claude.")

    # Required from M2 onwards (indexing + embeddings).
    openai_api_key: str = Field(default="", description="OpenAI API key for embeddings.")

    # Qdrant connection (M2+).
    qdrant_url: str = Field(default="http://localhost:6333", description="Qdrant endpoint.")
    qdrant_api_key: str = Field(default="", description="Qdrant Cloud API key (prod only).")


def get_settings() -> Settings:
    """Return a fresh `Settings` instance.

    Tests should patch `os.environ` via `monkeypatch` rather than cache a
    singleton — this keeps test isolation simple at the cost of one
    environment scan per call.
    """
    return Settings()
