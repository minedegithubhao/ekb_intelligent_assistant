"""Pydantic schemas for user conversations and chat messages."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


class ConversationCreate(BaseModel):
    knowledge_base_type: str = Field(max_length=32)
    title: str | None = Field(default="新会话", max_length=255)


class ConversationInfo(BaseModel):
    conversation_id: int
    title: str
    knowledge_base_type: str
    last_message_at: datetime | None = None
    created_at: datetime
    updated_at: datetime


class ConversationMessageInfo(BaseModel):
    message_id: int
    conversation_id: int
    role: str
    content: str
    sources: list[dict[str, Any]] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime


class ConversationQuestionCreate(BaseModel):
    question: str = Field(min_length=1, max_length=8000)
    knowledge_base_type: str = Field(max_length=32)


class ConversationQuestionAnswer(BaseModel):
    message_id: int
    conversation_id: int
    answer: str
    knowledge_base_type: str
    sources: list[dict[str, Any]] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)
    hit_type: str = "none"
    need_human_transfer: bool = False
    created_at: datetime
