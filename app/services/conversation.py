"""Service functions for user conversation and chat history management."""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.exceptions import BadRequestException, NotFoundException
from app.db.models.conversation import Conversation, ConversationMessage
from app.schemas.conversation import ConversationCreate, ConversationInfo, ConversationMessageInfo, ConversationQuestionAnswer
from app.schemas.retrieval import RetrievalResult
from app.services.retrieval import retrieve_answer


KNOWLEDGE_BASE_TYPES = {"enterprise", "personal"}
DEFAULT_CONVERSATION_TITLE = "新会话"
TITLE_MAX_LENGTH = 30
RETRIEVAL_FAILURE_ANSWER = "抱歉，当前知识库检索暂时不可用，你的问题已保存，请稍后再试。"

logger = logging.getLogger(__name__)


def _normalize_knowledge_base_type(knowledge_base_type: str) -> str:
    if knowledge_base_type not in KNOWLEDGE_BASE_TYPES:
        raise BadRequestException("invalid knowledge_base_type")
    return knowledge_base_type


def _clean_title(title: str | None) -> str:
    value = (title or "").strip()
    return value or DEFAULT_CONVERSATION_TITLE


def _title_from_question(question: str) -> str:
    value = " ".join(question.strip().split())
    if not value:
        return DEFAULT_CONVERSATION_TITLE
    if len(value) <= TITLE_MAX_LENGTH:
        return value
    return f"{value[:TITLE_MAX_LENGTH]}..."


def _get_conversation(
    db: Session,
    *,
    conversation_id: int,
    user_id: int,
    knowledge_base_type: str | None = None,
) -> Conversation:
    filters = [
        Conversation.id == conversation_id,
        Conversation.user_id == user_id,
        Conversation.is_deleted.is_(False),
    ]
    if knowledge_base_type:
        filters.append(Conversation.knowledge_base_type == _normalize_knowledge_base_type(knowledge_base_type))
    conversation = db.execute(select(Conversation).where(*filters)).scalar_one_or_none()
    if not conversation:
        raise NotFoundException("conversation not found")
    return conversation


def _first_user_message_title(db: Session, conversation_id: int) -> str | None:
    message = db.execute(
        select(ConversationMessage.content)
        .where(
            ConversationMessage.conversation_id == conversation_id,
            ConversationMessage.role == "user",
            ConversationMessage.is_deleted.is_(False),
        )
        .order_by(ConversationMessage.created_at.asc(), ConversationMessage.id.asc())
        .limit(1)
    ).scalar_one_or_none()
    return _title_from_question(message) if message else None


def conversation_to_info(db: Session, conversation: Conversation) -> ConversationInfo:
    title = _clean_title(conversation.title)
    if title == DEFAULT_CONVERSATION_TITLE:
        title = _first_user_message_title(db, conversation.id) or title
    return ConversationInfo(
        conversation_id=conversation.id,
        title=title,
        knowledge_base_type=conversation.knowledge_base_type,
        last_message_at=conversation.last_message_at,
        created_at=conversation.created_at,
        updated_at=conversation.updated_at,
    )


def message_to_info(message: ConversationMessage) -> ConversationMessageInfo:
    return ConversationMessageInfo(
        message_id=message.id,
        conversation_id=message.conversation_id,
        role=message.role,
        content=message.content,
        sources=message.sources_json or [],
        metadata=message.metadata_json or {},
        created_at=message.created_at,
    )


def list_conversations(db: Session, *, user_id: int, knowledge_base_type: str) -> list[ConversationInfo]:
    normalized_type = _normalize_knowledge_base_type(knowledge_base_type)
    conversations = db.execute(
        select(Conversation)
        .where(
            Conversation.user_id == user_id,
            Conversation.knowledge_base_type == normalized_type,
            Conversation.is_deleted.is_(False),
        )
        .order_by(
            func.coalesce(Conversation.last_message_at, Conversation.updated_at, Conversation.created_at).desc(),
            Conversation.id.desc(),
        )
    ).scalars().all()
    return [conversation_to_info(db, conversation) for conversation in conversations]


def create_conversation(db: Session, *, user_id: int, payload: ConversationCreate) -> ConversationInfo:
    normalized_type = _normalize_knowledge_base_type(payload.knowledge_base_type)
    conversation = Conversation(
        user_id=user_id,
        title=_clean_title(payload.title),
        knowledge_base_type=normalized_type,
    )
    db.add(conversation)
    db.flush()
    db.refresh(conversation)
    return conversation_to_info(db, conversation)


def list_conversation_messages(
    db: Session,
    *,
    user_id: int,
    conversation_id: int,
    knowledge_base_type: str,
) -> list[ConversationMessageInfo]:
    _get_conversation(
        db,
        conversation_id=conversation_id,
        user_id=user_id,
        knowledge_base_type=knowledge_base_type,
    )
    messages = db.execute(
        select(ConversationMessage)
        .where(
            ConversationMessage.conversation_id == conversation_id,
            ConversationMessage.user_id == user_id,
            ConversationMessage.is_deleted.is_(False),
        )
        .order_by(ConversationMessage.created_at.asc(), ConversationMessage.id.asc())
    ).scalars().all()
    return [message_to_info(message) for message in messages]


