"""Admin dashboard retrieval hot configuration APIs."""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.api.deps import CurrentUser, require_admin
from app.core.response import success_response
from app.db.mysql import get_db
from app.schemas.config import DashboardConfigSave
from app.services.config_versions import (
    activate_hot_config,
    build_dashboard_payload,
    get_effective_retrieval_config,
    list_hot_configs,
    save_hot_config,
)

router = APIRouter(prefix="/admin", dependencies=[Depends(require_admin)])


@router.get("/dashboard/config")
def get_dashboard_config(db: Session = Depends(get_db)) -> dict:
    config, hot_config, source = get_effective_retrieval_config(db)
    return success_response(build_dashboard_payload(config, hot_config, source))


@router.put("/dashboard/config")
def save_dashboard_config(
    payload: DashboardConfigSave,
    current_user: CurrentUser = Depends(require_admin),
    db: Session = Depends(get_db),
) -> dict:
    hot_config = save_hot_config(db, config=payload.config, created_by=current_user.id)
    db.flush()
    db.refresh(hot_config)
    return success_response(
        {
            "id": hot_config.id,
            "config_name": hot_config.config_name,
            "status": "active" if hot_config.is_enabled else "standby",
            "is_enabled": hot_config.is_enabled,
        }
    )


@router.get("/config/versions")
def get_config_versions(db: Session = Depends(get_db)) -> dict:
    return success_response(list_hot_configs(db))


@router.post("/config/versions")
def create_version(
    payload: DashboardConfigSave,
    current_user: CurrentUser = Depends(require_admin),
    db: Session = Depends(get_db),
) -> dict:
    hot_config = save_hot_config(db, config=payload.config, created_by=current_user.id)
    db.flush()
    db.refresh(hot_config)
    return success_response(
        {
            "id": hot_config.id,
            "config_name": hot_config.config_name,
            "version_no": hot_config.id,
            "status": "active" if hot_config.is_enabled else "standby",
        }
    )


@router.post("/config/versions/{version_id}/activate")
def activate_version(
    version_id: int,
    current_user: CurrentUser = Depends(require_admin),
    db: Session = Depends(get_db),
) -> dict:
    hot_config = activate_hot_config(db, config_id=version_id, activated_by=current_user.id)
    db.flush()
    db.refresh(hot_config)
    return success_response(
        {
            "id": hot_config.id,
            "config_name": hot_config.config_name,
            "version_no": hot_config.id,
            "status": "active" if hot_config.is_enabled else "standby",
            "activated_at": hot_config.created_at,
        }
    )
