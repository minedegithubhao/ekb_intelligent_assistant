"""User conversation and chat history APIs."""

from __future__ import annotations

import json

from fastapi import APIRouter, Depends, Query
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from app.api.deps import CurrentUser, get_current_user
from app.core.exceptions import PermissionDeniedException
from app.core.response import success_response
from app.db.mysql import get_db
from app.schemas.conversation import ConversationCreate, ConversationQuestionCreate
from app.services.conversation import (
    add_question_message,
    create_conversation,
    delete_conversation,
    list_conversation_messages,
    list_conversations,
    stream_question_message_events,
)

router = APIRouter(prefix="/conversations")


def _assert_knowledge_base_access(current_user: CurrentUser, knowledge_base_type: str) -> None:
    if current_user.is_admin:
        return
    category = current_user.category
    allowed_type = None
    if category in {"merchant", "enterprise"}:
        allowed_type = "enterprise"
    elif category in {"individual", "personal"}:
        allowed_type = "personal"
    if allowed_type is None or knowledge_base_type != allowed_type:
        raise PermissionDeniedException("knowledge base access denied")


@router.get("")
def get_conversations(
    knowledge_base_type: str = Query(max_length=32),
    current_user: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    _assert_knowledge_base_access(current_user, knowledge_base_type)
    conversations = list_conversations(db, user_id=current_user.id, knowledge_base_type=knowledge_base_type)
    return success_response([item.model_dump(mode="json") for item in conversations])


@router.post("")
def create_user_conversation(
    payload: ConversationCreate,
    current_user: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    _assert_knowledge_base_access(current_user, payload.knowledge_base_type)
    conversation = create_conversation(db, user_id=current_user.id, payload=payload)
    return success_response(conversation.model_dump(mode="json"))


@router.get("/{conversation_id}/messages")
def get_conversation_messages(
    conversation_id: int,
    knowledge_base_type: str = Query(max_length=32),
    current_user: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    _assert_knowledge_base_access(current_user, knowledge_base_type)
    messages = list_conversation_messages(
        db,
        user_id=current_user.id,
        conversation_id=conversation_id,
        knowledge_base_type=knowledge_base_type,
    )
    return success_response([item.model_dump(mode="json") for item in messages])


@router.post("/{conversation_id}/messages")
def create_conversation_message(
    conversation_id: int,
    payload: ConversationQuestionCreate,
    current_user: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    _assert_knowledge_base_access(current_user, payload.knowledge_base_type)
    answer = add_question_message(
        db,
        user_id=current_user.id,
        conversation_id=conversation_id,
        question=payload.question,
        knowledge_base_type=payload.knowledge_base_type,
    )
    return success_response(answer.model_dump(mode="json"))


@router.post("/{conversation_id}/messages/stream")
def create_conversation_message_stream(
    conversation_id: int,
    payload: ConversationQuestionCreate,
    current_user: CurrentUser = Depends(get_current_user),
) -> StreamingResponse:
    _assert_knowledge_base_access(current_user, payload.knowledge_base_type)

    def encode_events():
        for item in stream_question_message_events(
            user_id=current_user.id,
            conversation_id=conversation_id,
            question=payload.question,
            knowledge_base_type=payload.knowledge_base_type,
        ):
            data = json.dumps(item["data"], ensure_ascii=False)
            yield f"event: {item['event']}\ndata: {data}\n\n"

    return StreamingResponse(
        encode_events(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


@router.delete("/{conversation_id}")
def remove_conversation(
    conversation_id: int,
    current_user: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    return success_response(delete_conversation(db, user_id=current_user.id, conversation_id=conversation_id))
