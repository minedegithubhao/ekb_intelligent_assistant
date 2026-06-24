"""Schemas for JSON vector ingestion APIs."""

from __future__ import annotations

from pydantic import BaseModel


class JsonVectorIngestFailedItem(BaseModel):
    index: int
    pk: str | None = None
    reason: str


class JsonVectorIngestResult(BaseModel):
    file_name: str
    record_type: str
    collection_name: str
    kb_versions: list[str]
    total_count: int
    success_count: int
    failed_count: int
    failed_items: list[JsonVectorIngestFailedItem]


class JsonVectorIngestBatchResult(BaseModel):
    record_type: str
    collection_name: str
    kb_versions: list[str]
    total_files: int
    success_files: int
    failed_files: int
    total_count: int
    success_count: int
    failed_count: int
    file_results: list[JsonVectorIngestResult]
