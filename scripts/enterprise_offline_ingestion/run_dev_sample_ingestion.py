from __future__ import annotations

from pathlib import Path
from typing import Any

import torch
from pymilvus import Collection, connections, db, utility
from transformers import AutoModel, AutoTokenizer

from app.core.config import get_runtime_config
from app.enterprise_offline_ingestion.milvus_writer import MilvusIngestionWriter
from app.enterprise_offline_ingestion.pipeline import OfflineIngestionPipeline
from app.enterprise_offline_ingestion.settings import IngestionSettings
from app.enterprise_offline_ingestion.vectorization import VectorizationService


ROOT = Path(__file__).resolve().parents[2]
RAW_DATA_DIR = ROOT / "source_data" / "原始数据"


class LocalDenseEmbeddingProvider:
    """调试入库专用的本地 dense 向量提供器。

    这里直接基于 transformers 加载本地 bge-m3 模型，只生成 dense 向量，
    避免受 FlagEmbedding 与当前环境版本兼容性影响。
    """

    def __init__(self, model_path: str, *, batch_size: int = 4, max_length: int = 512) -> None:
        self.model_path = model_path
        self.batch_size = batch_size
        self.max_length = max_length
        self._tokenizer: Any | None = None
        self._model: Any | None = None

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        tokenizer, model = self._load()
        vectors: list[list[float]] = []
        for start in range(0, len(texts), self.batch_size):
            batch = texts[start : start + self.batch_size]
            encoded = tokenizer(
                batch,
                padding=True,
                truncation=True,
                max_length=self.max_length,
                return_tensors="pt",
            )
            with torch.no_grad():
                outputs = model(**encoded)
            last_hidden_state = outputs.last_hidden_state
            attention_mask = encoded["attention_mask"].unsqueeze(-1)
            masked = last_hidden_state * attention_mask
            pooled = masked.sum(dim=1) / attention_mask.sum(dim=1).clamp(min=1)
            normalized = torch.nn.functional.normalize(pooled, p=2, dim=1)
            vectors.extend(normalized.cpu().tolist())
        return [[float(item) for item in vector] for vector in vectors]

    def _load(self) -> tuple[Any, Any]:
        if self._tokenizer is None or self._model is None:
            self._tokenizer = AutoTokenizer.from_pretrained(self.model_path)
            self._model = AutoModel.from_pretrained(self.model_path)
            self._model.eval()
        return self._tokenizer, self._model


def build_settings() -> IngestionSettings:
    return IngestionSettings(
        source_data_root=ROOT / "source_data",
        clean_markdown_dir="原始数据",
        index_csv_name="index.csv",
        doc_collection_name="doc_collection_dev_sample",
        faq_collection_name="faq_collection_dev_sample",
        dense_vector_dim=1024,
        sparse_vector_enabled=False,
        embedding_batch_size=4,
        milvus_insert_batch_size=16,
        strict_index_match=True,
        faq_reference_required=True,
    )


def build_sample_paths() -> tuple[list[Path], list[Path], Path]:
    markdown_paths = [
        RAW_DATA_DIR / "企业" / "1011532864321359872_京东开放平台商业空间类目商品商家考核规则.md",
        RAW_DATA_DIR / "个体" / "1090224406216708096_京东开放平台个人_个体交易管理规则.md",
    ]
    faq_paths = [
        RAW_DATA_DIR / "faq" / "dev_sample_faq.csv",
    ]
    index_csv_path = RAW_DATA_DIR / "index.csv"

    missing = [str(path) for path in [*markdown_paths, *faq_paths, index_csv_path] if not path.exists()]
    if missing:
        raise FileNotFoundError(f"缺少样本文件: {missing}")
    return markdown_paths, faq_paths, index_csv_path


def print_collection_summary(name: str) -> None:
    runtime = get_runtime_config().app.milvus
    connections.connect(
        alias=runtime.alias,
        host=runtime.host,
        port=str(runtime.port),
        db_name=runtime.database,
    )
    db.using_database(runtime.database, using=runtime.alias)
    if not utility.has_collection(name, using=runtime.alias):
        print({"collection": name, "exists": False})
        return
    collection = Collection(name=name, using=runtime.alias)
    sample_rows = collection.query(expr="", limit=1, output_fields=["*"])
    sample_keys = sorted(sample_rows[0].keys()) if sample_rows else []
    print(
        {
            "collection": name,
            "exists": True,
            "num_entities": collection.num_entities,
            "dynamic_field_enabled": getattr(collection.schema, "enable_dynamic_field", False),
            "functions": [
                {
                    "name": getattr(fn, "name", None),
                    "type": str(getattr(fn, "type", None)),
                    "input": getattr(fn, "input_field_names", None),
                    "output": getattr(fn, "output_field_names", None),
                }
                for fn in (getattr(collection.schema, "functions", None) or [])
            ],
            "indexes": [getattr(index, "field_name", None) for index in (collection.indexes or [])],
            "sample_keys": sample_keys,
        }
    )


def drop_collection_if_exists(name: str) -> None:
    runtime = get_runtime_config().app.milvus
    connections.connect(
        alias=runtime.alias,
        host=runtime.host,
        port=str(runtime.port),
        db_name=runtime.database,
    )
    db.using_database(runtime.database, using=runtime.alias)
    if utility.has_collection(name, using=runtime.alias):
        utility.drop_collection(name, using=runtime.alias)


def main() -> None:
    settings = build_settings()
    markdown_paths, faq_paths, index_csv_path = build_sample_paths()
    runtime = get_runtime_config()
    vectorization_service = VectorizationService(
        dense_provider=LocalDenseEmbeddingProvider(
            runtime.app.models.embedding_model_path,
            batch_size=settings.embedding_batch_size,
        ),
        sparse_provider=None,
        batch_size=settings.embedding_batch_size,
    )

    pipeline = OfflineIngestionPipeline(
        settings,
        vectorization_service=vectorization_service,
        writer=MilvusIngestionWriter(settings),
    )
    drop_collection_if_exists(settings.doc_collection_name)
    drop_collection_if_exists(settings.faq_collection_name)

    batch = pipeline.ingest(
        markdown_paths=markdown_paths,
        faq_paths=faq_paths,
        index_csv_path=index_csv_path,
    )

    print(
        {
            "documents": len(batch.documents),
            "parent_chunks": len(batch.parent_chunks),
            "child_chunks": len(batch.child_chunks),
            "faq_records": len(batch.faq_records),
            "doc_collection": settings.doc_collection_name,
            "faq_collection": settings.faq_collection_name,
        }
    )
    print_collection_summary(settings.doc_collection_name)
    print_collection_summary(settings.faq_collection_name)


if __name__ == "__main__":
    main()
