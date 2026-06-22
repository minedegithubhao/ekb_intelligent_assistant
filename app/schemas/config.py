"""Schemas for admin dashboard hot configuration APIs."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class DashboardConfigSave(BaseModel):
    config: dict[str, Any]
    description: str | None = Field(default=None, max_length=500)
    activate: bool = True
