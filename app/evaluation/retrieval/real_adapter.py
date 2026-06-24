"""Adapter from the project's real retrieval result to evaluation trace."""

from __future__ import annotations

from dataclasses import asdict
from typing import Any

from app.evaluation.retrieval.schemas import FAQHit, KBHit, RetrievalTrace
from app.schemas.retrieval import RetrievalEvidence, RetrievalResult


def build_trace_from_retrieval_result(
    *,
    case_id: str,
    question: str,
    result: RetrievalResult,
) -> RetrievalTrace:
    """Convert ``retrieve_answer`` output into the retrieval evaluation contract."""

    return RetrievalTrace(
        case_id=case_id,
        question=question,
        rewritten_query=result.debug.standalone_question,
        faq_hits=_faq_hits(result.faq_evidence),
        kb_hits=_kb_hits(result.doc_evidence),
        raw_debug_payload=build_retrieval_debug_payload(result),
    )


def build_retrieval_debug_payload(result: RetrievalResult) -> dict[str, Any]:
    """Build a JSON-safe payload for reports and case detail display."""

    return {
        "answer": result.answer,
        "hit_type": result.hit_type,
        "need_human_transfer": result.need_human_transfer,
        "metadata": result.metadata,
        "sources": result.sources,
        "faq_evidence": [_evidence_to_dict(item, rank=index) for index, item in enumerate(result.faq_evidence, start=1)],
        "doc_evidence": [_evidence_to_dict(item, rank=index) for index, item in enumerate(result.doc_evidence, start=1)],
        "final_evidence": [
            _evidence_to_dict(item, rank=index) for index, item in enumerate(result.final_evidence, start=1)
        ],
        "debug": result.debug.model_dump(mode="json"),
    }


def _faq_hits(items: list[RetrievalEvidence]) -> list[FAQHit]:
    hits: list[FAQHit] = []
    for index, item in enumerate(items, start=1):
        faq_id = str(item.evidence_id or item.metadata.get("faq_id") or "").strip()
        if not faq_id:
            continue
        hits.append(
            FAQHit(
                faq_id=faq_id,
                rank=index,
                score=item.score,
                question=item.title or item.text or None,
            )
        )
    return hits


def _kb_hits(items: list[RetrievalEvidence]) -> list[KBHit]:
    hits: list[KBHit] = []
    for index, item in enumerate(items, start=1):
        metadata = item.metadata or {}
        rule_id = str(metadata.get("rule_id") or item.source_doc_id or metadata.get("source_doc_id") or "").strip()
        if not rule_id:
            continue
        chunk_id = str(
            metadata.get("chunk_id")
            or metadata.get("child_chunk_id")
            or item.evidence_id
            or ""
        ).strip()
        preview_source = item.parent_content or item.text or ""
        hits.append(
            KBHit(
                rule_id=rule_id,
                chunk_id=chunk_id or None,
                rank=index,
                score=item.score,
                title=item.title,
                chunk_text_preview=preview_source[:200] or None,
            )
        )
    return hits


def _evidence_to_dict(item: RetrievalEvidence, *, rank: int) -> dict[str, Any]:
    data = item.model_dump(mode="json")
    data["rank"] = rank
    return data
