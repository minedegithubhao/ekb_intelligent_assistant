"""Schemas for admin retrieval testing APIs."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class AdminRetrievalTestRequest(BaseModel):
    question: str = Field(min_length=1, max_length=2000)
    knowledge_base_type: Literal["enterprise", "personal"] = "enterprise"
    kb_version: str | None = Field(default=None, max_length=64)
    include_answer: bool = True

