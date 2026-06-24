"""知识库版本管理的 Admin APIs。"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.api.deps import CurrentUser, require_admin
from app.core.response import success_response
from app.db.mysql import get_db
from app.kb_version.schemas import KbVersionCreate, KbVersionOperation
from app.kb_version.service import KbVersionService

router = APIRouter(prefix="/admin/kb/versions", tags=["kb-version"], dependencies=[Depends(require_admin)])


@router.get("")
def list_versions(
    keyword: str | None = Query(default=None, description="版本号搜索关键字"),
    db: Session = Depends(get_db),
) -> dict:
    """查询版本列表，并返回 active/previous 指针摘要。"""

    payload = KbVersionService(db).list_versions(keyword=keyword)
    return success_response(payload.model_dump(mode="json"))


@router.post("")
def create_version(
    payload: KbVersionCreate,
    current_user: CurrentUser = Depends(require_admin),
    db: Session = Depends(get_db),
) -> dict:
    """创建 staged 版本，并返回 kb_versions 表字段。"""

    version = KbVersionService(db).create_version(payload, operator_id=str(current_user.id))
    return success_response(version.model_dump(mode="json"))


@router.post("/{kb_version}/publish")
def publish_version(
    kb_version: str,
    payload: KbVersionOperation | None = None,
    current_user: CurrentUser = Depends(require_admin),
    db: Session = Depends(get_db),
) -> dict:
    """将 staged 版本发布为 active。"""

    version = KbVersionService(db).publish(
        kb_version,
        operator_id=str(current_user.id),
        message=payload.message if payload else None,
    )
    return success_response(version.model_dump(mode="json"))


@router.post("/rollback")
def quick_rollback(
    payload: KbVersionOperation | None = None,
    current_user: CurrentUser = Depends(require_admin),
    db: Session = Depends(get_db),
) -> dict:
    """快速回滚到 previous 指针指向的版本。"""

    version = KbVersionService(db).rollback(
        operator_id=str(current_user.id),
        message=payload.message if payload else None,
    )
    return success_response(version.model_dump(mode="json"))


@router.post("/{kb_version}/rollback")
def rollback_to_version(
    kb_version: str,
    payload: KbVersionOperation | None = None,
    current_user: CurrentUser = Depends(require_admin),
    db: Session = Depends(get_db),
) -> dict:
    """回滚到指定的 archived 版本。"""

    version = KbVersionService(db).rollback(
        target_kb_version=kb_version,
        operator_id=str(current_user.id),
        message=payload.message if payload else None,
    )
    return success_response(version.model_dump(mode="json"))


@router.get("/pointers/current")
def get_pointer(db: Session = Depends(get_db)) -> dict:
    """获取当前版本指针。"""

    pointer = KbVersionService(db).get_pointer()
    return success_response(pointer.model_dump(mode="json"))


@router.get("/logs/recent")
def list_action_logs(limit: int = Query(default=20, ge=1, le=100), db: Session = Depends(get_db)) -> dict:
    """查询最近的版本操作日志。"""

    logs = KbVersionService(db).list_action_logs(limit=limit)
    return success_response([item.model_dump(mode="json") for item in logs])
