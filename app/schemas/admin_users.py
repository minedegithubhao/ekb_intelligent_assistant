"""Schemas for administrator user management APIs."""

from __future__ import annotations

import re
from datetime import datetime

from pydantic import BaseModel, Field, field_validator


USERNAME_PATTERN = re.compile(r"^[A-Za-z0-9]+$")


class AdminUserCreate(BaseModel):
    username: str = Field(min_length=1, max_length=64)
    password: str = Field(min_length=6, max_length=128)
    displayName: str = Field(min_length=1, max_length=128)
    name: str | None = Field(default=None, max_length=128)
    email: str | None = Field(default=None, max_length=255)
    department: str | None = Field(default=None, max_length=128)
    role: str = Field(default="user", max_length=32)
    status: str = Field(default="enabled", max_length=32)
    category: str = Field(default="merchant", max_length=64)

    @field_validator("username")
    @classmethod
    def validate_username(cls, value: str) -> str:
        if not USERNAME_PATTERN.fullmatch(value):
            raise ValueError("username can only contain English letters and numbers")
        return value


class AdminUserUpdate(BaseModel):
    password: str | None = Field(default=None, min_length=6, max_length=128)
    displayName: str | None = Field(default=None, min_length=1, max_length=128)
    name: str | None = Field(default=None, max_length=128)
    email: str | None = Field(default=None, max_length=255)
    department: str | None = Field(default=None, max_length=128)
    role: str | None = Field(default=None, max_length=32)
    status: str | None = Field(default=None, max_length=32)
    category: str | None = Field(default=None, max_length=64)


class AdminUserStatusUpdate(BaseModel):
    status: str = Field(max_length=32)


class AdminUserInfo(BaseModel):
    userId: int
    username: str
    name: str | None = None
    displayName: str
    email: str | None = None
    department: str | None = None
    role: str
    status: str
    category: str | None = None
    knowledgeBaseType: str
    knowledgeBaseName: str
    createdAt: datetime
    updatedAt: datetime
