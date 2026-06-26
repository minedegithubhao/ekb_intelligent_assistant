"""Authentication service functions shared by API routes and dependencies."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.core.exceptions import AuthException
from app.core.security import create_access_token, verify_password
from app.db.models.auth import User, UserSession
from app.db.redis import exists as redis_exists
from app.db.redis import get_value
from app.db.redis import set_value
from app.schemas.auth import RoleInfo, TokenResponse, UserInfo


TOKEN_BLACKLIST_PREFIX = "auth:blacklist:"
USER_CACHE_PREFIX = "auth:user:"
TOKEN_USER_PREFIX = "auth:token:"


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def user_to_info(user: User) -> UserInfo:
    question_categories = [item for item in user.question_categories if not item.is_deleted]
    return UserInfo(
        id=user.id,
        username=user.username,
        name=user.name,
        display_name=user.display_name,
        email=user.email,
        department=user.department,
        category=user.category,
        user_type=user.user_type,
        roles=[RoleInfo(code=role.code, name=role.name) for role in user.roles if not role.is_deleted],
        question_categories=[item.category_code for item in question_categories],
        question_category_names=[item.category_name for item in question_categories],
    )


def get_user_by_username(db: Session, username: str) -> User | None:
    stmt = (
        select(User)
        .options(selectinload(User.roles), selectinload(User.question_categories))
        .where(User.username == username, User.is_deleted.is_(False))
    )
    return db.execute(stmt).scalar_one_or_none()


def get_user_by_id(db: Session, user_id: int) -> User | None:
    stmt = (
        select(User)
        .options(selectinload(User.roles), selectinload(User.question_categories))
        .where(User.id == user_id, User.is_deleted.is_(False))
    )
    return db.execute(stmt).scalar_one_or_none()


def authenticate_user(db: Session, username: str, password: str) -> User:
    # Central place for password verification and disabled-user checks.
    user = get_user_by_username(db, username)
    if not user or not user.is_active or not verify_password(password, user.password_hash):
        raise AuthException("invalid username or password")
    user.last_login_at = datetime.now(UTC)
    return user


def create_login_response(
    db: Session,
    user: User,
    ip_address: str | None = None,
    user_agent: str | None = None,
) -> TokenResponse:
    role_codes = [role.code for role in user.roles if not role.is_deleted]
    token, expires_at, jti = create_access_token(subject=str(user.id), username=user.username, roles=role_codes)
    session = UserSession(
        user_id=user.id,
        token_jti=jti,
        status="active",
        login_at=datetime.now(UTC),
        expires_at=expires_at,
        ip_address=ip_address,
        user_agent=user_agent,
    )
    db.add(session)
    info = user_to_info(user)
    ttl_seconds = max(1, int((expires_at - datetime.now(UTC)).total_seconds()))
    cache_user_info(info, jti=jti, ttl_seconds=ttl_seconds)
    return TokenResponse(access_token=token, expires_at=expires_at, user=info)


def cache_user_info(info: UserInfo, jti: str | None = None, ttl_seconds: int | None = None) -> None:
    payload = json.dumps(info.model_dump(mode="json"), ensure_ascii=False)
    set_value(f"{USER_CACHE_PREFIX}{info.id}", payload, ttl_seconds=ttl_seconds)
    if jti:
        set_value(f"{TOKEN_USER_PREFIX}{jti}", str(info.id), ttl_seconds=ttl_seconds)


def get_cached_user_info(user_id: int) -> dict[str, Any] | None:
    raw = get_value(f"{USER_CACHE_PREFIX}{user_id}")
    if not raw:
        return None
    try:
        loaded = json.loads(raw)
    except json.JSONDecodeError:
        return None
    return loaded if isinstance(loaded, dict) else None


def is_session_active(db: Session, token_jti: str) -> bool:
    session = db.execute(
        select(UserSession).where(
            UserSession.token_jti == token_jti,
            UserSession.is_deleted.is_(False),
        )
    ).scalar_one_or_none()
    if not session:
        return False
    if session.status != "active":
        return False
    if _as_utc(session.expires_at) < datetime.now(UTC):
        session.status = "expired"
        return False
    return True


def revoke_session(db: Session, token_jti: str) -> None:
    session = db.execute(
        select(UserSession).where(
            UserSession.token_jti == token_jti,
            UserSession.is_deleted.is_(False),
        )
    ).scalar_one_or_none()
    if session:
        session.status = "revoked"
        session.logout_at = datetime.now(UTC)


def blacklist_token(jti: str, exp: int) -> None:
    # Redis key expires when the original token would have expired.
    ttl = max(1, exp - int(datetime.now(UTC).timestamp()))
    set_value(f"{TOKEN_BLACKLIST_PREFIX}{jti}", "1", ttl_seconds=ttl)


def is_token_blacklisted(jti: str) -> bool:
    return redis_exists(f"{TOKEN_BLACKLIST_PREFIX}{jti}")
