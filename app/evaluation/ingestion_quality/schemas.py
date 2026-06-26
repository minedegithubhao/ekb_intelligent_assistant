"""chunk 质量评估结果的数据结构。"""

from __future__ import annotations

from pydantic import BaseModel, Field


class ChunkQualityDatasetInfo(BaseModel):
    """临时数据集列表接口返回的元数据。"""

    dataset: str
    dataset_id: str
    user_type: str
    path: str


class DocumentIngestMetrics(BaseModel):
    """文档层级的入库完整率指标，当前由临时数据模拟。"""

    expected_document_count: int
    actual_document_count: int
    document_ingest_completeness_rate: float


class ChunkQualityMetrics(BaseModel):
    """chunk 层级的分布和质量聚合指标。"""

    chunk_count: int
    duplicate_chunk_count: int
    min_chunk_length: int
    max_chunk_length: int
    avg_chunk_length: float
    low_quality_issue_count: int
    empty_chunk_count: int
    empty_chunk_rate: float
    too_short_chunk_count: int
    too_short_chunk_rate: float
    too_long_chunk_count: int
    too_long_chunk_rate: float
    low_unique_ratio_chunk_count: int
    low_unique_ratio_chunk_rate: float
    duplicate_group_count: int


class ChunkQualityIssue(BaseModel):
    """单个 chunk 命中的低质量问题。"""

    chunk_id: str
    document_id: str | None = None
    issue_type: str
    reason: str
    text_length: int
    unique_ratio: float | None = None
    duplicate_hash: str | None = None


class ChunkQualityEvaluationResult(BaseModel):
    """单次 chunk 质量评估的完整返回结果。"""

    dataset: str
    dataset_id: str
    user_type: str
    document_metrics_mode: str
    parent_chunk_size: int
    min_chunk_length_threshold: int
    max_chunk_length_threshold: int
    low_unique_ratio_threshold: float
    document_metrics: DocumentIngestMetrics
    chunk_metrics: ChunkQualityMetrics
    low_quality_issues: list[ChunkQualityIssue] = Field(default_factory=list)
