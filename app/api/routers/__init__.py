"""Central API router registry."""

from fastapi import APIRouter

from app.api.routers import admin_config, admin_users, auth, system

api_router = APIRouter()
api_router.include_router(system.router, tags=["system"])
api_router.include_router(auth.router, prefix="/auth", tags=["auth"])
api_router.include_router(admin_config.router, tags=["admin-config"])
api_router.include_router(admin_users.router, tags=["admin-users"])
