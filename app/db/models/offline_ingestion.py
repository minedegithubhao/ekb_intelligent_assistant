"""Offline ingestion ORM models."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import BigInteger, Boolean, DateTime, Integer, JSON, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.models.base import Base


class OfflineIngestionConfig(Base):
    __tablename__ = "offline_ingestion_configs"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    config_name: Mapped[str] = mapped_column(String(64), nullable=False)
    is_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default="1", index=True)
    created_by: Mapped[int | None] = mapped_column(BigInteger, nullable=True)

    source_data_root: Mapped[str] = mapped_column(String(512), nullable=False)
    clean_markdown_dir: Mapped[str] = mapped_column(String(128), nullable=False)
    index_csv_name: Mapped[str] = mapped_column(String(128), nullable=False)
    faq_csv_dir: Mapped[str] = mapped_column(String(128), nullable=False)
    doc_parent_chunk_size: Mapped[int] = mapped_column(Integer, nullable=False)
    doc_child_chunk_size: Mapped[int] = mapped_column(Integer, nullable=False)
    doc_child_chunk_overlap: Mapped[int] = mapped_column(Integer, nullable=False)
    table_split_strategy: Mapped[str] = mapped_column(String(32), nullable=False)
    table_header_required: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default="1")
    table_row_max_chars: Mapped[int] = mapped_column(Integer, nullable=False)
    rule_metadata_filter_keys: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    doc_collection_name: Mapped[str] = mapped_column(String(128), nullable=False)
    faq_collection_name: Mapped[str] = mapped_column(String(128), nullable=False)
    dense_vector_dim: Mapped[int] = mapped_column(Integer, nullable=False)
    sparse_vector_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default="1")
    embedding_batch_size: Mapped[int] = mapped_column(Integer, nullable=False)
    milvus_insert_batch_size: Mapped[int] = mapped_column(Integer, nullable=False)
    scope_enum: Mapped[dict[str, str]] = mapped_column(JSON, nullable=False)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )


class OfflineIngestionTask(Base):
    __tablename__ = "offline_ingestion_tasks"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    task_id: Mapped[str] = mapped_column(String(64), nullable=False, unique=True, index=True)
    status: Mapped[str] = mapped_column(String(24), nullable=False, default="pending", server_default="pending", index=True)
    progress_percent: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    current_stage: Mapped[str | None] = mapped_column(String(128), nullable=True)
    kb_version: Mapped[str | None] = mapped_column(String(128), nullable=True, index=True)
    config_id: Mapped[int] = mapped_column(BigInteger, nullable=False, index=True)
    ingest_type: Mapped[str] = mapped_column(String(24), nullable=False, default="mixed", server_default="mixed", index=True)
    upload_root: Mapped[str | None] = mapped_column(String(512), nullable=True)
    source_data_root: Mapped[str] = mapped_column(String(512), nullable=False)
    clean_markdown_dir: Mapped[str] = mapped_column(String(128), nullable=False)
    index_csv_name: Mapped[str] = mapped_column(String(128), nullable=False)
    faq_csv_dir: Mapped[str] = mapped_column(String(128), nullable=False)
    auto_publish: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default="0")
    version_description: Mapped[str | None] = mapped_column(String(255), nullable=True)
    document_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    parent_chunk_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    child_chunk_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    faq_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_by: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )
