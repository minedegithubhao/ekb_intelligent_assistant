"""Central API router registry."""

from fastapi import APIRouter

from app.api.routers import (
    admin_config,
    admin_conversation,
    admin_evaluation,
    admin_users,
    auth,
    conversation,
    offline_ingestion,
    system,
    vector_ingest_json,
)
from app.kb_version import router as kb_version_router

api_router = APIRouter()
api_router.include_router(system.router, tags=["system"])
api_router.include_router(auth.router, prefix="/auth", tags=["auth"])
api_router.include_router(conversation.router, tags=["conversations"])
api_router.include_router(admin_config.router, tags=["admin-config"])
api_router.include_router(admin_users.router, tags=["admin-users"])
api_router.include_router(admin_conversation.router, tags=["admin-conversations"])
api_router.include_router(admin_evaluation.router, tags=["admin-evaluations"])
api_router.include_router(offline_ingestion.router, tags=["offline-ingestion"])
api_router.include_router(vector_ingest_json.router, tags=["vector-ingest-json"])
api_router.include_router(kb_version_router.router)
