"""向量化接口与入库行组装。"""

from __future__ import annotations

from collections.abc import Iterable
from typing import Protocol

from app.enterprise_offline_ingestion.cleaner import split_delimited_text
from app.enterprise_offline_ingestion.models import ChildChunk, DocumentVectorRow, FAQRecord, FAQVectorRow


class DenseEmbeddingProvider(Protocol):
    """dense 向量提供器接口。

    生产环境可以接本地 `bge-m3`，也可以接兼容的远程 embedding 服务。
    """

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        """为每条输入文本返回一个 dense 向量。"""


class SparseVectorProvider(Protocol):
    """sparse 向量提供器接口。

    如果 sparse 由客户端生成，可以在这里接入；如果由 Milvus 侧处理，
    也可以不传这个实现。
    """

    def encode_documents(self, texts: list[str]) -> list[dict[int, float]]:
        """为每条输入文本返回一个 sparse 向量。"""


class VectorizationService:
    """把切分结果转换成可写入向量库的行。"""

    def __init__(
        self,
        dense_provider: DenseEmbeddingProvider,
        sparse_provider: SparseVectorProvider | None = None,
        *,
        batch_size: int = 32,
    ) -> None:
        self.dense_provider = dense_provider
        self.sparse_provider = sparse_provider
        self.batch_size = batch_size

    def vectorize_documents(self, chunks: list[ChildChunk]) -> list[DocumentVectorRow]:
        """文档只对 child_content 做向量化。

        parent_content 保留给最终回填展示，不作为主检索文本。
        """

        rows: list[DocumentVectorRow] = []
        for chunk_batch in self._batches(chunks):
            texts = [chunk.child_content for chunk in chunk_batch]
            dense_vectors = self.dense_provider.embed_documents(texts)
            sparse_vectors = self._encode_sparse(texts)
            self._validate_count("document", len(chunk_batch), dense_vectors, sparse_vectors)
            rows.extend(
                DocumentVectorRow(
                    child_chunk_id=chunk.child_chunk_id,
                    parent_id=chunk.parent_id,
                    source_doc_id=chunk.source_doc_id,
                    title_path=chunk.title_path,
                    child_content=chunk.child_content,
                    parent_content=chunk.parent_content,
                    dense_vector=dense_vectors[index],
                    sparse_vector=sparse_vectors[index] if sparse_vectors else None,
                    reference_source=chunk.reference_source,
                    scope=chunk.scope,
                    metadata={
                        **chunk.metadata,
                        "title_path": chunk.title_path,
                        "parent_id": chunk.parent_id,
                    },
                )
                for index, chunk in enumerate(chunk_batch)
            )
        return rows

    def vectorize_faq(self, records: list[FAQRecord]) -> list[FAQVectorRow]:
        """FAQ 只对 question 做向量化。

        answer 保持完整展示文本，不参与主要召回文本构造。
        """

        rows: list[FAQVectorRow] = []
        for record_batch in self._batches(records):
            questions = [record.question for record in record_batch]
            dense_vectors = self.dense_provider.embed_documents(questions)
            sparse_vectors = self._encode_sparse(questions)
            self._validate_count("faq", len(record_batch), dense_vectors, sparse_vectors)
            rows.extend(
                FAQVectorRow(
                    faq_id=record.faq_id,
                    question=record.question,
                    answer=record.answer,
                    dense_vector=dense_vectors[index],
                    sparse_vector=sparse_vectors[index] if sparse_vectors else None,
                    source=record.source,
                    reference_source=record.reference_source,
                    metadata={
                        **record.metadata,
                        "record_type": "faq",
                        "category": record.category,
                        "tags": record.tags,
                        "tag_list": split_delimited_text(record.tags),
                        "doc_refs": record.doc_refs,
                        "doc_ref_ids": split_delimited_text(record.doc_refs),
                    },
                )
                for index, record in enumerate(record_batch)
            )
        return rows

    def _encode_sparse(self, texts: list[str]) -> list[dict[int, float]] | None:
        """生成 sparse 向量；如果没有提供 sparse provider，则返回 None。"""

        if self.sparse_provider is None:
            return None
        return self.sparse_provider.encode_documents(texts)

    def _batches(self, items: list[object]) -> Iterable[list[object]]:
        """按配置把待向量化数据切成稳定批次。"""

        for start in range(0, len(items), self.batch_size):
            yield items[start : start + self.batch_size]

    @staticmethod
    def _validate_count(
        name: str,
        expected: int,
        dense_vectors: list[list[float]],
        sparse_vectors: list[dict[int, float]] | None,
    ) -> None:
        """校验向量数量必须和输入数量一致。"""

        if len(dense_vectors) != expected:
            raise ValueError(f"{name} dense 向量数量不匹配")
        if sparse_vectors is not None and len(sparse_vectors) != expected:
            raise ValueError(f"{name} sparse 向量数量不匹配")
