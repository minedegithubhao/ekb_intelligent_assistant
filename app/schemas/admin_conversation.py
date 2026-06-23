"""Pydantic schemas for admin conversation management APIs."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel


class AdminConversationItem(BaseModel):
    conversation_id: int
    user_id: int
    username: str
    display_name: str
    title: str | None
    knowledge_base_type: str
    knowledge_base_name: str
    message_count: int
    last_message_at: datetime | None = None
    created_at: datetime


class AdminConversationStats(BaseModel):
    total_conversations: int
    total_messages: int
    total_users: int
    data_source: str = "演示数据"


class AdminConversationMessageItem(BaseModel):
    message_id: int
    conversation_id: int
    role: str
    content: str
    sources: list[dict] | None = None
    metadata: dict | None = None
    created_at: datetime
