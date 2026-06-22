"""Schemas for admin configuration APIs."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


class ConfigVersionCreate(BaseModel):
    config: dict[str, Any]
    description: str | None = Field(default=None, max_length=500)
    activate: bool = False


class ConfigVersionInfo(BaseModel):
    id: int
    config_key: str
    version_no: int
    status: str
    description: str | None = None
    created_by: int | None = None
    activated_by: int | None = None
    activated_at: datetime | None = None
    created_at: datetime
    updated_at: datetime


class ConfigVersionDetail(ConfigVersionInfo):
    config: dict[str, Any]
