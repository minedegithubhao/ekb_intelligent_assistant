"""Request and response schemas for admin evaluation APIs."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


EVALUATION_TYPES = {"ingestion_quality", "retrieval_eval", "end_to_end", "mixed"}
RUN_STATUSES = {"pending", "running", "success", "failed"}


class EvaluationDatasetCreate(BaseModel):
    dataset_id: str = Field(min_length=1, max_length=64)
    name: str = Field(min_length=1, max_length=128)
    evaluation_type: str = Field(default="retrieval_eval", max_length=32)
    description: str | None = None


class EvaluationDatasetInfo(BaseModel):
    id: int
    dataset_id: str
    name: str
    evaluation_type: str
    description: str | None = None
    sample_count: int = 0
    created_at: datetime


class EvaluationCaseImportItem(BaseModel):
    case_id: str = Field(min_length=1, max_length=64)
    question: str = Field(min_length=1)
    expected_json: dict[str, Any] | None = None
    category: str | None = Field(default=None, max_length=64)


class EvaluationCasesImport(BaseModel):
    items: list[EvaluationCaseImportItem] = Field(min_length=1)
    overwrite: bool = True


class EvaluationCaseInfo(BaseModel):
    id: int
    case_id: str
    dataset_id: str
    question: str
    expected_json: dict[str, Any] | None = None
    category: str | None = None
    created_at: datetime


class IngestionQualityRunCreate(BaseModel):
    dataset: str = Field(default="enterprise", description="Temporary chunk dataset key, such as enterprise or personal.")
    knowledge_base_version: str | None = Field(default=None, max_length=64)
    min_length: int | None = Field(default=None, ge=0)
    max_length: int | None = Field(default=None, ge=1)
    duplicate_threshold: float | None = Field(default=None, ge=0, le=1)


class RetrievalRunCreate(BaseModel):
    dataset_id: str = Field(min_length=1, max_length=64)
    knowledge_base_version: str | None = Field(default=None, max_length=64)
    faq_top_k: int = Field(default=5, ge=1, le=100)
    kb_top_k: int = Field(default=10, ge=1, le=100)
    mock_mode: bool = True


class EvaluationRunInfo(BaseModel):
    id: int
    run_id: str
    dataset_id: str | None = None
    evaluation_type: str
    knowledge_base_version: str | None = None
    config_json: dict[str, Any] | None = None
    status: str
    summary_json: dict[str, Any] | None = None
    detail_json: dict[str, Any] | None = None
    created_at: datetime
    finished_at: datetime | None = None
    metrics_text: str = ""


class EvaluationCaseResultInfo(BaseModel):
    id: int
    run_id: str
    case_id: str
    question: str | None = None
    expected_json: dict[str, Any] | None = None
    retrieved_items_json: dict[str, Any] | None = None
    metric_results_json: dict[str, Any] | None = None
    actual_answer: str | None = None
    latency_json: dict[str, Any] | None = None
    created_at: datetime
