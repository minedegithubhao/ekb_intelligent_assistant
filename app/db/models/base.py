"""Shared SQLAlchemy base classes and common model fields."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import BigInteger, Boolean, DateTime, func
from sqlalchemy.orm import DeclarativeBase, Mapped, declared_attr, mapped_column


class Base(DeclarativeBase):
    pass


class IdMixin:
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )


class SoftDeleteMixin:
    is_deleted: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default="0")


class BaseModel(Base, IdMixin, TimestampMixin, SoftDeleteMixin):
    """Base for business tables: id, timestamps, and logical delete flag."""

    __abstract__ = True

    @declared_attr.directive
    def __tablename__(cls) -> str:
        name = cls.__name__
        chars: list[str] = []
        for index, char in enumerate(name):
            if char.isupper() and index > 0:
                chars.append("_")
            chars.append(char.lower())
        return "".join(chars)
