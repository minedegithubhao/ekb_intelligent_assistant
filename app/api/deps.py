"""FastAPI dependency functions for authentication and role checks."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime

from fastapi import Depends, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from app.core.exceptions import AuthException, PermissionDeniedException
from app.core.security import decode_access_token
from app.db.mysql import get_db
from app.schemas.auth import UserInfo
from app.services.auth import cache_user_info, get_user_by_id, is_session_active, is_token_blacklisted, user_to_info

bearer_scheme = HTTPBearer(auto_error=False)


@dataclass(frozen=True)
class CurrentUser:
    id: int
    username: str
    name: str | None
    display_name: str
    department: str | None
    category: str | None
    user_type: str
    roles: tuple[str, ...]
    question_categories: tuple[str, ...]
    question_category_names: tuple[str, ...]
    token_jti: str
    token_exp: int

    @classmethod
    def from_user_info(cls, info: UserInfo, token_jti: str, token_exp: int) -> "CurrentUser":
        return cls(
            id=info.id,
            username=info.username,
            name=info.name,
            display_name=info.display_name,
            department=info.department,
            category=info.category,
            user_type=info.user_type,
            roles=tuple(role.code for role in info.roles),
            question_categories=tuple(info.question_categories),
            question_category_names=tuple(info.question_category_names),
            token_jti=token_jti,
            token_exp=token_exp,
        )

    @property
    def is_admin(self) -> bool:
        return "admin" in self.roles


def get_current_user(
    request: Request,
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
    db: Session = Depends(get_db),
) -> CurrentUser:
    # Shared dependency for all protected endpoints.
    if credentials is None or credentials.scheme.lower() != "bearer":
        raise AuthException("missing bearer token")
    payload = decode_access_token(credentials.credentials)
    jti = str(payload.get("jti", ""))
    if not jti or is_token_blacklisted(jti):
        raise AuthException("token revoked")
    if not is_session_active(db, jti):
        raise AuthException("session expired or revoked")
    user_id = int(payload.get("sub", 0))
    user = get_user_by_id(db, user_id)
    if not user or not user.is_active:
        raise AuthException("user disabled or not found")
    info = user_to_info(user)
    cache_user_info(info, jti=jti, ttl_seconds=max(1, int(payload["exp"]) - int(datetime.now(UTC).timestamp())))
    current = CurrentUser.from_user_info(info, token_jti=jti, token_exp=int(payload["exp"]))
    request.state.user_id = current.id
    return current


def require_admin(current_user: CurrentUser = Depends(get_current_user)) -> CurrentUser:
    # Admin-only endpoint guard.
    if not current_user.is_admin:
        raise PermissionDeniedException("admin role required")
    return current_user
