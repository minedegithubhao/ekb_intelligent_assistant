"""Authentication routes: login, current user, logout, and admin check."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from sqlalchemy.orm import Session

from app.api.deps import CurrentUser, get_current_user, require_admin
from app.core.exceptions import PermissionDeniedException
from app.core.response import success_response
from app.db.mysql import get_db
from app.schemas.auth import LoginRequest
from app.services.auth import authenticate_user, blacklist_token, create_login_response, revoke_session

router = APIRouter()


@router.post("/login")
def login(payload: LoginRequest, request: Request, db: Session = Depends(get_db)) -> dict:
    # Password verification and token creation live in the auth service.
    user = authenticate_user(db, payload.username, payload.password)
    if payload.login_type == "admin" and "admin" not in {role.code for role in user.roles if not role.is_deleted}:
        raise PermissionDeniedException("admin role required")
    token = create_login_response(
        db,
        user,
        ip_address=request.client.host if request.client else None,
        user_agent=(request.headers.get("user-agent") or "")[:512],
    )
    return success_response(token.model_dump(mode="json"))


@router.get("/me")
def me(current_user: CurrentUser = Depends(get_current_user)) -> dict:
    return success_response(
        {
            "id": current_user.id,
            "username": current_user.username,
            "name": current_user.name,
            "display_name": current_user.display_name,
            "department": current_user.department,
            "category": current_user.category,
            "user_type": current_user.user_type,
            "roles": list(current_user.roles),
            "is_admin": current_user.is_admin,
            "question_categories": list(current_user.question_categories),
            "question_category_names": list(current_user.question_category_names),
        }
    )


@router.post("/logout")
def logout(current_user: CurrentUser = Depends(get_current_user), db: Session = Depends(get_db)) -> dict:
    # Logout uses a Redis blacklist so the current token stops working immediately.
    blacklist_token(current_user.token_jti, current_user.token_exp)
    revoke_session(db, current_user.token_jti)
    return success_response({"revoked": True})


@router.get("/admin-check")
def admin_check(current_user: CurrentUser = Depends(require_admin)) -> dict:
    return success_response({"username": current_user.username, "roles": list(current_user.roles)})
