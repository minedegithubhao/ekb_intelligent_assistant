"""Schemas for retrieval runtime configuration APIs."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, model_validator


class RetrievalHotConfigValues(BaseModel):
    faq_exact_match_max_length: int = Field(default=48, ge=1)
    faq_fast_retrieval_limit: int = Field(default=5, ge=1)
    faq_fast_dense_weight: float = Field(default=0.5, ge=0, le=1)
    faq_fast_sparse_weight: float = Field(default=0.5, ge=0, le=1)
    follow_up_max_length: int = Field(default=10, ge=1)
    recent_message_keep_count: int = Field(default=8, ge=0)
    history_summary_max_chars: int = Field(default=800, ge=1)
    variant_generation_enabled: bool = True
    llm_variant_count: int = Field(default=1, ge=0)
    faq_candidate_limit_per_query: int = Field(default=20, ge=1)
    faq_fusion_top_k: int = Field(default=20, ge=1)
    faq_dense_weight: float = Field(default=0.5, ge=0, le=1)
    faq_sparse_weight: float = Field(default=0.5, ge=0, le=1)
    faq_rerank_top_k: int = Field(default=3, ge=1)
    faq_high_conf_threshold: float = Field(default=0.85, ge=0, le=1)
    faq_middle_conf_threshold: float = Field(default=0.65, ge=0, le=1)
    doc_candidate_limit_per_query: int = Field(default=50, ge=1)
    doc_fusion_top_k: int = Field(default=20, ge=1)
    doc_dense_weight: float = Field(default=0.7, ge=0, le=1)
    doc_sparse_weight: float = Field(default=0.3, ge=0, le=1)
    doc_rerank_top_k: int = Field(default=5, ge=1)
    doc_evidence_threshold: float = Field(default=0.55, ge=0, le=1)
    final_evidence_top_k: int = Field(default=6, ge=1)

    @model_validator(mode="after")
    def validate_relationships(self) -> "RetrievalHotConfigValues":
        _validate_weight_pair(self.faq_fast_dense_weight, self.faq_fast_sparse_weight, "FAQ fast")
        _validate_weight_pair(self.faq_dense_weight, self.faq_sparse_weight, "FAQ")
        _validate_weight_pair(self.doc_dense_weight, self.doc_sparse_weight, "Doc")
        if self.faq_high_conf_threshold < self.faq_middle_conf_threshold:
            raise ValueError("faq_high_conf_threshold must be greater than or equal to faq_middle_conf_threshold")
        if self.faq_rerank_top_k > self.faq_fusion_top_k:
            raise ValueError("faq_rerank_top_k must be less than or equal to faq_fusion_top_k")
        if self.doc_rerank_top_k > self.doc_fusion_top_k:
            raise ValueError("doc_rerank_top_k must be less than or equal to doc_fusion_top_k")
        return self


class RetrievalHotConfigCreate(RetrievalHotConfigValues):
    config_name: str = Field(default="default", min_length=1, max_length=64)
    description: str | None = Field(default=None, max_length=500)
    is_enabled: bool = True


class RetrievalHotConfigInfo(RetrievalHotConfigCreate):
    model_config = ConfigDict(from_attributes=True)

    id: int
    status: str
    created_by: int | None = None
    updated_by: int | None = None
    activated_by: int | None = None
    activated_at: datetime | None = None
    created_at: datetime
    updated_at: datetime


class RetrievalKeywordRuleSave(BaseModel):
    rule_name: str = Field(min_length=1, max_length=128)
    keywords: list[str] = Field(min_length=1)
    response_text: str | None = None
    match_type: str = Field(default="contains", max_length=32)
    match_order: int = Field(default=100, ge=1)
    is_enabled: bool = True


class RetrievalKeywordRuleKeywordsUpdate(BaseModel):
    keywords: list[str] = Field(min_length=1)


class RetrievalKeywordRuleInfo(RetrievalKeywordRuleSave):
    id: int
    rule_code: str
    created_by: int | None = None
    updated_by: int | None = None
    created_at: datetime
    updated_at: datetime


class RetrievalTermNormalizationCreate(BaseModel):
    canonical_term: str = Field(min_length=1, max_length=128)
    aliases: list[str] = Field(min_length=1)
    description: str | None = Field(default=None, max_length=500)
    is_enabled: bool = True


class RetrievalTermNormalizationUpdate(BaseModel):
    canonical_term: str | None = Field(default=None, min_length=1, max_length=128)
    aliases: list[str] | None = Field(default=None, min_length=1)
    description: str | None = Field(default=None, max_length=500)
    is_enabled: bool | None = None


class RetrievalTermNormalizationInfo(BaseModel):
    id: int
    canonical_term: str
    aliases: list[str]
    match_type: str
    description: str | None = None
    is_enabled: bool
    created_by: int | None = None
    updated_by: int | None = None
    created_at: datetime
    updated_at: datetime


def _validate_weight_pair(dense_weight: float, sparse_weight: float, label: str) -> None:
    if abs((dense_weight + sparse_weight) - 1.0) > 0.000001:
        raise ValueError(f"{label} dense and sparse weights must sum to 1")
