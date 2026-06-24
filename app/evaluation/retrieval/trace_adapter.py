"""把 QAService 的检索调试结果转换成评估模块内部结构。

为什么要单独做 adapter：

- 生产检索链路返回的原始 payload 往往字段很多、层级也不稳定；
- 评估模块只关心少数字段，例如 faq_id、rule_id、rank、score；
- 通过 adapter 把原始 dict 收敛成稳定结构后，下游 scorer/runner 会更简单。
"""

from __future__ import annotations

from typing import Any

from app.evaluation.retrieval.schemas import FAQHit, KBHit, RetrievalTrace


def _safe_rank(index: int, item: dict[str, Any]) -> int:
    """读取命中结果的 rank。

    真实项目里，有的 payload 会显式带 `rank`，有的只保证结果顺序。
    为了让评估模块兼容两种情况，这里优先取 `item["rank"]`；
    如果没有，就退化成当前遍历顺序。
    """
    return int(item.get("rank") or index)


def _safe_score(item: dict[str, Any]) -> float | None:
    """兼容不同 payload 里的分数字段。

    当前三个指标并不直接使用 score 计算，但排查问题时需要把分数展示出来。
    这里优先尝试几类常见字段：

    - score
    - hybrid_score
    - rerank_score
    - dense_score

    如果都没有或类型不对，就返回 None。
    """
    for key in ("score", "hybrid_score", "rerank_score", "dense_score"):
        value = item.get(key)
        if value is not None:
            try:
                return float(value)
            except (TypeError, ValueError):
                return None
    return None


def build_retrieval_trace(case_id: str, question: str, payload: dict[str, Any]) -> RetrievalTrace:
    """把 debug_retrieval 返回值转换成统一 trace。

    FAQ 侧：
    - 主键尽量收敛成 `faq_id`

    文档侧：
    - 主键尽量收敛成 `rule_id`
    - chunk 级诊断信息保留在 `chunk_id`

    如果你的真实项目字段名不同，优先改这里，而不是改 scorer/runner。
    """
    faq_sources = list(payload.get("faq_sources") or [])
    doc_sources = list(payload.get("doc_sources") or [])

    faq_hits = [
        FAQHit(
            faq_id=str(item.get("faq_id") or item.get("metadata", {}).get("faq_id") or ""),
            rank=_safe_rank(index, item),
            score=_safe_score(item),
            question=str(
                item.get("metadata", {}).get("standard_question")
                or item.get("question")
                or ""
            )
            or None,
        )
        for index, item in enumerate(faq_sources, start=1)
        # 没有稳定 faq_id 的 FAQ 命中对当前评估指标没有意义，因此直接过滤掉。
        if str(item.get("faq_id") or item.get("metadata", {}).get("faq_id") or "").strip()
    ]

    kb_hits = [
        KBHit(
            rule_id=str(item.get("metadata", {}).get("rule_id") or item.get("rule_id") or ""),
            chunk_id=str(item.get("metadata", {}).get("chunk_id") or item.get("chunk_id") or "") or None,
            rank=_safe_rank(index, item),
            score=_safe_score(item),
            title=str(item.get("metadata", {}).get("title") or item.get("title") or "") or None,
            chunk_text_preview=str(item.get("content") or "")[:200] or None,
        )
        for index, item in enumerate(doc_sources, start=1)
        # 同理，没有 rule_id 的文档命中无法参与文档级 Recall/MRR 计算。
        if str(item.get("metadata", {}).get("rule_id") or item.get("rule_id") or "").strip()
    ]

    return RetrievalTrace(
        case_id=case_id,
        question=question,
        rewritten_query=str(payload.get("rewritten_query") or ""),
        faq_hits=faq_hits,
        kb_hits=kb_hits,
        raw_debug_payload=payload,
        error=str(payload.get("error") or ""),
    )
