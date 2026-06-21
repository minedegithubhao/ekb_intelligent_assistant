"""Read, cache, create, and activate hot retrieval parameters stored in MySQL."""

from __future__ import annotations

from threading import RLock
from typing import Any

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.core.config import get_runtime_config
from app.core.exceptions import ConfigException
from app.db.models.retrieval_config import RetrievalHotConfig as RetrievalHotConfigModel
from app.schemas.retrieval_config import (
    RetrievalHotConfigCreate,
    RetrievalHotConfigRead,
    RetrievalHotConfigValues,
)

DEFAULT_RETRIEVAL_CONFIG_NAME = "default"
HOT_CONFIG_FIELDS = tuple(RetrievalHotConfigValues.model_fields.keys())

_cache_lock = RLock()
_hot_config_cache: RetrievalHotConfigRead | None = None


def _query_active_config_row(db: Session) -> RetrievalHotConfigModel | None:
    stmt = select(RetrievalHotConfigModel).where(
        RetrievalHotConfigModel.is_enabled.is_(True),
    ).order_by(
        RetrievalHotConfigModel.created_at.desc(),
        RetrievalHotConfigModel.id.desc(),
    )
    return db.execute(stmt).scalars().first()


def _row_to_read_model(row: RetrievalHotConfigModel) -> RetrievalHotConfigRead:
    values = {field: getattr(row, field) for field in HOT_CONFIG_FIELDS}
    return RetrievalHotConfigRead(
        id=row.id,
        config_name=row.config_name,
        is_enabled=row.is_enabled,
        created_by=row.created_by,
        created_at=row.created_at,
        **values,
    )


def clear_retrieval_hot_config_cache() -> None:
    """Clear cached hot config after manual maintenance or test setup."""

    global _hot_config_cache
    with _cache_lock:
        _hot_config_cache = None


def get_retrieval_hot_config(
    db: Session,
    *,
    force_reload: bool = False,
) -> RetrievalHotConfigRead:
    """Return the globally enabled hot config from memory first, then MySQL."""

    global _hot_config_cache
    if not force_reload:
        with _cache_lock:
            if _hot_config_cache is not None:
                return _hot_config_cache

    row = _query_active_config_row(db)
    if row is None or not row.is_enabled:
        raise ConfigException("enabled retrieval hot config not found")

    config = _row_to_read_model(row)
    with _cache_lock:
        _hot_config_cache = config
    return config


def reload_retrieval_hot_config(db: Session) -> RetrievalHotConfigRead:
    """Force reload from MySQL and atomically replace the in-memory snapshot."""

    return get_retrieval_hot_config(db, force_reload=True)


def get_retrieval_runtime_config(db: Session) -> dict[str, Any]:
    """Merge static YAML retrieval settings with hot MySQL parameters."""

    static_config = get_runtime_config().retrieval.model_dump()
    hot_config = get_retrieval_hot_config(db).model_dump(
        exclude={"id", "config_name", "is_enabled", "created_by", "created_at"}
    )
    return {**static_config, **hot_config}


def create_retrieval_hot_config(
    db: Session,
    payload: RetrievalHotConfigCreate | dict[str, Any],
    *,
    config_name: str = DEFAULT_RETRIEVAL_CONFIG_NAME,
    created_by: int | None = None,
) -> RetrievalHotConfigRead:
    """Validate and append a disabled config version.

    Activation is intentionally separate so adding history never changes the
    running retrieval strategy by accident.
    """

    create_payload = RetrievalHotConfigCreate.model_validate(payload)
    try:
        row = RetrievalHotConfigModel(config_name=config_name, created_by=created_by)
        for field in HOT_CONFIG_FIELDS:
            setattr(row, field, getattr(create_payload, field))
        row.is_enabled = False
        db.add(row)

        db.commit()
        db.refresh(row)
    except Exception:
        db.rollback()
        raise

    return _row_to_read_model(row)


def enable_retrieval_hot_config(db: Session, config_id: int) -> RetrievalHotConfigRead:
    """Enable one config row and disable every other config row globally."""

    global _hot_config_cache
    row = db.get(RetrievalHotConfigModel, config_id)
    if row is None:
        raise ConfigException(f"retrieval hot config not found: {config_id}")

    try:
        # The business rule is global: one enabled config across all names.
        db.execute(update(RetrievalHotConfigModel).values(is_enabled=False))
        row.is_enabled = True
        db.commit()
        db.refresh(row)
    except Exception:
        db.rollback()
        raise

    config = _row_to_read_model(row)
    with _cache_lock:
        _hot_config_cache = config
    return config
