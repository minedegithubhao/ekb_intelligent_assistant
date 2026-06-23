"""离线入库配置。

这里保存与离线入库直接相关的默认值，包括目录、chunk 大小、表格策略、
collection 名称和批处理大小等。生产环境建议通过环境变量或数据库配置表覆盖。
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]


def _resolve_path(value: str | Path) -> Path:
    """把配置值统一解析成路径。

    允许两种写法：
    1. 绝对路径，直接使用
    2. 相对路径，按项目根目录解析
    """

    path = Path(value)
    if path.is_absolute():
        return path
    return PROJECT_ROOT / path


def _env_path(name: str, default: str) -> Path:
    """读取环境变量中的路径配置，没有则回退到默认值。"""

    return _resolve_path(os.getenv(name, default))


@dataclass(frozen=True)
class IngestionSettings:
    """一次离线入库任务的运行参数。"""

    source_data_root: Path = field(default_factory=lambda: _env_path("KNOWFORGE_SOURCE_DATA_ROOT", "source_data"))
    clean_markdown_dir: str = field(default_factory=lambda: os.getenv("KNOWFORGE_CLEAN_MARKDOWN_DIR", "清洗后数据"))
    index_csv_name: str = field(default_factory=lambda: os.getenv("KNOWFORGE_INDEX_CSV_NAME", "index.csv"))
    faq_csv_dir: str = field(default_factory=lambda: os.getenv("KNOWFORGE_FAQ_CSV_DIR", "faq"))

    doc_parent_chunk_size: int = field(default_factory=lambda: int(os.getenv("KNOWFORGE_DOC_PARENT_CHUNK_SIZE", "1200")))
    doc_child_chunk_size: int = field(default_factory=lambda: int(os.getenv("KNOWFORGE_DOC_CHILD_CHUNK_SIZE", "400")))
    doc_child_chunk_overlap: int = field(default_factory=lambda: int(os.getenv("KNOWFORGE_DOC_CHILD_CHUNK_OVERLAP", "80")))

    table_split_strategy: str = field(default_factory=lambda: os.getenv("KNOWFORGE_TABLE_SPLIT_STRATEGY", "row"))
    table_header_required: bool = field(default_factory=lambda: os.getenv("KNOWFORGE_TABLE_HEADER_REQUIRED", "true").lower() == "true")
    table_row_max_chars: int = field(default_factory=lambda: int(os.getenv("KNOWFORGE_TABLE_ROW_MAX_CHARS", "1000")))

    rule_metadata_filter_keys: tuple[str, ...] = (
        "rule_id",
        "source_url",
        "label_names",
        "active_time",
        "update_time",
    )

    doc_collection_name: str = field(default_factory=lambda: os.getenv("KNOWFORGE_DOC_COLLECTION_NAME", "doc_collection"))
    faq_collection_name: str = field(default_factory=lambda: os.getenv("KNOWFORGE_FAQ_COLLECTION_NAME", "faq_collection"))
    dense_vector_dim: int = field(default_factory=lambda: int(os.getenv("KNOWFORGE_DENSE_VECTOR_DIM", "1024")))
    sparse_vector_enabled: bool = field(default_factory=lambda: os.getenv("KNOWFORGE_SPARSE_VECTOR_ENABLED", "true").lower() == "true")

    embedding_batch_size: int = field(default_factory=lambda: int(os.getenv("KNOWFORGE_EMBEDDING_BATCH_SIZE", "32")))
    milvus_insert_batch_size: int = field(default_factory=lambda: int(os.getenv("KNOWFORGE_MILVUS_INSERT_BATCH_SIZE", "500")))
    strict_index_match: bool = field(default_factory=lambda: os.getenv("KNOWFORGE_STRICT_INDEX_MATCH", "true").lower() == "true")
    faq_reference_required: bool = field(default_factory=lambda: os.getenv("KNOWFORGE_FAQ_REFERENCE_REQUIRED", "true").lower() == "true")

    scope_enum: dict[str, str] = field(
        default_factory=lambda: {
            "enterprise": "企业",
            "personal_individual": "个人/个体",
        }
    )

    @property
    def clean_data_root(self) -> Path:
        """清洗后数据根目录。

        默认约定为项目根目录下的 `source_data/清洗后数据`，这样代码迁移到
        不同机器或容器时不需要修改源码路径。
        """

        return self.source_data_root / self.clean_markdown_dir

    @property
    def index_csv_path(self) -> Path:
        """默认的 `index.csv` 路径。"""

        return self.clean_data_root / self.index_csv_name

    def validate(self) -> None:
        """对关键配置做基本安全检查。

        这里不做复杂业务校验，只拦截明显不合理的值，避免后续切分和写库
        阶段才暴露错误。
        """

        if self.doc_parent_chunk_size <= 0:
            raise ValueError("doc_parent_chunk_size 必须大于 0")
        if self.doc_child_chunk_size <= 0:
            raise ValueError("doc_child_chunk_size 必须大于 0")
        if self.doc_child_chunk_overlap < 0:
            raise ValueError("doc_child_chunk_overlap 不能小于 0")
        if self.doc_child_chunk_overlap >= self.doc_child_chunk_size:
            raise ValueError("doc_child_chunk_overlap 必须小于 doc_child_chunk_size")
        if self.table_split_strategy != "row":
            raise ValueError("当前仅支持 table_split_strategy='row'")
        if self.embedding_batch_size <= 0 or self.milvus_insert_batch_size <= 0:
            raise ValueError("批处理大小必须大于 0")
        if not self.doc_collection_name.strip():
            raise ValueError("doc_collection_name 不能为空")
        if not self.faq_collection_name.strip():
            raise ValueError("faq_collection_name 不能为空")
