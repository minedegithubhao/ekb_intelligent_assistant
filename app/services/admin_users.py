"""Administrator user management service."""

from __future__ import annotations

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session, selectinload

from app.core.exceptions import BadRequestException, NotFoundException
from app.core.security import hash_password
from app.db.models.auth import Role, User, UserQuestionCategory
from app.schemas.admin_users import AdminUserCreate, AdminUserInfo, AdminUserUpdate


USER_CATEGORY_OPTIONS = {"merchant", "enterprise", "individual", "personal"}
QUESTION_CATEGORY_MAP = {
    "merchant": ("enterprise_shop", "企业店规则", "企业店相关规则问题"),
    "enterprise": ("enterprise_shop", "企业店规则", "企业店相关规则问题"),
    "individual": ("individual_shop", "个人个体店规则", "个人/个体店相关规则问题"),
    "personal": ("individual_shop", "个人个体店规则", "个人/个体店相关规则问题"),
}
ADMIN_QUESTION_CATEGORIES = [
    ("enterprise_shop", "企业店规则", "企业店相关规则问题"),
    ("individual_shop", "个人个体店规则", "个人/个体店相关规则问题"),
]


def _status_to_active(status: str) -> bool:
    if status not in {"enabled", "disabled"}:
        raise BadRequestException("invalid user status")
    return status == "enabled"


def _normalize_role(role: str) -> str:
    if role not in {"admin", "user"}:
        raise BadRequestException("invalid user role")
    return role


def _normalize_category(role: str, category: str | None) -> str:
    if role == "admin":
        return "admin"
    normalized = category or "merchant"
    if normalized not in USER_CATEGORY_OPTIONS:
        raise BadRequestException("invalid user category")
    return normalized


def _knowledge_base_info(category: str | None) -> tuple[str, str]:
    if category in {"merchant", "enterprise"}:
        return "enterprise", "企业知识库"
    if category in {"individual", "personal"}:
        return "personal", "个人知识库"
    return "enterprise", "企业知识库"


def _get_role(db: Session, role_code: str) -> Role:
    role = db.execute(
        select(Role).where(Role.code == role_code, Role.is_deleted.is_(False))
    ).scalar_one_or_none()
    if not role:
        raise BadRequestException("role does not exist")
    return role


def _get_user(db: Session, user_id: int) -> User:
    user = db.execute(
        select(User)
        .options(selectinload(User.roles), selectinload(User.question_categories))
        .where(User.id == user_id, User.is_deleted.is_(False))
    ).scalar_one_or_none()
    if not user:
        raise NotFoundException("user not found")
    return user


def _sync_question_categories(user: User, category: str) -> None:
    user.question_categories.clear()
    if category == "admin":
        entries = ADMIN_QUESTION_CATEGORIES
    else:
        entries = [QUESTION_CATEGORY_MAP[category]]
    for code, name, description in entries:
        user.question_categories.append(
            UserQuestionCategory(category_code=code, category_name=name, description=description)
        )


def user_to_admin_info(user: User) -> AdminUserInfo:
    role_code = next((role.code for role in user.roles if not role.is_deleted), "user")
    knowledge_base_type, knowledge_base_name = _knowledge_base_info(user.category)
    return AdminUserInfo(
        userId=user.id,
        username=user.username,
        name=user.name,
        displayName=user.display_name,
        email=user.email,
        department=user.department,
        role=role_code,
        status="enabled" if user.is_active else "disabled",
        category=user.category,
        knowledgeBaseType=knowledge_base_type,
        knowledgeBaseName=knowledge_base_name,
        createdAt=user.created_at,
        updatedAt=user.updated_at,
    )


def list_admin_users(
    db: Session,
    keyword: str | None = None,
    role: str | None = None,
    status: str | None = None,
    page: int = 1,
    page_size: int = 100,
) -> tuple[list[AdminUserInfo], int]:
    filters = [User.is_deleted.is_(False)]
    if keyword:
        like_keyword = f"%{keyword}%"
        filters.append(or_(User.username.like(like_keyword), User.display_name.like(like_keyword), User.name.like(like_keyword)))
    if role:
        filters.append(User.roles.any(Role.code == _normalize_role(role)))
    if status:
        filters.append(User.is_active.is_(_status_to_active(status)))

    total = db.execute(select(func.count()).select_from(User).where(*filters)).scalar_one()
    users = db.execute(
        select(User)
        .options(selectinload(User.roles), selectinload(User.question_categories))
        .where(*filters)
        .order_by(User.id.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    ).scalars().all()
    return [user_to_admin_info(user) for user in users], int(total)


def create_admin_user(db: Session, payload: AdminUserCreate) -> AdminUserInfo:
    role_code = _normalize_role(payload.role)
    category = _normalize_category(role_code, payload.category)
    existing = db.execute(select(User).where(User.username == payload.username)).scalar_one_or_none()
    if existing:
        raise BadRequestException("username already exists")

    user = User(
        username=payload.username,
        name=payload.name or payload.displayName,
        display_name=payload.displayName,
        password_hash=hash_password(payload.password),
        email=payload.email,
        department=payload.department,
        category=category,
        user_type=role_code,
        is_active=_status_to_active(payload.status),
    )
    user.roles = [_get_role(db, role_code)]
    _sync_question_categories(user, category)
    db.add(user)
    db.flush()
    db.refresh(user)
    return user_to_admin_info(_get_user(db, user.id))


def update_admin_user(db: Session, user_id: int, payload: AdminUserUpdate, current_user_id: int) -> AdminUserInfo:
    user = _get_user(db, user_id)
    update_data = payload.model_dump(exclude_unset=True)
    role_code = _normalize_role(update_data.get("role", next((role.code for role in user.roles if not role.is_deleted), "user")))
    category = _normalize_category(role_code, update_data.get("category", user.category))

    if user.id == current_user_id and (role_code != "admin" or update_data.get("status") == "disabled"):
        raise BadRequestException("cannot remove or disable current administrator")

    if "password" in update_data and update_data["password"]:
        user.password_hash = hash_password(update_data["password"])
    if "displayName" in update_data and update_data["displayName"]:
        user.display_name = update_data["displayName"]
    if "name" in update_data:
        user.name = update_data["name"] or user.display_name
    if "email" in update_data:
        user.email = update_data["email"]
    if "department" in update_data:
        user.department = update_data["department"]
    if "status" in update_data:
        user.is_active = _status_to_active(update_data["status"])

    user.category = category
    user.user_type = role_code
    user.roles = [_get_role(db, role_code)]
    _sync_question_categories(user, category)
    db.flush()
    db.refresh(user)
    return user_to_admin_info(_get_user(db, user.id))


def disable_admin_user(db: Session, user_id: int, current_user_id: int) -> AdminUserInfo:
    if user_id == current_user_id:
        raise BadRequestException("cannot disable current administrator")
    user = _get_user(db, user_id)
    user.is_active = False
    db.flush()
    db.refresh(user)
    return user_to_admin_info(user)
