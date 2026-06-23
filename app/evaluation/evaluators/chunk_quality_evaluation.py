"""基于临时 JSON 数据集的 chunk 质量评估。"""

from __future__ import annotations

import hashlib
import json
from collections import defaultdict
from pathlib import Path
from typing import Any

from app.core.exceptions import BadRequestException, NotFoundException
from app.evaluation.evaluators.chunk_quality import (
    ChunkQualityDatasetInfo,
    ChunkQualityEvaluationResult,
    ChunkQualityIssue,
    ChunkQualityMetrics,
    DocumentIngestMetrics,
)

PROJECT_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_DATASET_DIR = Path(__file__).resolve().parent
# 临时数据集注册表。后续入库流程提供真实 chunk 数据后，只需要把这里
# 替换成真实数据来源。
DEFAULT_DATASETS = {
    "enterprise": DEFAULT_DATASET_DIR / "chunk_quality_enterprise.json",
    "personal": DEFAULT_DATASET_DIR / "chunk_quality_personal.json",
}

# 阈值来自当前评估需求文档。
MIN_CHUNK_LENGTH = 30
LOW_UNIQUE_RATIO_MIN_LENGTH = 50
LOW_UNIQUE_RATIO_THRESHOLD = 0.08
DEFAULT_PARENT_CHUNK_SIZE = 500


def list_chunk_quality_datasets() -> list[ChunkQualityDatasetInfo]:
    """返回当前阶段可用的临时 chunk 数据集。"""

    datasets: list[ChunkQualityDatasetInfo] = []
    for dataset, path in DEFAULT_DATASETS.items():
        payload = _load_json(path)
        datasets.append(
            ChunkQualityDatasetInfo(
                dataset=dataset,
                dataset_id=str(payload.get("dataset_id", dataset)),
                user_type=str(payload.get("user_type", dataset)),
                path=str(path.relative_to(PROJECT_ROOT)),
            )
        )
    return datasets


def evaluate_chunk_quality_dataset(dataset: str) -> ChunkQualityEvaluationResult:
    """按数据集名称加载临时数据，并计算文档和 chunk 指标。"""

    dataset_key = dataset.strip().lower()
    path = DEFAULT_DATASETS.get(dataset_key)
    if path is None:
        supported = ", ".join(sorted(DEFAULT_DATASETS))
        raise NotFoundException(f"chunk quality dataset not found: {dataset}. supported: {supported}")
    payload = _load_json(path)
    return evaluate_chunk_quality_payload(dataset_key, payload)


