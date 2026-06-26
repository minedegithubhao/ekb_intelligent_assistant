"""Schemas for offline ingestion admin APIs."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, model_validator


class OfflineIngestionConfigEditable(BaseModel):
    doc_parent_chunk_size: int = Field(gt=0)
    doc_child_chunk_size: int = Field(gt=0)
    doc_child_chunk_overlap: int = Field(ge=0)
    table_split_strategy: str = Field(default="row", max_length=32)
    table_header_required: bool = True
    table_row_max_chars: int = Field(gt=0)

    @model_validator(mode="after")
    def validate_relationships(self) -> "OfflineIngestionConfigEditable":
        if self.doc_child_chunk_overlap >= self.doc_child_chunk_size:
            raise ValueError("doc_child_chunk_overlap must be less than doc_child_chunk_size")
        if self.table_split_strategy != "row":
            raise ValueError("table_split_strategy only supports row")
        return self


class OfflineIngestionConfigCreate(OfflineIngestionConfigEditable):
    config_name: str = Field(default="default", min_length=1, max_length=64)


class OfflineIngestionConfigInfo(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    config_name: str
    is_enabled: bool
    status: str
    created_by: int | None = None
    source_data_root: str
    clean_markdown_dir: str
    index_csv_name: str
    faq_csv_dir: str
    doc_parent_chunk_size: int
    doc_child_chunk_size: int
    doc_child_chunk_overlap: int
    table_split_strategy: str
    table_header_required: bool
    table_row_max_chars: int
    rule_metadata_filter_keys: list[str]
    doc_collection_name: str
    faq_collection_name: str
    dense_vector_dim: int
    sparse_vector_enabled: bool
    embedding_batch_size: int
    milvus_insert_batch_size: int
    scope_enum: dict[str, str]
    created_at: datetime
    updated_at: datetime


class OfflineIngestionTaskCreate(BaseModel):
    version_description: str | None = Field(default=None, max_length=255)
    auto_publish: bool = False
    source_data_root: str | None = Field(default=None, max_length=512)
    clean_markdown_dir: str | None = Field(default=None, max_length=128)
    index_csv_name: str | None = Field(default=None, max_length=128)
    faq_csv_dir: str | None = Field(default=None, max_length=128)


class OfflineUploadTaskCreate(BaseModel):
    kb_version: str = Field(min_length=1, max_length=128)
    scope: str = Field(min_length=1, max_length=64)
    version_description: str | None = Field(default=None, max_length=255)
    auto_publish: bool = False


class OfflineIngestionTaskInfo(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    task_id: str
    status: str
    progress_percent: int
    current_stage: str | None = None
    kb_version: str | None = None
    config_id: int
    ingest_type: str = "mixed"
    upload_root: str | None = None
    source_data_root: str
    clean_markdown_dir: str
    index_csv_name: str
    faq_csv_dir: str
    auto_publish: bool
    version_description: str | None = None
    document_count: int
    parent_chunk_count: int
    child_chunk_count: int
    faq_count: int
    error_message: str | None = None
    created_by: int | None = None
    started_at: datetime | None = None
    finished_at: datetime | None = None
    created_at: datetime
    updated_at: datetime
