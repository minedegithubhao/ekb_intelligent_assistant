"""Pydantic request and response schemas for auth APIs."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field


class LoginRequest(BaseModel):
    username: str = Field(min_length=1, max_length=64)
    password: str = Field(min_length=1, max_length=128)
    login_type: str | None = Field(default=None, max_length=32)


class RoleInfo(BaseModel):
    code: str
    name: str


class UserInfo(BaseModel):
    id: int
    username: str
    name: str | None = None
    display_name: str
    email: str | None = None
    department: str | None = None
    category: str | None = None
    user_type: str = "user"
    roles: list[RoleInfo]
    question_categories: list[str] = Field(default_factory=list)
    question_category_names: list[str] = Field(default_factory=list)


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_at: datetime
    user: UserInfo
