"""Authentication service functions shared by API routes and dependencies."""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.core.exceptions import AuthException
from app.core.security import create_access_token, verify_password
from app.db.models.auth import User
from app.db.redis import exists as redis_exists
from app.db.redis import set_value
from app.schemas.auth import RoleInfo, TokenResponse, UserInfo


TOKEN_BLACKLIST_PREFIX = "auth:blacklist:"


def user_to_info(user: User) -> UserInfo:
    return UserInfo(
        id=user.id,
        username=user.username,
        display_name=user.display_name,
        email=user.email,
        roles=[RoleInfo(code=role.code, name=role.name) for role in user.roles if not role.is_deleted],
    )


def get_user_by_username(db: Session, username: str) -> User | None:
    stmt = (
        select(User)
        .options(selectinload(User.roles))
        .where(User.username == username, User.is_deleted.is_(False))
    )
    return db.execute(stmt).scalar_one_or_none()


def get_user_by_id(db: Session, user_id: int) -> User | None:
    stmt = (
        select(User)
        .options(selectinload(User.roles))
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


def create_login_response(user: User) -> TokenResponse:
    role_codes = [role.code for role in user.roles if not role.is_deleted]
    token, expires_at, _ = create_access_token(subject=str(user.id), username=user.username, roles=role_codes)
    return TokenResponse(access_token=token, expires_at=expires_at, user=user_to_info(user))


def blacklist_token(jti: str, exp: int) -> None:
    # Redis key expires when the original token would have expired.
    ttl = max(1, exp - int(datetime.now(UTC).timestamp()))
    set_value(f"{TOKEN_BLACKLIST_PREFIX}{jti}", "1", ttl_seconds=ttl)


def is_token_blacklisted(jti: str) -> bool:
    return redis_exists(f"{TOKEN_BLACKLIST_PREFIX}{jti}")
