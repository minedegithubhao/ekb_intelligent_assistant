"""Unified response helpers used by all JSON APIs."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class ApiResponse(BaseModel):
    code: int = 0
    message: str = "success"
    data: Any = Field(default_factory=dict)


class PageData(BaseModel):
    items: list[Any]
    total: int
    page: int
    page_size: int


def success_response(data: Any | None = None, message: str = "success") -> dict[str, Any]:
    # Keeps the API response shape stable for frontend integration.
    return ApiResponse(message=message, data={} if data is None else data).model_dump()


def page_response(
    items: list[Any],
    total: int,
    page: int,
    page_size: int,
    message: str = "success",
) -> dict[str, Any]:
    data = PageData(items=items, total=total, page=page, page_size=page_size)
    return success_response(data=data.model_dump(), message=message)


def error_response(code: int, message: str, data: Any | None = None) -> dict[str, Any]:
    return ApiResponse(code=code, message=message, data={} if data is None else data).model_dump()
