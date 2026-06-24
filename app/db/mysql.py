"""MySQL engine, session dependency, and connectivity helpers."""

from __future__ import annotations

import logging
from collections.abc import Generator

from sqlalchemy import create_engine, text
from sqlalchemy import event
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import get_runtime_config
from app.core.exceptions import ServiceUnavailableException
from app.db.models import Base

logger = logging.getLogger(__name__)

mysql_config = get_runtime_config().app.database.mysql

engine = create_engine(
    mysql_config.sqlalchemy_url,
    echo=mysql_config.echo,
    pool_pre_ping=True,
    pool_size=mysql_config.pool_size,
    max_overflow=mysql_config.max_overflow,
    pool_recycle=mysql_config.pool_recycle_seconds,
)


@event.listens_for(engine, "connect")
def _set_mysql_session_options(dbapi_connection, connection_record) -> None:
    cursor = dbapi_connection.cursor()
    try:
        cursor.execute("SET time_zone = '+08:00'")
        cursor.execute("SET NAMES utf8mb4")
    finally:
        cursor.close()


SessionLocal = sessionmaker(bind=engine, autocommit=False, autoflush=False, expire_on_commit=False)


def get_db() -> Generator[Session, None, None]:
    # FastAPI dependency: commits on success, rolls back on exception.
    db = SessionLocal()
    try:
        yield db
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def ping_mysql() -> dict[str, str]:
    # Health check used by /api/health/dependencies.
    try:
        with engine.connect() as conn:
            version = conn.execute(text("select version()")).scalar_one()
            database = conn.execute(text("select database()")).scalar_one()
            return {"status": "ok", "version": str(version), "database": str(database)}
    except Exception as exc:
        logger.exception("mysql ping failed")
        raise ServiceUnavailableException("mysql unavailable") from exc


def create_all_tables() -> None:
    Base.metadata.create_all(bind=engine)