def evaluate_chunk_quality_payload(dataset: str, payload: dict[str, Any]) -> ChunkQualityEvaluationResult:
    """基于统一格式的 chunk 数据计算质量指标。"""

    chunks = payload.get("chunks")
    if not isinstance(chunks, list):
        raise BadRequestException("chunk dataset must contain a chunks list")

    parent_chunk_size = _positive_int(payload.get("parent_chunk_size"), DEFAULT_PARENT_CHUNK_SIZE)
    max_chunk_length = max(parent_chunk_size * 2, 2000)
    # 先统一构建重复分组，后续只标记重复组中的冗余副本，
    # 第一条保留为基准 chunk。
    duplicate_groups = _build_duplicate_groups(chunks)
    duplicate_chunk_ids_by_hash = _duplicate_chunk_ids_by_hash(duplicate_groups)

    issues: list[ChunkQualityIssue] = []
    lengths: list[int] = []
    empty_count = 0
    too_short_count = 0
    too_long_count = 0
    low_unique_count = 0

    for index, chunk in enumerate(chunks):
        if not isinstance(chunk, dict):
            raise BadRequestException(f"chunk item at index {index} must be an object")

        chunk_id = _string_value(chunk.get("chunk_id"), fallback=f"chunk_{index + 1}")
        document_id = _nullable_string(chunk.get("document_id"))
        text = _string_value(chunk.get("text"))
        stripped_text = text.strip()
        text_length = len(stripped_text)
        lengths.append(text_length)

        is_table = _is_table_chunk(chunk)
        unique_ratio = _unique_char_ratio(stripped_text)

        # 空 chunk 没有可检索语义，记录 empty 问题后跳过其他文本质量检查。
        if not stripped_text:
            empty_count += 1
            issues.append(
                ChunkQualityIssue(
                    chunk_id=chunk_id,
                    document_id=document_id,
                    issue_type="empty",
                    reason="chunk text is empty after stripping whitespace",
                    text_length=text_length,
                )
            )
            continue

        # 表格 chunk 即使较短，也可能承载结构化业务含义，因此不按过短处理。
        if text_length < MIN_CHUNK_LENGTH and not is_table:
            too_short_count += 1
            issues.append(
                ChunkQualityIssue(
                    chunk_id=chunk_id,
                    document_id=document_id,
                    issue_type="too_short",
                    reason=f"text length is below {MIN_CHUNK_LENGTH} and chunk is not table",
                    text_length=text_length,
                )
            )

        # 最大长度阈值由 parent_chunk_size 推导，但最低不小于 2000，
        # 与需求文档保持一致。
        if text_length > max_chunk_length:
            too_long_count += 1
            issues.append(
                ChunkQualityIssue(
                    chunk_id=chunk_id,
                    document_id=document_id,
                    issue_type="too_long",
                    reason=f"text length exceeds {max_chunk_length}",
                    text_length=text_length,
                )
            )

        # 唯一字符比例过低通常意味着重复字符噪声，例如 OCR 异常或解析失败。
        if (
            text_length >= LOW_UNIQUE_RATIO_MIN_LENGTH
            and unique_ratio < LOW_UNIQUE_RATIO_THRESHOLD
            and not is_table
        ):
            low_unique_count += 1
            issues.append(
                ChunkQualityIssue(
                    chunk_id=chunk_id,
                    document_id=document_id,
                    issue_type="low_unique_ratio",
                    reason=f"unique character ratio is below {LOW_UNIQUE_RATIO_THRESHOLD}",
                    text_length=text_length,
                    unique_ratio=unique_ratio,
                )
            )

        duplicate_hash = _content_hash(stripped_text)
        # 只把后续副本标记为 duplicate_content，这样重复数表示冗余 chunk 数，
        # 而不是重复分组内的全部 chunk 数。
        if chunk_id in duplicate_chunk_ids_by_hash.get(duplicate_hash, set()):
            issues.append(
                ChunkQualityIssue(
                    chunk_id=chunk_id,
                    document_id=document_id,
                    issue_type="duplicate_content",
                    reason="chunk content hash already appeared in the same dataset",
                    text_length=text_length,
                    duplicate_hash=duplicate_hash,
                )
            )

    chunk_count = len(chunks)
    duplicate_chunk_count = sum(max(0, len(group) - 1) for group in duplicate_groups.values())
    # 临时数据集可以显式提供文档数；真实数据源如果不提供，
    # 则从 chunk 的 document_id 自动推导实际文档数。
    actual_document_count = _resolve_actual_document_count(payload, chunks)
    expected_document_count = _resolve_expected_document_count(payload, actual_document_count)

    return ChunkQualityEvaluationResult(
        dataset=dataset,
        dataset_id=str(payload.get("dataset_id", dataset)),
        user_type=str(payload.get("user_type", dataset)),
        document_metrics_mode=str(payload.get("document_metrics_mode", "simulated")),
        parent_chunk_size=parent_chunk_size,
        min_chunk_length_threshold=MIN_CHUNK_LENGTH,
        max_chunk_length_threshold=max_chunk_length,
        low_unique_ratio_threshold=LOW_UNIQUE_RATIO_THRESHOLD,
        document_metrics=DocumentIngestMetrics(
            expected_document_count=expected_document_count,
            actual_document_count=actual_document_count,
            document_ingest_completeness_rate=_document_completeness_rate(
                actual_document_count, expected_document_count
            ),
        ),
        chunk_metrics=ChunkQualityMetrics(
            chunk_count=chunk_count,
            duplicate_chunk_count=duplicate_chunk_count,
            min_chunk_length=min(lengths, default=0),
            max_chunk_length=max(lengths, default=0),
            avg_chunk_length=round(sum(lengths) / chunk_count, 2) if chunk_count else 0.0,
            low_quality_issue_count=len(issues),
            empty_chunk_count=empty_count,
            empty_chunk_rate=_rate(empty_count, chunk_count),
            too_short_chunk_count=too_short_count,
            too_short_chunk_rate=_rate(too_short_count, chunk_count),
            too_long_chunk_count=too_long_count,
            too_long_chunk_rate=_rate(too_long_count, chunk_count),
            low_unique_ratio_chunk_count=low_unique_count,
            low_unique_ratio_chunk_rate=_rate(low_unique_count, chunk_count),
            duplicate_group_count=len(duplicate_groups),
        ),
        low_quality_issues=issues,
    )


