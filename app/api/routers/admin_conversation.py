"""Admin conversation management APIs."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.api.deps import require_admin
from app.core.response import page_response, success_response
from app.db.mysql import get_db
from app.services.admin_conversation import (
    delete_admin_conversation,
    get_admin_stats,
    list_admin_conversation_messages,
    list_admin_conversations,
)

router = APIRouter(prefix="/admin/conversations", dependencies=[Depends(require_admin)])


@router.get("")
def get_admin_conversations(
    keyword: str | None = Query(default=None, max_length=128),
    user_id: int | None = Query(default=None),
    knowledge_base_type: str | None = Query(default=None, max_length=32),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=500),
    db: Session = Depends(get_db),
) -> dict:
    items, total = list_admin_conversations(
        db,
        keyword=keyword,
        user_id=user_id,
        knowledge_base_type=knowledge_base_type,
        page=page,
        page_size=page_size,
    )
    return page_response(
        [item.model_dump(mode="json") for item in items],
        total=total,
        page=page,
        page_size=page_size,
    )


@router.get("/stats")
def get_conversation_stats(db: Session = Depends(get_db)) -> dict:
    stats = get_admin_stats(db)
    return success_response(stats.model_dump(mode="json"))


@router.get("/{conversation_id}/messages")
def get_conversation_messages(
    conversation_id: int,
    db: Session = Depends(get_db),
) -> dict:
    data = list_admin_conversation_messages(db, conversation_id=conversation_id)
    return success_response([item.model_dump(mode="json") for item in data])


@router.delete("/{conversation_id}")
def remove_conversation(
    conversation_id: int,
    db: Session = Depends(get_db),
) -> dict:
    result = delete_admin_conversation(db, conversation_id=conversation_id)
    return success_response(result)
