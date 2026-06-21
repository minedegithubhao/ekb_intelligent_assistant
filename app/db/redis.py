"""Redis client and small key-value helper functions."""

from __future__ import annotations

import logging
from typing import Any

from redis import Redis

from app.core.config import get_runtime_config
from app.core.exceptions import ServiceUnavailableException

logger = logging.getLogger(__name__)

redis_config = get_runtime_config().app.redis

redis_client = Redis(
    host=redis_config.host,
    port=redis_config.port,
    db=redis_config.db,
    password=redis_config.password,
    socket_timeout=redis_config.socket_timeout_seconds,
    decode_responses=True,
)


def ping_redis() -> dict[str, str]:
    # Health check used by /api/health/dependencies.
    try:
        redis_client.ping()
        return {"status": "ok"}
    except Exception as exc:
        logger.exception("redis ping failed")
        raise ServiceUnavailableException("redis unavailable") from exc


def get_value(key: str) -> str | None:
    return redis_client.get(key)


def set_value(key: str, value: Any, ttl_seconds: int | None = None) -> bool:
    return bool(redis_client.set(key, value, ex=ttl_seconds))


def delete_value(key: str) -> int:
    return int(redis_client.delete(key))


def exists(key: str) -> bool:
    return bool(redis_client.exists(key))