def _load_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        raise NotFoundException(f"chunk quality dataset file not found: {path}")
    with path.open("r", encoding="utf-8") as file:
        payload = json.load(file)
    if not isinstance(payload, dict):
        raise BadRequestException("chunk quality dataset root must be an object")
    return payload


def _build_duplicate_groups(chunks: list[Any]) -> dict[str, list[str]]:
    groups: dict[str, list[str]] = defaultdict(list)
    for index, chunk in enumerate(chunks):
        if not isinstance(chunk, dict):
            continue
        text = _string_value(chunk.get("text")).strip()
        if not text:
            continue
        chunk_id = _string_value(chunk.get("chunk_id"), fallback=f"chunk_{index + 1}")
        groups[_content_hash(text)].append(chunk_id)
    return {content_hash: ids for content_hash, ids in groups.items() if len(ids) > 1}


def _duplicate_chunk_ids_by_hash(duplicate_groups: dict[str, list[str]]) -> dict[str, set[str]]:
    return {content_hash: set(ids[1:]) for content_hash, ids in duplicate_groups.items()}


def _content_hash(text: str) -> str:
    # hash 前先统一换行符，避免不同平台换行造成误判。
    normalized = text.replace("\r\n", "\n").replace("\r", "\n").strip()
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def _is_table_chunk(chunk: dict[str, Any]) -> bool:
    if bool(chunk.get("is_table")):
        return True
    chunk_type = _string_value(chunk.get("chunk_type")).strip().lower()
    return chunk_type == "table"


def _unique_char_ratio(text: str) -> float:
    compact_text = "".join(text.split())
    if not compact_text:
        return 0.0
    return round(len(set(compact_text)) / len(compact_text), 4)


def _document_completeness_rate(actual_count: int, expected_count: int) -> float:
    if expected_count == 0:
        return 1.0 if actual_count == 0 else 0.0
    return _rate(actual_count, expected_count)


def _resolve_actual_document_count(payload: dict[str, Any], chunks: list[Any]) -> int:
    if "actual_document_count" in payload:
        return _non_negative_int(payload.get("actual_document_count"))
    # 兼容未来真实 chunk 数据集没有单独提供文档数的情况。
    document_ids = {
        str(chunk.get("document_id")).strip()
        for chunk in chunks
        if isinstance(chunk, dict) and str(chunk.get("document_id", "")).strip()
    }
    return len(document_ids)


def _resolve_expected_document_count(payload: dict[str, Any], actual_document_count: int) -> int:
    if "expected_document_count" in payload:
        return _non_negative_int(payload.get("expected_document_count"))
    return actual_document_count


def _rate(count: int, total: int) -> float:
    if total <= 0:
        return 0.0
    return round(count / total, 4)


def _string_value(value: Any, fallback: str = "") -> str:
    if value is None:
        return fallback
    return str(value)


def _nullable_string(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _positive_int(value: Any, fallback: int) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return fallback
    return parsed if parsed > 0 else fallback


def _non_negative_int(value: Any) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return 0
    return max(parsed, 0)
