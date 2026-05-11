# syntax=docker/dockerfile:1.7

# ──────────────────────────────────────────────────────────────────────
# Builder — uses uv to resolve and install dependencies into a venv
# ──────────────────────────────────────────────────────────────────────
FROM python:3.12-slim AS builder

# Copy uv from the official Astral image (matches our local dev tool).
COPY --from=ghcr.io/astral-sh/uv:0.5.0 /uv /uvx /bin/

ENV UV_LINK_MODE=copy \
    UV_COMPILE_BYTECODE=1 \
    UV_PYTHON_DOWNLOADS=never \
    PYTHONUNBUFFERED=1

WORKDIR /app

# Layer 1 — dependency resolution. Cached unless pyproject.toml or uv.lock change.
COPY pyproject.toml uv.lock ./
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-install-project --no-dev

# Layer 2 — install the project itself (separate so source edits don't bust the deps cache).
COPY src ./src
COPY README.md ./
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev

# ──────────────────────────────────────────────────────────────────────
# Runtime — slim final image, copies only the venv + source from builder
# ──────────────────────────────────────────────────────────────────────
FROM python:3.12-slim AS runtime

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PATH="/app/.venv/bin:$PATH"

WORKDIR /app

# Copy the virtualenv and the source tree from the builder stage.
COPY --from=builder /app/.venv /app/.venv
COPY --from=builder /app/src /app/src

# Non-root user — basic hardening for prod-like dev parity.
RUN groupadd --system app && useradd --system --gid app --no-create-home app \
    && mkdir -p /data && chown -R app:app /app /data
USER app

EXPOSE 8000

# Default command serves the FastAPI app. docker-compose can override with --reload for dev.
CMD ["uvicorn", "github_analyzer.api:app", "--host", "0.0.0.0", "--port", "8000"]
