"""JSON vector ingestion using LangChain Milvus hybrid search."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from functools import lru_cache
from pathlib import Path
from typing import Any

from langchain_core.documents import Document
from langchain_huggingface import HuggingFaceEmbeddings
from langchain_milvus import BM25BuiltInFunction, Milvus

from app.core.config import get_runtime_config
from app.core.exceptions import BadRequestException, ServiceUnavailableException
from app.schemas.vector_ingest_json import (
    JsonVectorIngestBatchResult,
    JsonVectorIngestFailedItem,
    JsonVectorIngestResult,
)

ALLOWED_RECORD_TYPES = {"faq", "doc"}
ALLOWED_ITEM_RECORD_TYPES_BY_REQUEST = {
    "faq": {"faq"},
    "doc": {"doc", "document", "document_chunk"},
}
COLLECTION_BY_RECORD_TYPE = {
    "faq": "faq_collection_dev_sample",
    "doc": "doc_collection_dev_sample",
}
DEFAULT_BGE_M3_MODEL_PATH = Path("D:/ai大模型/rag/04_代码/knowforge-rag-platform/models/bge-m3")


class JsonVectorIngestService:
    def ingest_json_files(
        self,
        *,
        files: list[tuple[str, bytes]],
        record_type: str,
        imported_by: int,
    ) -> JsonVectorIngestBatchResult:
        normalized_type = _normalize_record_type(record_type)
        collection_name = COLLECTION_BY_RECORD_TYPE[normalized_type]
        file_results: list[JsonVectorIngestResult] = []

        for file_name, content in files:
            try:
                file_results.append(
                    self.ingest_json_bytes(
                        content=content,
                        file_name=file_name,
                        record_type=normalized_type,
                        imported_by=imported_by,
                    )
                )
            except BadRequestException as exc:
                file_results.append(
                    JsonVectorIngestResult(
                        file_name=file_name,
                        record_type=normalized_type,
                        collection_name=collection_name,
                        kb_versions=[],
                        total_count=0,
                        success_count=0,
                        failed_count=1,
                        failed_items=[JsonVectorIngestFailedItem(index=-1, reason=exc.message)],
                    )
                )

        success_files = sum(1 for item in file_results if item.success_count > 0 and item.failed_count == 0)
        failed_files = sum(1 for item in file_results if item.failed_count > 0)
        kb_versions = sorted({version for item in file_results for version in item.kb_versions})
        return JsonVectorIngestBatchResult(
            record_type=normalized_type,
            collection_name=collection_name,
            kb_versions=kb_versions,
            total_files=len(file_results),
            success_files=success_files,
            failed_files=failed_files,
            total_count=sum(item.total_count for item in file_results),
            success_count=sum(item.success_count for item in file_results),
            failed_count=sum(item.failed_count for item in file_results),
            file_results=file_results,
        )

    def ingest_json_bytes(
        self,
        *,
        content: bytes,
        file_name: str,
        record_type: str,
        imported_by: int,
    ) -> JsonVectorIngestResult:
        normalized_type = _normalize_record_type(record_type)
        _validate_file_name(file_name)
        rows = _load_json_array(content)

        collection_name = COLLECTION_BY_RECORD_TYPE[normalized_type]
        documents: list[Document] = []
        ids: list[str] = []
        failed_items: list[JsonVectorIngestFailedItem] = []
        seen_pks: set[str] = set()
        kb_versions: set[str] = set()
        imported_at = datetime.now(UTC).isoformat()

        for index, item in enumerate(rows):
            document, pk, failure = _item_to_document(
                item,
                index=index,
                record_type=normalized_type,
                file_name=file_name,
                imported_by=imported_by,
                imported_at=imported_at,
            )
            if failure:
                failed_items.append(failure)
                continue
            if pk in seen_pks:
                failed_items.append(
                    JsonVectorIngestFailedItem(index=index, pk=pk, reason="duplicate pk in uploaded file")
                )
                continue
            seen_pks.add(pk)
            documents.append(document)
            ids.append(pk)
            kb_version = _clean_string(document.metadata.get("kb_version"))
            if kb_version:
                kb_versions.add(kb_version)

        if documents:
            try:
                store = MilvusVectorStoreFactory().create(record_type=normalized_type)
                store.add_documents(documents, ids=ids)
            except Exception as exc:  # noqa: BLE001 - normalize vector-store failures for API callers.
                failed_items.extend(
                    JsonVectorIngestFailedItem(index=-1, pk=pk, reason=f"milvus insert failed: {exc}")
                    for pk in ids
                )
                documents = []

        return JsonVectorIngestResult(
            file_name=file_name,
            record_type=normalized_type,
            collection_name=collection_name,
            kb_versions=sorted(kb_versions) if documents else [],
            total_count=len(rows),
            success_count=len(documents),
            failed_count=len(failed_items),
            failed_items=failed_items,
        )


class MilvusVectorStoreFactory:
    def create(self, *, record_type: str) -> Milvus:
        normalized_type = _normalize_record_type(record_type)
        milvus_config = get_runtime_config().app.milvus
        collection_name = COLLECTION_BY_RECORD_TYPE[normalized_type]
        return Milvus(
            embedding_function=BgeM3EmbeddingFactory().create(),
            builtin_function=BM25BuiltInFunction(),
            collection_name=collection_name,
            connection_args={
                "uri": f"http://{milvus_config.host}:{milvus_config.port}",
                "db_name": milvus_config.database,
            },
            vector_field=["dense", "sparse"],
            text_field="text",
            primary_field="pk",
            auto_id=False,
            enable_dynamic_field=True,
            consistency_level="Session",
            drop_old=False,
        )


class BgeM3EmbeddingFactory:
    def create(self) -> HuggingFaceEmbeddings:
        model_path = _resolve_bge_m3_model_path()
        return _get_bge_m3_embeddings(str(model_path))


def _normalize_record_type(record_type: str) -> str:
    normalized = (record_type or "").strip().lower()
    if normalized not in ALLOWED_RECORD_TYPES:
        raise BadRequestException("record_type must be faq or doc")
    return normalized


def _validate_file_name(file_name: str) -> None:
    if not file_name.lower().endswith(".json"):
        raise BadRequestException("only .json files are supported")


def _load_json_array(content: bytes) -> list[Any]:
    try:
        text = content.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise BadRequestException("json file must be utf-8 encoded") from exc
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        raise BadRequestException(f"invalid json: {exc.msg}") from exc
    if not isinstance(data, list):
        raise BadRequestException("json root must be an array")
    return data


def _item_to_document(
    item: Any,
    *,
    index: int,
    record_type: str,
    file_name: str,
    imported_by: int,
    imported_at: str,
) -> tuple[Document | None, str | None, JsonVectorIngestFailedItem | None]:
    if not isinstance(item, dict):
        return None, None, JsonVectorIngestFailedItem(index=index, reason="item must be an object")

    pk = _clean_string(item.get("pk"))
    if not pk:
        return None, None, JsonVectorIngestFailedItem(index=index, reason="pk is required")

    text = _clean_string(item.get("text"))
    if not text:
        return None, pk, JsonVectorIngestFailedItem(index=index, pk=pk, reason="text is required")

    dynamic_fields = item.get("dynamic_fields")
    if not isinstance(dynamic_fields, dict):
        return None, pk, JsonVectorIngestFailedItem(index=index, pk=pk, reason="dynamic_fields must be an object")

    item_record_type = _clean_string(dynamic_fields.get("record_type"))
    if item_record_type not in ALLOWED_ITEM_RECORD_TYPES_BY_REQUEST[record_type]:
        return (
            None,
            pk,
            JsonVectorIngestFailedItem(
                index=index,
                pk=pk,
                reason="dynamic_fields.record_type is not compatible with request record_type",
            ),
        )

    metadata = {
        **dynamic_fields,
        "pk": pk,
        "ingest_record_type": record_type,
        "import_file_name": file_name,
        "imported_by": imported_by,
        "imported_at": imported_at,
    }
    return Document(page_content=text, metadata=metadata), pk, None


def _clean_string(value: Any) -> str:
    return value.strip() if isinstance(value, str) else ""


def _resolve_bge_m3_model_path() -> Path:
    configured = Path(get_runtime_config().retrieval.embedding_model_path)
    if configured.exists():
        return configured
    if DEFAULT_BGE_M3_MODEL_PATH.exists():
        return DEFAULT_BGE_M3_MODEL_PATH
    raise ServiceUnavailableException(f"bge-m3 model path not found: {configured}")


@lru_cache(maxsize=1)
def _get_bge_m3_embeddings(model_path: str) -> HuggingFaceEmbeddings:
    _ensure_cuda_available()
    return HuggingFaceEmbeddings(
        model_name=model_path,
        model_kwargs={"device": "cuda"},
        encode_kwargs={"normalize_embeddings": True},
    )


def _ensure_cuda_available() -> None:
    try:
        import torch
    except Exception as exc:  # noqa: BLE001 - expose a clear API error when torch is misconfigured.
        raise ServiceUnavailableException("PyTorch is required for CUDA embedding inference") from exc
    if not torch.cuda.is_available():
        raise ServiceUnavailableException("CUDA is not available in current Python environment")
