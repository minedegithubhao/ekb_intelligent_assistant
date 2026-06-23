"""Conversation statistics ORM model for admin dashboard queries."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import ForeignKey
from sqlalchemy.orm import Mapped, mapped_column

from app.db.models.base import BaseModel


class ConversationStatistic(BaseModel):
    """Aggregated statistics per conversation for fast admin listing."""

    __tablename__ = "conversation_statistics"

    conversation_id: Mapped[int] = mapped_column(
        ForeignKey("conversations.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
        index=True,
    )
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    message_count: Mapped[int] = mapped_column(nullable=False, default=0)
    last_message_at: Mapped[datetime | None] = mapped_column(nullable=True)
