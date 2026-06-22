"""Configuration version ORM models."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, ForeignKey, JSON, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db.models.base import BaseModel


class ConfigVersion(BaseModel):
    __tablename__ = "config_versions"
    __table_args__ = (UniqueConstraint("config_key", "version_no", name="uq_config_version_key_no"),)

    config_key: Mapped[str] = mapped_column(String(64), nullable=False, index=True, default="retrieval")
    version_no: Mapped[int] = mapped_column(nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="draft", server_default="draft", index=True)
    config_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_by: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    activated_by: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    activated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
