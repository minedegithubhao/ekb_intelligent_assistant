"""Admin APIs for offline document ingestion."""

from __future__ import annotations

from fastapi import APIRouter, BackgroundTasks, Depends, File, Form, Query, UploadFile
from sqlalchemy.orm import Session

from app.api.deps import CurrentUser, require_admin
from app.core.response import success_response
from app.db.mysql import get_db
from app.schemas.offline_ingestion import OfflineIngestionConfigCreate, OfflineIngestionTaskCreate, OfflineIngestionTaskInfo, OfflineUploadTaskCreate
from app.services.offline_ingestion import (
    activate_config,
    create_config,
    create_task,
    create_uploaded_document_task,
    create_uploaded_faq_task,
    get_active_config_info,
    get_task,
    list_server_directories,
    list_configs,
    list_tasks,
    run_offline_ingestion_task,
)

router = APIRouter(prefix="/admin/offline-ingestion", dependencies=[Depends(require_admin)])


@router.get("/configs")
def get_configs(db: Session = Depends(get_db)) -> dict:
    return success_response(list_configs(db))


@router.get("/configs/active")
def get_active_config(db: Session = Depends(get_db)) -> dict:
    return success_response(get_active_config_info(db))


@router.get("/directories")
def get_server_directories(path: str | None = Query(default=None)) -> dict:
    return success_response(list_server_directories(path))


@router.post("/configs")
def create_ingestion_config(
    payload: OfflineIngestionConfigCreate,
    current_user: CurrentUser = Depends(require_admin),
    db: Session = Depends(get_db),
) -> dict:
    row = create_config(db, payload=payload, created_by=current_user.id)
    return success_response({"id": row.id, "status": "standby"})


@router.post("/configs/{config_id}/activate")
def activate_ingestion_config(config_id: int, db: Session = Depends(get_db)) -> dict:
    row = activate_config(db, config_id=config_id)
    return success_response({"id": row.id, "status": "active"})


@router.post("/tasks")
def create_ingestion_task(
    payload: OfflineIngestionTaskCreate,
    background_tasks: BackgroundTasks,
    current_user: CurrentUser = Depends(require_admin),
    db: Session = Depends(get_db),
) -> dict:
    task = create_task(db, payload=payload, created_by=current_user.id)
    db.commit()
    background_tasks.add_task(run_offline_ingestion_task, task.task_id)
    return success_response({"task_id": task.task_id, "status": task.status})


@router.post("/document-tasks")
async def create_document_upload_task(
    background_tasks: BackgroundTasks,
    kb_version: str = Form(...),
    scope: str = Form(...),
    version_description: str | None = Form(default=None),
    auto_publish: bool = Form(default=False),
    files: list[UploadFile] = File(...),
    current_user: CurrentUser = Depends(require_admin),
    db: Session = Depends(get_db),
) -> dict:
    payload = OfflineUploadTaskCreate(
        kb_version=kb_version,
        scope=scope,
        version_description=version_description,
        auto_publish=auto_publish,
    )
    task = await create_uploaded_document_task(db, payload=payload, files=files, created_by=current_user.id)
    db.commit()
    background_tasks.add_task(run_offline_ingestion_task, task.task_id)
    return success_response({
        "task_id": task.task_id,
        "status": task.status,
        "ingest_type": task.ingest_type,
        "kb_version": task.kb_version,
    })


@router.post("/faq-tasks")
async def create_faq_upload_task(
    background_tasks: BackgroundTasks,
    kb_version: str = Form(...),
    scope: str = Form(...),
    version_description: str | None = Form(default=None),
    auto_publish: bool = Form(default=False),
    files: list[UploadFile] = File(...),
    current_user: CurrentUser = Depends(require_admin),
    db: Session = Depends(get_db),
) -> dict:
    payload = OfflineUploadTaskCreate(
        kb_version=kb_version,
        scope=scope,
        version_description=version_description,
        auto_publish=auto_publish,
    )
    task = await create_uploaded_faq_task(db, payload=payload, files=files, created_by=current_user.id)
    db.commit()
    background_tasks.add_task(run_offline_ingestion_task, task.task_id)
    return success_response({
        "task_id": task.task_id,
        "status": task.status,
        "ingest_type": task.ingest_type,
        "kb_version": task.kb_version,
    })


@router.get("/tasks")
def get_tasks(limit: int = Query(default=20, ge=1, le=100), db: Session = Depends(get_db)) -> dict:
    return success_response(list_tasks(db, limit=limit))


@router.get("/tasks/{task_id}")
def get_ingestion_task(task_id: str, db: Session = Depends(get_db)) -> dict:
    task = get_task(db, task_id=task_id)
    return success_response(OfflineIngestionTaskInfo.model_validate(task).model_dump(mode="json"))
