"""Retrieval runtime configuration ORM models."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import BigInteger, Boolean, DateTime, Float, Integer, JSON, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.models.base import BaseModel


class RetrievalHotConfig(BaseModel):
    __tablename__ = "retrieval_hot_configs"

    config_name: Mapped[str] = mapped_column(String(64), nullable=False, default="default", server_default="default", index=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    is_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default="1", index=True)
    created_by: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    updated_by: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    activated_by: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    activated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    faq_exact_match_max_length: Mapped[int] = mapped_column(Integer, nullable=False, default=48, server_default="48")
    faq_fast_retrieval_limit: Mapped[int] = mapped_column(Integer, nullable=False, default=5, server_default="5")
    faq_fast_dense_weight: Mapped[float] = mapped_column(Float, nullable=False, default=0.5, server_default="0.5")
    faq_fast_sparse_weight: Mapped[float] = mapped_column(Float, nullable=False, default=0.5, server_default="0.5")
    follow_up_max_length: Mapped[int] = mapped_column(Integer, nullable=False, default=10, server_default="10")
    recent_message_keep_count: Mapped[int] = mapped_column(Integer, nullable=False, default=8, server_default="8")
    history_summary_max_chars: Mapped[int] = mapped_column(Integer, nullable=False, default=800, server_default="800")
    variant_generation_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default="1")
    llm_variant_count: Mapped[int] = mapped_column(Integer, nullable=False, default=1, server_default="1")
    faq_candidate_limit_per_query: Mapped[int] = mapped_column(Integer, nullable=False, default=20, server_default="20")
    faq_fusion_top_k: Mapped[int] = mapped_column(Integer, nullable=False, default=20, server_default="20")
    faq_dense_weight: Mapped[float] = mapped_column(Float, nullable=False, default=0.5, server_default="0.5")
    faq_sparse_weight: Mapped[float] = mapped_column(Float, nullable=False, default=0.5, server_default="0.5")
    faq_rerank_top_k: Mapped[int] = mapped_column(Integer, nullable=False, default=3, server_default="3")
    faq_high_conf_threshold: Mapped[float] = mapped_column(Float, nullable=False, default=0.85, server_default="0.85")
    faq_middle_conf_threshold: Mapped[float] = mapped_column(Float, nullable=False, default=0.65, server_default="0.65")
    doc_candidate_limit_per_query: Mapped[int] = mapped_column(Integer, nullable=False, default=50, server_default="50")
    doc_fusion_top_k: Mapped[int] = mapped_column(Integer, nullable=False, default=20, server_default="20")
    doc_dense_weight: Mapped[float] = mapped_column(Float, nullable=False, default=0.7, server_default="0.7")
    doc_sparse_weight: Mapped[float] = mapped_column(Float, nullable=False, default=0.3, server_default="0.3")
    doc_rerank_top_k: Mapped[int] = mapped_column(Integer, nullable=False, default=5, server_default="5")
    doc_evidence_threshold: Mapped[float] = mapped_column(Float, nullable=False, default=0.55, server_default="0.55")
    final_evidence_top_k: Mapped[int] = mapped_column(Integer, nullable=False, default=6, server_default="6")


class RetrievalKeywordRule(BaseModel):
    __tablename__ = "retrieval_keyword_rules"

    rule_code: Mapped[str] = mapped_column(String(64), nullable=False, unique=True, index=True)
    rule_name: Mapped[str] = mapped_column(String(128), nullable=False)
    keywords_json: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    response_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    match_type: Mapped[str] = mapped_column(String(32), nullable=False, default="contains", server_default="contains")
    match_order: Mapped[int] = mapped_column(Integer, nullable=False, default=100, server_default="100", index=True)
    is_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default="1", index=True)
    created_by: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    updated_by: Mapped[int | None] = mapped_column(BigInteger, nullable=True)


class RetrievalTermNormalization(BaseModel):
    __tablename__ = "retrieval_term_normalizations"

    canonical_term: Mapped[str] = mapped_column(String(128), nullable=False, unique=True, index=True)
    aliases_json: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    match_type: Mapped[str] = mapped_column(String(32), nullable=False, default="contains", server_default="contains")
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    is_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default="1", index=True)
    created_by: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    updated_by: Mapped[int | None] = mapped_column(BigInteger, nullable=True)

    def alias_terms(self) -> list[str]:
        aliases = self.aliases_json or []
        return [term for term in aliases if isinstance(term, str) and term.strip()]
