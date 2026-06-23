"""企业级离线入库的核心数据结构。

这一层只描述数据长什么样，不承载具体业务流程。清洗、切分、向量化和写入
都依赖这些结构在各层之间传递，便于保持代码边界清晰。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


Metadata = dict[str, Any]


@dataclass(frozen=True)
class IndexRecord:
    """`index.csv` 中的一行索引记录。

    `scope` 表示数据适用范围或类别，例如 `enterprise`、`personal_individual`。
    该字段用于区分企业和个人/个体两类知识源。
    """

    rule_id: str
    scope: str
    title: str
    summary: str
    created: str
    modified: str
    active_time: str
    label_names: str
    source_url: str
    json_path: str
    markdown_path: str


@dataclass(frozen=True)
class CleanedDocument:
    """清洗后的 Markdown 文档。

    `content` 只保留正式正文；文档开头的规则元信息块、无效 URL 等
    不适合检索的内容会在清洗阶段移入 `metadata` 或直接过滤。
    """

    path: Path
    content: str
    metadata: Metadata


@dataclass(frozen=True)
class ParentChunk:
    """父块。

    父块保留较完整的章节上下文，主要用途不是直接检索，而是在最终答案
    回填 evidence 时提供完整证据文本。
    """

    parent_id: str
    source_doc_id: str
    title_path: str
    parent_content: str
    reference_source: str
    scope: str
    metadata: Metadata = field(default_factory=dict)


@dataclass(frozen=True)
class ChildChunk:
    """子块。

    子块是检索的最小单元，dense 检索、BM25 稀疏检索和 rerank 都围绕它展开。
    """

    child_chunk_id: str
    parent_id: str
    source_doc_id: str
    title_path: str
    child_content: str
    parent_content: str
    reference_source: str
    scope: str
    metadata: Metadata = field(default_factory=dict)


@dataclass(frozen=True)
class FAQRecord:
    """一条 FAQ 记录。

    `question` 负责检索，`answer` 负责最终展示。两者分离可以避免把答案文本
    当成主要召回文本，保证 FAQ 召回更接近用户提问。
    """

    faq_id: str
    question: str
    answer: str
    source: str
    reference_source: str
    category: str = ""
    tags: str = ""
    doc_refs: str = ""
    metadata: Metadata = field(default_factory=dict)


@dataclass(frozen=True)
class DocumentVectorRow:
    """文档向量化后的入库行。

    该结构已经具备 Milvus 写入所需的文档字段，可直接交给写入层。
    """

    child_chunk_id: str
    parent_id: str
    source_doc_id: str
    title_path: str
    child_content: str
    parent_content: str
    dense_vector: list[float]
    sparse_vector: dict[int, float] | None
    reference_source: str
    scope: str
    metadata: Metadata


@dataclass(frozen=True)
class FAQVectorRow:
    """FAQ 向量化后的入库行。"""

    faq_id: str
    question: str
    answer: str
    dense_vector: list[float]
    sparse_vector: dict[int, float] | None
    source: str
    reference_source: str
    metadata: Metadata


@dataclass(frozen=True)
class IngestionBatch:
    """清洗和切分后的中间结果。

    这个阶段还没有做向量化，因此适合用于预览、校验和单元测试。
    """

    documents: list[CleanedDocument]
    parent_chunks: list[ParentChunk]
    child_chunks: list[ChildChunk]
    faq_records: list[FAQRecord]
