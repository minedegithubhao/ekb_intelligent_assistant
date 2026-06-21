"""Pydantic request and response schemas for auth APIs."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field


class LoginRequest(BaseModel):
    username: str = Field(min_length=1, max_length=64)
    password: str = Field(min_length=1, max_length=128)


class RoleInfo(BaseModel):
    code: str
    name: str


class UserInfo(BaseModel):
    id: int
    username: str
    display_name: str
    email: str | None = None
    roles: list[RoleInfo]


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_at: datetime
    user: UserInfo
