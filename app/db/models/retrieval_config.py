"""ORM model for historical hot-update retrieval strategy parameters."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import BigInteger, Boolean, DateTime, Float, ForeignKey, Integer, JSON, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.models.base import Base


class RetrievalHotConfig(Base):
    """Each row is a config version; the enabled latest row is active."""

    __tablename__ = "retrieval_hot_configs"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    is_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default="1")
    config_name: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    created_by: Mapped[int | None] = mapped_column(
        BigInteger,
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )

    variant_generation_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default="1")
    rerank_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default="1")
    rule_variant_count: Mapped[int] = mapped_column(Integer, nullable=False)
    llm_variant_count: Mapped[int] = mapped_column(Integer, nullable=False)
    query_variant_total: Mapped[int] = mapped_column(Integer, nullable=False)

    faq_exact_match_max_length: Mapped[int] = mapped_column(Integer, nullable=False)
    follow_up_max_length: Mapped[int] = mapped_column(Integer, nullable=False)
    recent_message_keep_count: Mapped[int] = mapped_column(Integer, nullable=False)
    history_summary_boundary_round: Mapped[int] = mapped_column(Integer, nullable=False)
    history_summary_max_chars: Mapped[int] = mapped_column(Integer, nullable=False)

    faq_dense_top_k_exact: Mapped[int] = mapped_column(Integer, nullable=False)
    faq_sparse_top_k_exact: Mapped[int] = mapped_column(Integer, nullable=False)
    faq_fetch_k: Mapped[int] = mapped_column(Integer, nullable=False)
    faq_k: Mapped[int] = mapped_column(Integer, nullable=False)
    doc_fetch_k: Mapped[int] = mapped_column(Integer, nullable=False)
    doc_k: Mapped[int] = mapped_column(Integer, nullable=False)
    rerank_top_k: Mapped[int] = mapped_column(Integer, nullable=False)
    faq_rerank_top_k: Mapped[int] = mapped_column(Integer, nullable=False)
    doc_rerank_top_k: Mapped[int] = mapped_column(Integer, nullable=False)
    final_evidence_top_k: Mapped[int] = mapped_column(Integer, nullable=False)

    faq_dense_weight: Mapped[float] = mapped_column(Float, nullable=False)
    faq_sparse_weight: Mapped[float] = mapped_column(Float, nullable=False)
    doc_dense_weight: Mapped[float] = mapped_column(Float, nullable=False)
    doc_sparse_weight: Mapped[float] = mapped_column(Float, nullable=False)

    faq_high_conf_threshold: Mapped[float] = mapped_column(Float, nullable=False)
    faq_middle_conf_threshold: Mapped[float] = mapped_column(Float, nullable=False)
    doc_evidence_threshold: Mapped[float] = mapped_column(Float, nullable=False)

    rule_hit_priority: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    faq_exact_match_policy: Mapped[str] = mapped_column(String(64), nullable=False)
    standby_keep_days: Mapped[int] = mapped_column(Integer, nullable=False)
    standby_min_keep_versions: Mapped[int] = mapped_column(Integer, nullable=False)
