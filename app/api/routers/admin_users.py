"""Administrator user management APIs."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.api.deps import CurrentUser, require_admin
from app.core.response import page_response, success_response
from app.db.mysql import get_db
from app.schemas.admin_users import AdminUserCreate, AdminUserStatusUpdate, AdminUserUpdate
from app.services.admin_users import create_admin_user, disable_admin_user, list_admin_users, update_admin_user

router = APIRouter(prefix="/admin/users", dependencies=[Depends(require_admin)])


@router.get("")
def get_users(
    keyword: str | None = Query(default=None, max_length=128),
    role: str | None = Query(default=None, max_length=32),
    status: str | None = Query(default=None, max_length=32),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=100, ge=1, le=500),
    db: Session = Depends(get_db),
) -> dict:
    users, total = list_admin_users(db, keyword=keyword, role=role, status=status, page=page, page_size=page_size)
    return page_response([item.model_dump(mode="json") for item in users], total=total, page=page, page_size=page_size)


@router.post("")
def create_user(payload: AdminUserCreate, db: Session = Depends(get_db)) -> dict:
    user = create_admin_user(db, payload)
    return success_response(user.model_dump(mode="json"))


@router.put("/{user_id}")
def update_user(
    user_id: int,
    payload: AdminUserUpdate,
    current_user: CurrentUser = Depends(require_admin),
    db: Session = Depends(get_db),
) -> dict:
    user = update_admin_user(db, user_id=user_id, payload=payload, current_user_id=current_user.id)
    return success_response(user.model_dump(mode="json"))


@router.patch("/{user_id}/status")
def update_user_status(
    user_id: int,
    payload: AdminUserStatusUpdate,
    current_user: CurrentUser = Depends(require_admin),
    db: Session = Depends(get_db),
) -> dict:
    user = update_admin_user(
        db,
        user_id=user_id,
        payload=AdminUserUpdate(status=payload.status),
        current_user_id=current_user.id,
    )
    return success_response(user.model_dump(mode="json"))


@router.delete("/{user_id}")
def disable_user(
    user_id: int,
    current_user: CurrentUser = Depends(require_admin),
    db: Session = Depends(get_db),
) -> dict:
    user = disable_admin_user(db, user_id=user_id, current_user_id=current_user.id)
    return success_response(user.model_dump(mode="json"))
