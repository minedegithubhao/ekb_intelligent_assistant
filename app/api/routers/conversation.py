"""User conversation and chat history APIs."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.api.deps import CurrentUser, get_current_user
from app.core.response import success_response
from app.db.mysql import get_db
from app.schemas.conversation import ConversationCreate, ConversationQuestionCreate
from app.services.conversation import (
    add_question_message,
    create_conversation,
    delete_conversation,
    list_conversation_messages,
    list_conversations,
)

router = APIRouter(prefix="/conversations")


@router.get("")
def get_conversations(
    knowledge_base_type: str = Query(max_length=32),
    current_user: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    conversations = list_conversations(db, user_id=current_user.id, knowledge_base_type=knowledge_base_type)
    return success_response([item.model_dump(mode="json") for item in conversations])


@router.post("")
def create_user_conversation(
    payload: ConversationCreate,
    current_user: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    conversation = create_conversation(db, user_id=current_user.id, payload=payload)
    return success_response(conversation.model_dump(mode="json"))


@router.get("/{conversation_id}/messages")
def get_conversation_messages(
    conversation_id: int,
    knowledge_base_type: str = Query(max_length=32),
    current_user: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
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
    answer = add_question_message(
        db,
        user_id=current_user.id,
        conversation_id=conversation_id,
        question=payload.question,
        knowledge_base_type=payload.knowledge_base_type,
    )
    return success_response(answer.model_dump(mode="json"))


@router.delete("/{conversation_id}")
def remove_conversation(
    conversation_id: int,
    current_user: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    return success_response(delete_conversation(db, user_id=current_user.id, conversation_id=conversation_id))
