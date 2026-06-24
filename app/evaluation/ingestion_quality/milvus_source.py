"""Milvus data source for ingestion quality evaluation."""

from __future__ import annotations

from typing import Any

from pymilvus import Collection, connections, db, utility
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.config import get_runtime_config
from app.core.exceptions import BadRequestException, NotFoundException


CHUNK_OUTPUT_FIELDS = [
    "pk",
    "text",
    "kb_version",
    "source",
    "record_type",
    "chunk_id",
    "child_chunk_id",
    "source_doc_id",
    "doc_id",
    "parent_id",
    "title_path",
]


def build_chunk_quality_payload_from_milvus(
    db_session: Session,
    *,
    kb_version: str,
    batch_size: int = 1000,
) -> dict[str, Any]:
    """Read all doc chunks for a knowledge version and build chunk-quality payload."""

    version = _get_version_info(db_session, kb_version)
    rows = _query_doc_chunks(
        collection_name=version["doc_collection_name"],
        kb_version=version["kb_version"],
        batch_size=batch_size,
    )
    chunks = [_row_to_chunk(row, index=index) for index, row in enumerate(rows, start=1)]
    document_ids = {chunk["document_id"] for chunk in chunks if chunk.get("document_id")}
    return {
        "dataset_id": version["kb_version"],
        "user_type": "milvus",
        "document_metrics_mode": "milvus",
        "actual_document_count": len(document_ids),
        "expected_document_count": len(document_ids),
        "chunks": chunks,
        "source": {
            "type": "milvus",
            "kb_version": version["kb_version"],
            "doc_collection_name": version["doc_collection_name"],
            "chunk_count": len(chunks),
        },
    }


def _get_version_info(db_session: Session, kb_version: str) -> dict[str, str]:
    cleaned = kb_version.strip()
    if not cleaned:
        raise BadRequestException("knowledge_base_version cannot be empty")
    row = db_session.execute(
        text(
            """
            SELECT kb_version, doc_collection_name
            FROM kb_versions
            WHERE kb_version = :kb_version
              AND doc_collection_name IS NOT NULL
            LIMIT 1
            """
        ),
        {"kb_version": cleaned},
    ).mappings().first()
    if row is None:
        raise NotFoundException("knowledge base version not found or missing doc collection")
    return {"kb_version": str(row["kb_version"]), "doc_collection_name": str(row["doc_collection_name"])}


def _query_doc_chunks(
    *,
    collection_name: str,
    kb_version: str,
    batch_size: int,
) -> list[dict[str, Any]]:
    config = get_runtime_config().app.milvus
    connections.connect(
        alias=config.alias,
        host=config.host,
        port=str(config.port),
        db_name=config.database,
    )
    db.using_database(config.database, using=config.alias)
    if not utility.has_collection(collection_name, using=config.alias):
        raise NotFoundException(f"Milvus collection not found: {collection_name}")

    collection = Collection(collection_name, using=config.alias)
    collection.load()
    expr = f'kb_version == "{_escape_expr_value(kb_version)}"'
    rows: list[dict[str, Any]] = []
    iterator = collection.query_iterator(
        expr=expr,
        output_fields=CHUNK_OUTPUT_FIELDS,
        batch_size=batch_size,
    )
    try:
        while True:
            batch = iterator.next()
            if not batch:
                break
            rows.extend(dict(item) for item in batch)
    finally:
        iterator.close()
    return rows


def _row_to_chunk(row: dict[str, Any], *, index: int) -> dict[str, Any]:
    chunk_id = _string_value(
        row.get("chunk_id") or row.get("child_chunk_id") or row.get("pk"),
        fallback=f"chunk_{index}",
    )
    document_id = _string_value(row.get("source_doc_id") or row.get("doc_id"))
    title_path = _string_value(row.get("title_path"))
    text_value = _string_value(row.get("text"))
    return {
        "chunk_id": chunk_id,
        "document_id": document_id or None,
        "text": text_value,
        "chunk_type": _infer_chunk_type(row, text_value=text_value),
        "title_path": title_path or None,
    }


def _infer_chunk_type(row: dict[str, Any], *, text_value: str) -> str:
    record_type = _string_value(row.get("record_type")).strip().lower()
    if record_type:
        return record_type
    stripped = text_value.lstrip().lower()
    if stripped.startswith("<table") or "<tr" in stripped[:500]:
        return "table"
    return "text"


def _string_value(value: Any, fallback: str = "") -> str:
    if value is None:
        return fallback
    return str(value)


def _escape_expr_value(value: str) -> str:
    return value.replace("\\", "\\\\").replace('"', '\\"')