def delete_conversation(db: Session, *, user_id: int, conversation_id: int) -> dict[str, bool]:
    conversation = _get_conversation(db, conversation_id=conversation_id, user_id=user_id)
    conversation.is_deleted = True
    messages = db.execute(
        select(ConversationMessage).where(
            ConversationMessage.conversation_id == conversation.id,
            ConversationMessage.user_id == user_id,
            ConversationMessage.is_deleted.is_(False),
        )
    ).scalars().all()
    for message in messages:
        message.is_deleted = True
    db.flush()
    return {"deleted": True}


def add_question_message(
    db: Session,
    *,
    user_id: int,
    conversation_id: int,
    question: str,
    knowledge_base_type: str,
) -> ConversationQuestionAnswer:
    normalized_type = _normalize_knowledge_base_type(knowledge_base_type)
    cleaned_question = question.strip()
    if not cleaned_question:
        raise BadRequestException("question cannot be empty")
    conversation = _get_conversation(
        db,
        conversation_id=conversation_id,
        user_id=user_id,
        knowledge_base_type=normalized_type,
    )
    conversation_pk = conversation.id
    existing_user_message_count = db.execute(
        select(func.count(ConversationMessage.id)).where(
            ConversationMessage.conversation_id == conversation_pk,
            ConversationMessage.user_id == user_id,
            ConversationMessage.role == "user",
            ConversationMessage.is_deleted.is_(False),
        )
    ).scalar_one()
    history_messages = _history_messages_for_retrieval(
        db,
        conversation_id=conversation_pk,
        user_id=user_id,
    )
    now = datetime.now(UTC)
    user_message = ConversationMessage(
        conversation_id=conversation_pk,
        user_id=user_id,
        role="user",
        content=cleaned_question,
        sources_json=[],
        metadata_json={},
    )
    db.add(user_message)

    if existing_user_message_count == 0:
        conversation.title = _title_from_question(cleaned_question)
    conversation.last_message_at = now
    db.flush()
    db.commit()

    try:
        retrieval_result = retrieve_answer(
            db,
            question=cleaned_question,
            knowledge_base_type=normalized_type,
            history_messages=history_messages,
        )
        answer, sources, metadata = _retrieval_result_to_message_payload(retrieval_result)
    except Exception as exc:  # noqa: BLE001 - user question must stay saved when retrieval fails.
        db.rollback()
        logger.exception("retrieval failed for conversation_id=%s", conversation_pk)
        answer, sources, metadata = _retrieval_failure_payload(exc)

    assistant_now = datetime.now(UTC)
    assistant_message = ConversationMessage(
        conversation_id=conversation_pk,
        user_id=user_id,
        role="assistant",
        content=answer,
        sources_json=sources,
        metadata_json=metadata,
    )
    db.add(assistant_message)

    conversation.last_message_at = assistant_now
    db.flush()
    db.refresh(assistant_message)
    return ConversationQuestionAnswer(
        message_id=assistant_message.id,
        conversation_id=conversation_pk,
        answer=assistant_message.content,
        knowledge_base_type=normalized_type,
        sources=assistant_message.sources_json or [],
        hit_type=str((assistant_message.metadata_json or {}).get("hit_type", "none")),
        need_human_transfer=bool((assistant_message.metadata_json or {}).get("need_human_transfer", False)),
        created_at=assistant_message.created_at,
    )


def _history_messages_for_retrieval(
    db: Session,
    *,
    conversation_id: int,
    user_id: int,
) -> list[dict[str, str]]:
    rows = db.execute(
        select(ConversationMessage.role, ConversationMessage.content)
        .where(
            ConversationMessage.conversation_id == conversation_id,
            ConversationMessage.user_id == user_id,
            ConversationMessage.is_deleted.is_(False),
        )
        .order_by(ConversationMessage.created_at.asc(), ConversationMessage.id.asc())
    ).all()
    return [{"role": str(role), "content": str(content)} for role, content in rows if str(content).strip()]


def _retrieval_result_to_message_payload(result: RetrievalResult) -> tuple[str, list[dict[str, Any]], dict[str, Any]]:
    metadata = {
        **result.metadata,
        "hit_type": result.hit_type,
        "need_human_transfer": result.need_human_transfer,
        "debug": result.debug.model_dump(mode="json"),
    }
    return result.answer, result.sources, metadata


def _retrieval_failure_payload(exc: Exception) -> tuple[str, list[dict[str, Any]], dict[str, Any]]:
    error_message = getattr(exc, "message", str(exc))
    metadata = {
        "hit_type": "retrieval_error",
        "need_human_transfer": False,
        "retrieval_error": True,
        "error_type": exc.__class__.__name__,
        "error_message": error_message,
    }
    return RETRIEVAL_FAILURE_ANSWER, [], metadata
