"""Structlog setup for github-analyzer.

Pretty-prints in dev (TTY detected), emits JSON lines in prod.
M0.3 ships the configurator; nodes wire it in M1+ via `get_logger(__name__)`.
"""

from __future__ import annotations

import logging
import sys
from typing import Any, cast

import structlog


def configure_logging(*, level: str = "INFO", json_output: bool | None = None) -> None:
    """Configure structlog + stdlib logging.

    Parameters
    ----------
    level:
        Minimum log level (DEBUG, INFO, WARNING, ERROR).
    json_output:
        Force JSON lines if True, pretty console if False. When None,
        auto-detect: JSON when stderr is not a TTY (Docker / Railway).
    """
    if json_output is None:
        json_output = not sys.stderr.isatty()

    renderer: Any = (
        structlog.processors.JSONRenderer()
        if json_output
        else structlog.dev.ConsoleRenderer(colors=True)
    )

    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso", utc=True),
            structlog.processors.StackInfoRenderer(),
            structlog.processors.format_exc_info,
            renderer,
        ],
        wrapper_class=structlog.make_filtering_bound_logger(logging.getLevelNamesMapping()[level]),
        context_class=dict,
        logger_factory=structlog.PrintLoggerFactory(file=sys.stderr),
        cache_logger_on_first_use=True,
    )


def get_logger(name: str) -> structlog.stdlib.BoundLogger:
    """Return a bound structlog logger keyed by module name."""
    return cast(structlog.stdlib.BoundLogger, structlog.get_logger(name))
