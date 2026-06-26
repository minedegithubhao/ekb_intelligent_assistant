"""Conversation and chat message ORM models."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, ForeignKey, JSON, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.models.base import BaseModel


class Conversation(BaseModel):
    __tablename__ = "conversations"

    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    title: Mapped[str | None] = mapped_column(String(255), nullable=True)
    knowledge_base_type: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    last_message_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True, index=True)

    messages: Mapped[list["ConversationMessage"]] = relationship(
        back_populates="conversation",
        cascade="all, delete-orphan",
        lazy="selectin",
    )


class ConversationMessage(BaseModel):
    __tablename__ = "conversation_messages"

    conversation_id: Mapped[int] = mapped_column(
        ForeignKey("conversations.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    role: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    sources_json: Mapped[list[dict[str, Any]] | None] = mapped_column(JSON, nullable=True)
    metadata_json: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)

    conversation: Mapped[Conversation] = relationship(back_populates="messages")
