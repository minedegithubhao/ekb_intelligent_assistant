from __future__ import annotations

from pathlib import Path
import sys

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.enterprise_offline_ingestion.models import ChildChunk
from app.enterprise_offline_ingestion.milvus_writer import MilvusIngestionWriter
from app.enterprise_offline_ingestion.pipeline import OfflineIngestionPipeline
from app.enterprise_offline_ingestion.settings import IngestionSettings
from app.enterprise_offline_ingestion.vectorization import VectorizationService


class RecordingDenseProvider:
    def __init__(self) -> None:
        self.calls: list[list[str]] = []

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        self.calls.append(list(texts))
        return [[float(len(text))] for text in texts]


class RecordingSparseProvider:
    def encode_documents(self, texts: list[str]) -> list[dict[int, float]]:
        return [{0: float(len(text))} for text in texts]


class RecordingWriter:
    def __init__(self) -> None:
        self.deleted_doc_ids: list[str] = []
        self.deleted_faq_ids: list[str] = []
        self.document_rows: list[object] = []
        self.faq_rows: list[object] = []

    def delete_documents_by_source_doc_ids(self, source_doc_ids: list[str]) -> None:
        self.deleted_doc_ids.extend(source_doc_ids)

    def delete_faq_by_ids(self, faq_ids: list[str]) -> None:
        self.deleted_faq_ids.extend(faq_ids)

    def write_documents(self, rows: list[object]) -> None:
        self.document_rows.extend(rows)

    def write_faq(self, rows: list[object]) -> None:
        self.faq_rows.extend(rows)


class FakeField:
    def __init__(
        self,
        *,
        name: str,
        dtype: object,
        is_primary: bool | None = None,
        max_length: int | None = None,
        dim: int | None = None,
    ) -> None:
        self.name = name
        self.dtype = dtype
        self.is_primary = is_primary
        self.params: dict[str, object] = {}
        if max_length is not None:
            self.params["max_length"] = max_length
        if dim is not None:
            self.params["dim"] = dim


class FakeIndex:
    def __init__(self, field_name: str) -> None:
        self.field_name = field_name


class FakeSchema:
    def __init__(self, fields: list[FakeField], *, enable_dynamic_field: bool = True) -> None:
        self.fields = fields
        self.enable_dynamic_field = enable_dynamic_field


class FakeCollection:
    def __init__(
        self,
        fields: list[FakeField],
        indexes: list[FakeIndex] | None = None,
        *,
        enable_dynamic_field: bool = True,
    ) -> None:
        self.schema = FakeSchema(fields, enable_dynamic_field=enable_dynamic_field)
        self.indexes = indexes or []
        self.created_indexes: list[tuple[str, dict[str, object]]] = []

    def create_index(self, field_name: str, index_params: dict[str, object]) -> None:
        self.created_indexes.append((field_name, index_params))
        self.indexes.append(FakeIndex(field_name))


def build_fake_doc_fields(*, dense_dim: int = 1024) -> list[FakeField]:
    return [
        FakeField(name="pk", dtype="varchar", is_primary=True, max_length=64),
        FakeField(name="text", dtype="varchar", max_length=65535),
        FakeField(name="dense", dtype="float_vector", dim=dense_dim),
        FakeField(name="sparse", dtype="sparse_float_vector"),
    ]


def test_prepare_requires_index_match_when_strict(tmp_path: Path) -> None:
    settings = IngestionSettings(
        source_data_root=tmp_path,
        strict_index_match=True,
    )
    pipeline = OfflineIngestionPipeline(settings)

    markdown_path = tmp_path / "missing_rule_doc.md"
    markdown_path.write_text("# 标题\n正文\n", encoding="utf-8")

    index_csv_path = tmp_path / "index.csv"
    index_csv_path.write_text(
        (
            "rule_id,scope,title,summary,created,modified,active_time,label_names,source_url,json_path,markdown_path\n"
            "another_rule,enterprise,标题,摘要,2024-01-01,2024-01-02,长期,标签,https://example.com,a.json,a.md\n"
        ),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="未在 index.csv 中找到"):
        pipeline.prepare(markdown_paths=[markdown_path], faq_paths=[], index_csv_path=index_csv_path)


def test_vectorization_service_batches_requests() -> None:
    dense_provider = RecordingDenseProvider()
    service = VectorizationService(
        dense_provider=dense_provider,
        sparse_provider=RecordingSparseProvider(),
        batch_size=2,
    )
    chunks = [
        ChildChunk(
            child_chunk_id=f"c{i}",
            parent_id="p1",
            source_doc_id="doc1",
            title_path="标题",
            child_content=f"内容{i}",
            parent_content="父内容",
            reference_source="https://example.com",
            scope="enterprise",
            metadata={},
        )
        for i in range(5)
    ]

    rows = service.vectorize_documents(chunks)

    assert len(rows) == 5
    assert dense_provider.calls == [["内容0", "内容1"], ["内容2", "内容3"], ["内容4"]]


