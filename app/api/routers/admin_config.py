"""Admin dashboard and configuration version APIs."""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.api.deps import CurrentUser, require_admin
from app.core.response import success_response
from app.db.mysql import get_db
from app.schemas.config import ConfigVersionCreate
from app.services.config_versions import (
    activate_config_version,
    build_dashboard_payload,
    create_config_version,
    get_effective_retrieval_config,
    list_config_versions,
)

router = APIRouter(prefix="/admin", dependencies=[Depends(require_admin)])


@router.get("/dashboard/config")
def get_dashboard_config(db: Session = Depends(get_db)) -> dict:
    config, version, source = get_effective_retrieval_config(db)
    return success_response(build_dashboard_payload(config, version, source))


@router.get("/config/versions")
def get_config_versions(db: Session = Depends(get_db)) -> dict:
    return success_response([item.model_dump(mode="json") for item in list_config_versions(db)])


@router.post("/config/versions")
def create_version(
    payload: ConfigVersionCreate,
    current_user: CurrentUser = Depends(require_admin),
    db: Session = Depends(get_db),
) -> dict:
    version = create_config_version(
        db,
        config=payload.config,
        created_by=current_user.id,
        description=payload.description,
        activate=payload.activate,
    )
    db.flush()
    db.refresh(version)
    return success_response(
        {
            "id": version.id,
            "version_no": version.version_no,
            "status": version.status,
        }
    )


@router.post("/config/versions/{version_id}/activate")
def activate_version(
    version_id: int,
    current_user: CurrentUser = Depends(require_admin),
    db: Session = Depends(get_db),
) -> dict:
    version = activate_config_version(db, version_id=version_id, activated_by=current_user.id)
    db.flush()
    db.refresh(version)
    return success_response(
        {
            "id": version.id,
            "version_no": version.version_no,
            "status": version.status,
            "activated_at": version.activated_at,
        }
    )
