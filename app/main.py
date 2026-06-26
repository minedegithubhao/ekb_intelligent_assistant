"""FastAPI application factory and global exception wiring."""

from __future__ import annotations

import logging

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.api.routers import api_router
from app.core.config import get_runtime_config
from app.core.exceptions import AppException
from app.core.logging import RequestLoggingMiddleware, setup_logging
from app.core.response import error_response

def create_app() -> FastAPI:
    runtime_config = get_runtime_config()
    logging_config = runtime_config.app.logging
    setup_logging(
        level=logging_config.level,
        log_dir=logging_config.dir,
        app_file=logging_config.app_file,
        error_file=logging_config.error_file,
        max_bytes=logging_config.max_bytes,
        backup_count=logging_config.backup_count,
    )

    # App factory keeps startup wiring in one place for tests and local runs.
    app = FastAPI(
        title=runtime_config.app.app.name,
        debug=runtime_config.app.app.debug,
        docs_url="/docs",
        openapi_url="/openapi.json",
    )

    cors = runtime_config.app.cors
    app.add_middleware(
        CORSMiddleware,
        allow_origins=cors.allow_origins,
        allow_credentials=cors.allow_credentials,
        allow_methods=cors.allow_methods,
        allow_headers=cors.allow_headers,
    )
    app.add_middleware(RequestLoggingMiddleware)

    register_exception_handlers(app)
    app.include_router(api_router, prefix=runtime_config.app.app.api_prefix)
    register_startup_hooks(app)
    return app


def register_startup_hooks(app: FastAPI) -> None:
    """Startup tasks that should not make app imports depend on external services."""

    logger = logging.getLogger("app.startup")

    @app.on_event("startup")
    def load_effective_config() -> None:
        try:
            from app.db.mysql import SessionLocal
            from app.services.retrieval_config import refresh_effective_retrieval_cache

            with SessionLocal() as db:
                refresh_effective_retrieval_cache(db)
        except Exception as exc:  # noqa: BLE001 - startup should still expose health diagnostics.
            logger.warning("effective retrieval config was not loaded from mysql: %s", exc)


def register_exception_handlers(app: FastAPI) -> None:
    """Converts all API errors to the agreed response shape."""

    logger = logging.getLogger("app.exception")

    @app.exception_handler(AppException)
    async def handle_app_exception(_: Request, exc: AppException) -> JSONResponse:
        return JSONResponse(
            status_code=exc.status_code,
            content=error_response(code=exc.code, message=exc.message),
        )

    @app.exception_handler(RequestValidationError)
    async def handle_validation_exception(_: Request, exc: RequestValidationError) -> JSONResponse:
        return JSONResponse(
            status_code=422,
            content=error_response(code=42200, message="request validation failed", data=exc.errors()),
        )

    @app.exception_handler(Exception)
    async def handle_unexpected_exception(request: Request, exc: Exception) -> JSONResponse:
        logger.exception("unexpected error path=%s", request.url.path)
        return JSONResponse(
            status_code=500,
            content=error_response(code=50000, message="internal server error"),
        )


app = create_app()
