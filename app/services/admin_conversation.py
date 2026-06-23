"""Admin conversation management service."""

from __future__ import annotations

from sqlalchemy import func, or_, select, text
from sqlalchemy.orm import Session

from app.core.exceptions import NotFoundException
from app.db.models.auth import User
from app.db.models.conversation import Conversation, ConversationMessage
from app.db.models.conversation_statistics import ConversationStatistic
from app.schemas.admin_conversation import (
    AdminConversationItem,
    AdminConversationMessageItem,
    AdminConversationStats,
)


KB_TYPE_MAP = {
    "enterprise": "企业知识库",
    "personal": "个人知识库",
}


def _knowledge_base_name(kb_type: str) -> str:
    return KB_TYPE_MAP.get(kb_type, "未知知识库")


def _refresh_statistics(db: Session) -> None:
    """Sync conversation_statistics from source tables (MySQL ON DUPLICATE KEY UPDATE)."""
    db.execute(
        text(
            """
            INSERT INTO conversation_statistics
                (conversation_id, user_id, message_count, last_message_at)
            SELECT
                c.id AS conversation_id,
                c.user_id,
                COUNT(cm.id) AS message_count,
                MAX(cm.created_at) AS last_message_at
            FROM conversations c
            LEFT JOIN conversation_messages cm
                ON cm.conversation_id = c.id AND cm.is_deleted = 0
            WHERE c.is_deleted = 0
            GROUP BY c.id, c.user_id
            ON DUPLICATE KEY UPDATE
                user_id = VALUES(user_id),
                message_count = VALUES(message_count),
                last_message_at = VALUES(last_message_at)
            """
        )
    )
    db.flush()


def list_admin_conversations(
    db: Session,
    *,
    keyword: str | None = None,
    user_id: int | None = None,
    knowledge_base_type: str | None = None,
    page: int = 1,
    page_size: int = 20,
) -> tuple[list[AdminConversationItem], int]:
    _refresh_statistics(db)

    filters = [Conversation.is_deleted.is_(False)]
    if user_id:
        filters.append(Conversation.user_id == user_id)
    if knowledge_base_type:
        filters.append(Conversation.knowledge_base_type == knowledge_base_type)
    if keyword:
        like_kw = f"%{keyword}%"
        filters.append(
            or_(
                Conversation.title.like(like_kw),
                Conversation.id.like(like_kw),
            )
        )

    total = db.execute(
        select(func.count()).select_from(Conversation).where(*filters)
    ).scalar_one()

    rows = db.execute(
        select(Conversation, User, ConversationStatistic)
        .join(User, Conversation.user_id == User.id)
        .join(
            ConversationStatistic,
            ConversationStatistic.conversation_id == Conversation.id,
            isouter=True,
        )
        .where(*filters)
        .order_by(Conversation.last_message_at.desc().nullslast())
        .offset((page - 1) * page_size)
        .limit(page_size)
    ).all()

    items: list[AdminConversationItem] = []
    for conv, user, stat in rows:
        items.append(
            AdminConversationItem(
                conversation_id=conv.id,
                user_id=user.id,
                username=user.username,
                display_name=user.display_name or user.username,
                title=conv.title or "新会话",
                knowledge_base_type=conv.knowledge_base_type,
                knowledge_base_name=_knowledge_base_name(conv.knowledge_base_type),
                message_count=stat.message_count if stat else 0,
                last_message_at=stat.last_message_at if stat else conv.last_message_at,
                created_at=conv.created_at,
            )
        )
    return items, int(total)


def get_admin_stats(db: Session) -> AdminConversationStats:
    _refresh_statistics(db)

    total_conversations = db.execute(
        select(func.count()).select_from(Conversation).where(Conversation.is_deleted.is_(False))
    ).scalar_one()

    total_messages = db.execute(
        select(func.coalesce(func.sum(ConversationStatistic.message_count), 0))
        .select_from(ConversationStatistic)
        .join(Conversation, ConversationStatistic.conversation_id == Conversation.id)
        .where(Conversation.is_deleted.is_(False))
    ).scalar_one()

    total_users = db.execute(
        select(func.count(func.distinct(Conversation.user_id)))
        .select_from(Conversation)
        .where(Conversation.is_deleted.is_(False))
    ).scalar_one()

    return AdminConversationStats(
        total_conversations=int(total_conversations),
        total_messages=int(total_messages),
        total_users=int(total_users),
    )


def list_admin_conversation_messages(
    db: Session, conversation_id: int
) -> list[AdminConversationMessageItem]:
    conv = db.execute(
        select(Conversation).where(
            Conversation.id == conversation_id,
            Conversation.is_deleted.is_(False),
        )
    ).scalar_one_or_none()
    if not conv:
        raise NotFoundException("conversation not found")

    messages = db.execute(
        select(ConversationMessage)
        .where(
            ConversationMessage.conversation_id == conversation_id,
            ConversationMessage.is_deleted.is_(False),
        )
        .order_by(ConversationMessage.created_at.asc(), ConversationMessage.id.asc())
    ).scalars().all()

    return [
        AdminConversationMessageItem(
            message_id=m.id,
            conversation_id=m.conversation_id,
            role=m.role,
            content=m.content,
            sources=m.sources_json,
            metadata=m.metadata_json,
            created_at=m.created_at,
        )
        for m in messages
    ]


def delete_admin_conversation(db: Session, conversation_id: int) -> dict[str, bool]:
    conv = db.execute(
        select(Conversation).where(
            Conversation.id == conversation_id,
            Conversation.is_deleted.is_(False),
        )
    ).scalar_one_or_none()
    if not conv:
        raise NotFoundException("conversation not found")

    conv.is_deleted = True

    stat = db.execute(
        select(ConversationStatistic).where(
            ConversationStatistic.conversation_id == conversation_id
        )
    ).scalar_one_or_none()
    if stat:
        stat.is_deleted = True

    db.execute(
        text("UPDATE conversation_messages SET is_deleted = 1 WHERE conversation_id = :conv_id"),
        {"conv_id": conversation_id},
    )
    db.flush()
    return {"deleted": True}
