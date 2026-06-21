"""FastAPI dependency functions for authentication and role checks."""

from __future__ import annotations

from dataclasses import dataclass

from fastapi import Depends, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from app.core.exceptions import AuthException, PermissionDeniedException
from app.core.security import decode_access_token
from app.db.mysql import get_db
from app.services.auth import get_user_by_id, is_token_blacklisted, user_to_info
from app.schemas.auth import UserInfo

bearer_scheme = HTTPBearer(auto_error=False)


@dataclass(frozen=True)
class CurrentUser:
    id: int
    username: str
    display_name: str
    roles: tuple[str, ...]
    token_jti: str
    token_exp: int

    @classmethod
    def from_user_info(cls, info: UserInfo, token_jti: str, token_exp: int) -> "CurrentUser":
        return cls(
            id=info.id,
            username=info.username,
            display_name=info.display_name,
            roles=tuple(role.code for role in info.roles),
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
    user_id = int(payload.get("sub", 0))
    user = get_user_by_id(db, user_id)
    if not user or not user.is_active:
        raise AuthException("user disabled or not found")
    info = user_to_info(user)
    current = CurrentUser.from_user_info(info, token_jti=jti, token_exp=int(payload["exp"]))
    request.state.user_id = current.id
    return current


def require_admin(current_user: CurrentUser = Depends(get_current_user)) -> CurrentUser:
    # Admin-only endpoint guard.
    if not current_user.is_admin:
        raise PermissionDeniedException("admin role required")
    return current_user
