"""Schemas for retrieval pipeline service results."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field


class ActiveKnowledgeVersion(BaseModel):
    kb_version: str
    faq_collection_name: str
    doc_collection_name: str
    status: str


class QueryVariants(BaseModel):
    base_question: str
    rule_variant_question: str
    llm_variant_questions: list[str] = Field(default_factory=list)
    query_variants: list[str] = Field(default_factory=list)


class RetrievalEvidence(BaseModel):
    source_type: Literal["faq", "doc"]
    evidence_id: str
    text: str
    score: float
    confidence: float
    answer: str | None = None
    parent_content: str | None = None
    source_doc_id: str | None = None
    reference_source: str | None = None
    title: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class RetrievalDebugInfo(BaseModel):
    normalized_question: str
    standalone_question: str
    query_variants: QueryVariants
    rule_hit_type: str | None = None
    follow_up_rewritten: bool = False
    knowledge_base: ActiveKnowledgeVersion | None = None
    hot_config: dict[str, Any] = Field(default_factory=dict)


class RetrievalResult(BaseModel):
    answer: str
    hit_type: str = "none"
    need_human_transfer: bool = False
    sources: list[dict[str, Any]] = Field(default_factory=list)
    faq_evidence: list[RetrievalEvidence] = Field(default_factory=list)
    doc_evidence: list[RetrievalEvidence] = Field(default_factory=list)
    final_evidence: list[RetrievalEvidence] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)
    debug: RetrievalDebugInfo
