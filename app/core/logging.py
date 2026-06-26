"""Logging setup and HTTP request logging middleware."""

from __future__ import annotations

import logging
import sys
import time
from collections.abc import Callable
from logging.handlers import RotatingFileHandler
from pathlib import Path

from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware


PROJECT_ROOT = Path(__file__).resolve().parents[2]
LOG_FORMAT = "%(asctime)s %(levelname)s [%(name)s] %(message)s"


def setup_logging(
    level: str = "INFO",
    log_dir: str = "logs",
    app_file: str = "app.log",
    error_file: str = "error.log",
    max_bytes: int = 10 * 1024 * 1024,
    backup_count: int = 5,
) -> None:
    """Configure console logs plus rotating local log files."""

    resolved_dir = Path(log_dir)
    if not resolved_dir.is_absolute():
        resolved_dir = PROJECT_ROOT / resolved_dir
    resolved_dir.mkdir(parents=True, exist_ok=True)

    formatter = logging.Formatter(LOG_FORMAT)

    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setFormatter(formatter)

    app_handler = RotatingFileHandler(
        resolved_dir / app_file,
        maxBytes=max_bytes,
        backupCount=backup_count,
        encoding="utf-8",
    )
    app_handler.setFormatter(formatter)

    error_handler = RotatingFileHandler(
        resolved_dir / error_file,
        maxBytes=max_bytes,
        backupCount=backup_count,
        encoding="utf-8",
    )
    error_handler.setLevel(logging.ERROR)
    error_handler.setFormatter(formatter)

    logging.basicConfig(
        level=getattr(logging, level.upper(), logging.INFO),
        handlers=[console_handler, app_handler, error_handler],
        force=True,
    )


class RequestLoggingMiddleware(BaseHTTPMiddleware):
    """Writes one concise access log line for every HTTP request."""

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        logger = logging.getLogger("app.request")
        start = time.perf_counter()
        response: Response | None = None
        try:
            response = await call_next(request)
            return response
        finally:
            elapsed_ms = int((time.perf_counter() - start) * 1000)
            status_code = response.status_code if response else 500
            user_id = getattr(request.state, "user_id", "-")
            logger.info(
                "%s %s status=%s elapsed_ms=%s user=%s",
                request.method,
                request.url.path,
                status_code,
                elapsed_ms,
                user_id,
            )
