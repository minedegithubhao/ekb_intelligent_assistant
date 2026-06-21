"""Pydantic schemas for hot-update retrieval strategy parameters."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class RetrievalHotConfigValues(BaseModel):
    """Only contains parameters that can take effect without rebuilding models."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    variant_generation_enabled: bool
    rerank_enabled: bool
    rule_variant_count: int = Field(ge=0)
    llm_variant_count: int = Field(ge=0)
    query_variant_total: int = Field(ge=1)

    faq_exact_match_max_length: int = Field(ge=1)
    follow_up_max_length: int = Field(ge=1)
    recent_message_keep_count: int = Field(ge=0)
    history_summary_boundary_round: int = Field(ge=1)
    history_summary_max_chars: int = Field(ge=1)

    faq_dense_top_k_exact: int = Field(ge=0)
    faq_sparse_top_k_exact: int = Field(ge=0)
    faq_fetch_k: int = Field(ge=1)
    faq_k: int = Field(ge=1)
    doc_fetch_k: int = Field(ge=1)
    doc_k: int = Field(ge=1)
    rerank_top_k: int = Field(ge=1)
    faq_rerank_top_k: int = Field(ge=1)
    doc_rerank_top_k: int = Field(ge=1)
    final_evidence_top_k: int = Field(ge=1)

    faq_dense_weight: float = Field(ge=0, le=1)
    faq_sparse_weight: float = Field(ge=0, le=1)
    doc_dense_weight: float = Field(ge=0, le=1)
    doc_sparse_weight: float = Field(ge=0, le=1)

    faq_high_conf_threshold: float = Field(ge=0, le=1)
    faq_middle_conf_threshold: float = Field(ge=0, le=1)
    doc_evidence_threshold: float = Field(ge=0, le=1)

    rule_hit_priority: list[str] = Field(min_length=1)
    faq_exact_match_policy: str = Field(min_length=1, max_length=64)
    standby_keep_days: int = Field(ge=0)
    standby_min_keep_versions: int = Field(ge=0)


class RetrievalHotConfigCreate(RetrievalHotConfigValues):
    """Complete payload for creating a disabled config history row."""


class RetrievalHotConfigRead(RetrievalHotConfigValues):
    """Hot config snapshot returned from MySQL or in-memory cache."""

    model_config = ConfigDict(extra="forbid", from_attributes=True, frozen=True)

    id: int
    config_name: str
    is_enabled: bool
    created_by: int | None = None
    created_at: datetime | None = None
