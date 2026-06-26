"""User, role, and user-role association ORM models."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import Boolean, Column, DateTime, ForeignKey, String, Table, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.models.base import Base, BaseModel


user_roles = Table(
    # Many-to-many mapping so a user can hold multiple roles later if needed.
    "user_roles",
    Base.metadata,
    Column("user_id", ForeignKey("users.id", ondelete="CASCADE"), primary_key=True),
    Column("role_id", ForeignKey("roles.id", ondelete="CASCADE"), primary_key=True),
    UniqueConstraint("user_id", "role_id", name="uq_user_roles_user_role"),
)


class Role(BaseModel):
    __tablename__ = "roles"

    code: Mapped[str] = mapped_column(String(64), nullable=False, unique=True, index=True)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    is_system: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default="1")

    users: Mapped[list["User"]] = relationship(
        secondary=user_roles,
        back_populates="roles",
        lazy="selectin",
    )


class User(BaseModel):
    __tablename__ = "users"

    username: Mapped[str] = mapped_column(String(64), nullable=False, unique=True, index=True)
    name: Mapped[str | None] = mapped_column(String(128), nullable=True)
    display_name: Mapped[str] = mapped_column(String(128), nullable=False)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    email: Mapped[str | None] = mapped_column(String(255), nullable=True)
    department: Mapped[str | None] = mapped_column(String(128), nullable=True)
    category: Mapped[str | None] = mapped_column(String(64), nullable=True)
    user_type: Mapped[str] = mapped_column(String(32), nullable=False, default="user", server_default="user")
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default="1")
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    roles: Mapped[list[Role]] = relationship(
        secondary=user_roles,
        back_populates="users",
        lazy="selectin",
    )
    question_categories: Mapped[list["UserQuestionCategory"]] = relationship(
        back_populates="user",
        cascade="all, delete-orphan",
        lazy="selectin",
    )


class UserSession(BaseModel):
    __tablename__ = "user_sessions"

    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    token_jti: Mapped[str] = mapped_column(String(128), nullable=False, unique=True, index=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="active", server_default="active")
    login_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    logout_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    ip_address: Mapped[str | None] = mapped_column(String(64), nullable=True)
    user_agent: Mapped[str | None] = mapped_column(String(512), nullable=True)


class UserQuestionCategory(BaseModel):
    __tablename__ = "user_question_categories"
    __table_args__ = (UniqueConstraint("user_id", "category_code", name="uq_user_question_category"),)

    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    category_code: Mapped[str] = mapped_column(String(64), nullable=False)
    category_name: Mapped[str] = mapped_column(String(128), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)

    user: Mapped[User] = relationship(back_populates="question_categories")
