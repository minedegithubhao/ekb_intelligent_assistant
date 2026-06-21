"""System health endpoints for app and dependency checks."""

from __future__ import annotations

from fastapi import APIRouter

from app.core.config import get_runtime_config
from app.core.response import success_response
from app.db.milvus import milvus_client
from app.db.mysql import ping_mysql
from app.db.redis import ping_redis

router = APIRouter()


@router.get("/health")
def health() -> dict:
    config = get_runtime_config()
    return success_response(
        {
            "app": config.app.app.name,
            "env": config.app.app.env,
            "status": "ok",
        }
    )


@router.get("/health/dependencies")
def dependency_health() -> dict:
    # Used during local setup to confirm MySQL, Redis, and Milvus are reachable.
    return success_response(
        {
            "mysql": ping_mysql(),
            "redis": ping_redis(),
            "milvus": milvus_client.ping(),
            "sample_collection": milvus_client.build_collection_name("v1", "doc"),
        }
    )