def test_ingest_deletes_existing_rows_before_writing(tmp_path: Path) -> None:
    settings = IngestionSettings(
        source_data_root=tmp_path,
        strict_index_match=True,
    )
    vectorization = VectorizationService(
        dense_provider=RecordingDenseProvider(),
        sparse_provider=RecordingSparseProvider(),
        batch_size=2,
    )
    writer = RecordingWriter()
    pipeline = OfflineIngestionPipeline(settings, vectorization_service=vectorization, writer=writer)

    markdown_path = tmp_path / "rule_001_doc.md"
    markdown_path.write_text("# 标题\n这是一段正文。\n", encoding="utf-8")

    faq_path = tmp_path / "faq.csv"
    faq_path.write_text(
        (
            "faq_id,question,answer,source,reference_source,category,tags,doc_refs\n"
            "faq-1,问题1,答案1,FAQ手册,https://example.com/faq,分类,标签,rule\n"
        ),
        encoding="utf-8",
    )

    index_csv_path = tmp_path / "index.csv"
    index_csv_path.write_text(
        (
            "rule_id,scope,title,summary,created,modified,active_time,label_names,source_url,json_path,markdown_path\n"
            "rule,enterprise,标题,摘要,2024-01-01,2024-01-02,长期,标签,https://example.com/rule,rule.json,rule_001_doc.md\n"
        ),
        encoding="utf-8",
    )

    batch = pipeline.ingest(markdown_paths=[markdown_path], faq_paths=[faq_path], index_csv_path=index_csv_path)

    assert batch.documents
    assert writer.deleted_doc_ids == ["rule"]
    assert writer.deleted_faq_ids == ["faq-1"]
    assert len(writer.document_rows) == len(batch.child_chunks)
    assert len(writer.faq_rows) == 1


def test_milvus_writer_ensures_dense_index() -> None:
    settings = IngestionSettings(sparse_vector_enabled=False)
    writer = MilvusIngestionWriter(settings)
    expected_fields = build_fake_doc_fields(dense_dim=settings.dense_vector_dim)
    fake_fields = build_fake_doc_fields(dense_dim=settings.dense_vector_dim)
    collection = FakeCollection(fake_fields)

    writer._validate_collection_schema(collection, expected_fields)
    writer._ensure_collection_indexes(collection)

    assert collection.created_indexes == [
        ("dense", writer._dense_index_params()),
        ("sparse", writer._sparse_index_params()),
    ]


def test_milvus_writer_rejects_schema_mismatch() -> None:
    settings = IngestionSettings()
    writer = MilvusIngestionWriter(settings)
    expected_fields = build_fake_doc_fields(dense_dim=settings.dense_vector_dim)
    mismatched_fields = build_fake_doc_fields(dense_dim=768)
    collection = FakeCollection(mismatched_fields)

    with pytest.raises(ValueError, match="dense.*dim 不匹配"):
        writer._validate_collection_schema(collection, expected_fields)


def test_milvus_writer_expands_metadata_into_dynamic_fields() -> None:
    settings = IngestionSettings(sparse_vector_enabled=False)
    writer = MilvusIngestionWriter(settings)
    row = writer._doc_to_entity(
        type(
            "Row",
            (),
            {
                "child_chunk_id": "child-1",
                "parent_id": "parent-1",
                "source_doc_id": "rule-1",
                "title_path": "标题",
                "child_content": "内容",
                "parent_content": "父内容",
                "dense_vector": [0.1, 0.2],
                "sparse_vector": {1: 1.0},
                "reference_source": "https://example.com",
                "scope": "enterprise",
                "metadata": {
                    "category": "规则",
                    "chunk_order": 1,
                    "tag_list": ["A", "B"],
                    "nested": {"k": "v"},
                },
            },
        )()
    )

    assert row["pk"] == "child-1"
    assert row["text"] == "内容"
    assert row["dense"] == [0.1, 0.2]
    assert row["category"] == "规则"
    assert row["chunk_order"] == 1
    assert row["tag_list"] == ["A", "B"]
    assert row["nested"] == {"k": "v"}
    assert row["source_doc_id"] == "rule-1"
    assert row["reference_source"] == "https://example.com"
    assert "sparse" not in row


def test_milvus_writer_requires_dynamic_field_enabled() -> None:
    settings = IngestionSettings()
    writer = MilvusIngestionWriter(settings)
    expected_fields = build_fake_doc_fields(dense_dim=settings.dense_vector_dim)
    collection = FakeCollection(expected_fields, enable_dynamic_field=False)

    with pytest.raises(ValueError, match="dynamic field"):
        writer._validate_collection_schema(collection, expected_fields)
