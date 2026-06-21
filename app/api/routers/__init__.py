"""Central API router registry."""

from fastapi import APIRouter

from app.api.routers import auth, system

api_router = APIRouter()
api_router.include_router(system.router, tags=["system"])
api_router.include_router(auth.router, prefix="/auth", tags=["auth"])
