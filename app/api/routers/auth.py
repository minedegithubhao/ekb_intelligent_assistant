"""Authentication routes: login, current user, logout, and admin check."""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.api.deps import CurrentUser, get_current_user, require_admin
from app.core.response import success_response
from app.db.mysql import get_db
from app.schemas.auth import LoginRequest
from app.services.auth import authenticate_user, blacklist_token, create_login_response

router = APIRouter()


@router.post("/login")
def login(payload: LoginRequest, db: Session = Depends(get_db)) -> dict:
    # Password verification and token creation live in the auth service.
    user = authenticate_user(db, payload.username, payload.password)
    token = create_login_response(user)
    return success_response(token.model_dump(mode="json"))


@router.get("/me")
def me(current_user: CurrentUser = Depends(get_current_user)) -> dict:
    return success_response(
        {
            "id": current_user.id,
            "username": current_user.username,
            "display_name": current_user.display_name,
            "roles": list(current_user.roles),
            "is_admin": current_user.is_admin,
        }
    )


@router.post("/logout")
def logout(current_user: CurrentUser = Depends(get_current_user)) -> dict:
    # Logout uses a Redis blacklist so the current token stops working immediately.
    blacklist_token(current_user.token_jti, current_user.token_exp)
    return success_response({"revoked": True})


@router.get("/admin-check")
def admin_check(current_user: CurrentUser = Depends(require_admin)) -> dict:
    return success_response({"username": current_user.username, "roles": list(current_user.roles)})
