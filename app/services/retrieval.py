"""Retrieval pipeline for FAQ and document hybrid search."""

from __future__ import annotations

import math
import os
import re
import shutil
import logging
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, replace
from functools import lru_cache
from pathlib import Path
from typing import Any, Literal

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.config import get_runtime_config
from app.core.exceptions import BadRequestException, ServiceUnavailableException
from app.schemas.retrieval import (
    ActiveKnowledgeVersion,
    QueryVariants,
    RetrievalDebugInfo,
    RetrievalEvidence,
    RetrievalResult,
)
from app.schemas.retrieval_config import RetrievalHotConfigValues
from app.services.retrieval_config import (
    HOT_CONFIG_FIELDS,
    get_effective_retrieval_config,
    list_keyword_rules,
    list_term_normalizations,
)

KNOWLEDGE_BASE_TYPES = {"enterprise", "personal"}
KNOWLEDGE_BASE_TYPE_TO_SCOPE = {
    "enterprise": "enterprise",
    "personal": "personal_individual",
}
DIRECT_RULE_CODES = {"greeting", "out_of_scope", "human_transfer"}
FAQ_FAST_RULE_CODE = "faq_fast_retrieval"
DEFAULT_DENSE_FIELD = "dense"
DEFAULT_SPARSE_FIELD = "sparse"
DEFAULT_TEXT_FIELD = "text"
logger = logging.getLogger(__name__)

LLMVariantGenerator = Callable[[str, int], Sequence[str]]
FollowUpRewriter = Callable[[str, Sequence[Mapping[str, Any]], RetrievalHotConfigValues], str | None]
AnswerGenerator = Callable[[str, Sequence[RetrievalEvidence]], str]
ProgressCallback = Callable[[dict[str, Any]], None]


@dataclass(frozen=True)
class KeywordRule:
    rule_code: str
    rule_name: str
    keywords: tuple[str, ...]
    response_text: str | None
    match_type: str
    match_order: int


@dataclass(frozen=True)
class TermNormalization:
    canonical_term: str
    aliases: tuple[str, ...]


@dataclass(frozen=True)
class RetrievalContext:
    hot: RetrievalHotConfigValues
    keyword_rules: tuple[KeywordRule, ...]
    term_normalizations: tuple[TermNormalization, ...]
    knowledge_base: ActiveKnowledgeVersion | None
    knowledge_base_type: str


@dataclass(frozen=True)
class SearchHit:
    source_type: Literal["faq", "doc"]
    key: str
    text: str
    score: float
    metadata: dict[str, Any]


def _emit_progress(callback: ProgressCallback | None, **payload: Any) -> None:
    if callback is None:
        return
    try:
        callback(payload)
    except Exception as exc:  # noqa: BLE001 - progress reporting must not break retrieval.
        logger.warning("retrieval progress callback failed: %s", exc)


def retrieve_answer(
    db: Session,
    *,
    question: str,
    knowledge_base_type: str,
    history_messages: Sequence[Mapping[str, Any]] | None = None,
    hot_config_overrides: Mapping[str, Any] | RetrievalHotConfigValues | None = None,
    kb_version: str | None = None,
    knowledge_base: ActiveKnowledgeVersion | None = None,
    follow_up_rewriter: FollowUpRewriter | None = None,
    llm_variant_generator: LLMVariantGenerator | None = None,
    answer_generator: AnswerGenerator | None = None,
    progress_callback: ProgressCallback | None = None,
) -> RetrievalResult:
    """Run the retrieval pipeline and return an answer/evidence bundle.

    The API layer should call this function from the conversation service. It does not write
    conversation messages and does not depend on FastAPI request objects.
    """

    raw_question = question.strip()
    if not raw_question:
        raise BadRequestException("question cannot be empty")
    normalized_type = _normalize_knowledge_base_type(knowledge_base_type)

    # 先加载运行上下文：默认读取 MySQL 热参数；评估调用可覆盖热参数或指定知识库版本。
    ctx = load_retrieval_context(
        db,
        knowledge_base_type=normalized_type,
        require_knowledge_base=False,
        hot_config_overrides=hot_config_overrides,
        kb_version=kb_version,
        knowledge_base=knowledge_base,
    )
    follow_up_rewriter = follow_up_rewriter or _default_follow_up_rewriter
    llm_variant_generator = llm_variant_generator or _default_llm_variant_generator
    answer_generator = answer_generator or _default_answer_generator

    # 归一化问题用于规则匹配；standalone_question 是真正参与后续检索的问题。
    normalized_question = normalize_question(raw_question)
    _emit_progress(progress_callback, stage="rule_match", label="规则匹配", status="running")
    rule_hit = _match_first_rule(normalized_question, ctx.keyword_rules)
    _emit_progress(
        progress_callback,
        stage="rule_match",
        label="规则匹配",
        status="completed",
        hit=bool(rule_hit),
        rule_code=rule_hit.rule_code if rule_hit else None,
        judgement=_judgement_from_hit_type(f"rule_{rule_hit.rule_code}") if rule_hit else "未命中规则",
    )
    standalone_question = _rewrite_follow_up(
        raw_question,
        history_messages or [],
        ctx.hot,
        follow_up_rewriter=follow_up_rewriter,
    )

    debug = _base_debug(
        ctx=ctx,
        normalized_question=normalized_question,
        standalone_question=standalone_question,
        rule_hit_type=rule_hit.rule_code if rule_hit else None,
        follow_up_rewritten=standalone_question != raw_question,
    )

    # 打招呼、越界、转人工等规则命中后可直接返回，不要求知识库版本存在。
    if rule_hit and rule_hit.rule_code in DIRECT_RULE_CODES:
        _emit_progress(progress_callback, stage="faq_fast_match", label="FAQ快速匹配", status="skipped", reason="规则直接命中")
        _emit_progress(progress_callback, stage="faq_hybrid_search", label="FAQ混合检索", status="skipped", reason="规则直接命中")
        _emit_progress(progress_callback, stage="doc_hybrid_search", label="文档混合检索", status="skipped", reason="规则直接命中")
        _emit_progress(
            progress_callback,
            stage="answer_generation",
            label="答案生成",
            status="completed",
            hit_type=f"rule_{rule_hit.rule_code}",
            judgement=_judgement_from_hit_type(f"rule_{rule_hit.rule_code}"),
        )
        return _direct_rule_result(rule_hit, debug)

    # 只有进入真实 FAQ / 文档检索时，才必须确定知识库版本和 collection 名称。
    ctx = _ensure_knowledge_base(db, ctx)
    debug.knowledge_base = ctx.knowledge_base
    knowledge_base = ctx.knowledge_base

    # FAQ 快速检索用于短问题精确命中，命中标准 FAQ 后直接返回。
    if _should_run_fast_faq(rule_hit, normalized_question, ctx.hot):
        _emit_progress(progress_callback, stage="faq_fast_match", label="FAQ快速匹配", status="running")
        fast_hit = _faq_fast_exact_match(ctx, standalone_question)
        _emit_progress(
            progress_callback,
            stage="faq_fast_match",
            label="FAQ快速匹配",
            status="completed",
            hit=bool(fast_hit),
            candidate_count=1 if fast_hit else 0,
        )
        if fast_hit:
            evidence = _hit_to_evidence(fast_hit, confidence=1.0)
            _emit_progress(
                progress_callback,
                stage="faq_hybrid_search",
                label="FAQ混合检索",
                status="skipped",
                reason="FAQ快速匹配已命中",
            )
            _emit_progress(
                progress_callback,
                stage="doc_hybrid_search",
                label="文档混合检索",
                status="skipped",
                reason="FAQ快速匹配已命中",
            )
            _emit_progress(
                progress_callback,
                stage="answer_generation",
                label="答案生成",
                status="completed",
                hit_type="faq_fast",
                judgement=_judgement_from_hit_type("faq_fast"),
            )
            return _faq_answer_result(
                hit_type="faq_fast",
                answer=evidence.answer or evidence.text,
                faq_evidence=[evidence],
                doc_evidence=[],
                debug=debug,
                metadata={"faq_fast_exact_match": True},
            )
    else:
        _emit_progress(
            progress_callback,
            stage="faq_fast_match",
            label="FAQ快速匹配",
            status="skipped",
            reason="未命中FAQ快速匹配规则或问题超过长度限制",
        )

    # 生成 1 条基础问题、1 条规则变体和 N 条 LLM 变体，之后所有变体都参与混合检索。
    variants = build_query_variants(
        standalone_question,
        ctx.term_normalizations,
        ctx.hot,
        llm_variant_generator=llm_variant_generator,
    )
    debug.query_variants = variants

    # 先查 FAQ collection：多 query 混合检索、合并去重、rerank，再根据置信度决定是否直接返回。
    _emit_progress(progress_callback, stage="faq_hybrid_search", label="FAQ混合检索", status="running")
    faq_hits = _search_multi_query(
        ctx=ctx,
        source_type="faq",
        collection_name=knowledge_base.faq_collection_name,
        queries=variants.query_variants,
        per_query_limit=ctx.hot.faq_candidate_limit_per_query,
        fusion_top_k=ctx.hot.faq_fusion_top_k,
        dense_weight=ctx.hot.faq_dense_weight,
        sparse_weight=ctx.hot.faq_sparse_weight,
    )
    faq_evidence = _rerank_and_trim(
        standalone_question,
        faq_hits,
        source_type="faq",
        top_k=ctx.hot.faq_rerank_top_k,
    )
    _emit_progress(
        progress_callback,
        stage="faq_hybrid_search",
        label="FAQ混合检索",
        status="completed",
        candidate_count=len(faq_hits),
        evidence_count=len(faq_evidence),
        best_confidence=_best_confidence(faq_evidence),
    )

    best_faq = faq_evidence[0] if faq_evidence else None
    if best_faq and best_faq.confidence >= ctx.hot.faq_high_conf_threshold:
        _emit_progress(progress_callback, stage="doc_hybrid_search", label="文档混合检索", status="skipped", reason="FAQ高置信命中")
        _emit_progress(
            progress_callback,
            stage="answer_generation",
            label="答案生成",
            status="completed",
            hit_type="faq_high",
            judgement=_judgement_from_hit_type("faq_high"),
        )
        return _faq_answer_result(
            hit_type="faq_high",
            answer=best_faq.answer or best_faq.text,
            faq_evidence=faq_evidence,
            doc_evidence=[],
            debug=debug,
        )

    # FAQ 未达到高置信时继续查文档 collection，用文档证据支撑复杂或长尾问题回答。
    _emit_progress(progress_callback, stage="doc_hybrid_search", label="文档混合检索", status="running")
    doc_hits = _search_multi_query(
        ctx=ctx,
        source_type="doc",
        collection_name=knowledge_base.doc_collection_name,
        queries=variants.query_variants,
        per_query_limit=ctx.hot.doc_candidate_limit_per_query,
        fusion_top_k=ctx.hot.doc_fusion_top_k,
        dense_weight=ctx.hot.doc_dense_weight,
        sparse_weight=ctx.hot.doc_sparse_weight,
    )
    doc_evidence = [
        item
        for item in _rerank_and_trim(
            standalone_question,
            doc_hits,
            source_type="doc",
            top_k=ctx.hot.doc_rerank_top_k,
        )
        if item.confidence >= ctx.hot.doc_evidence_threshold
    ]
    _emit_progress(
        progress_callback,
        stage="doc_hybrid_search",
        label="文档混合检索",
        status="completed",
        candidate_count=len(doc_hits),
        evidence_count=len(doc_evidence),
        best_confidence=_best_confidence(doc_evidence),
    )

    # FAQ 中置信时保留 FAQ 证据，并与文档证据一起进入最终生成。
    if best_faq and best_faq.confidence >= ctx.hot.faq_middle_conf_threshold:
        evidence_for_answer = [best_faq, *doc_evidence]
        _emit_progress(progress_callback, stage="answer_generation", label="答案生成", status="running")
        result = _evidence_answer_result(
            hit_type="faq_middle_doc",
            question=standalone_question,
            faq_evidence=faq_evidence,
            doc_evidence=doc_evidence,
            debug=debug,
            answer_generator=answer_generator,
            final_top_k=ctx.hot.final_evidence_top_k,
            evidence_for_answer=evidence_for_answer,
        )
        _emit_progress(
            progress_callback,
            stage="answer_generation",
            label="答案生成",
            status="completed",
            hit_type=result.hit_type,
            judgement=_judgement_from_hit_type(result.hit_type),
            source_count=len(result.sources),
        )
        return result

    # FAQ 低置信时丢弃 FAQ 证据，仅用文档证据生成回答。
    if doc_evidence:
        _emit_progress(progress_callback, stage="answer_generation", label="答案生成", status="running")
        result = _evidence_answer_result(
            hit_type="doc",
            question=standalone_question,
            faq_evidence=[],
            doc_evidence=doc_evidence,
            debug=debug,
            answer_generator=answer_generator,
            final_top_k=ctx.hot.final_evidence_top_k,
            evidence_for_answer=doc_evidence,
        )
        _emit_progress(
            progress_callback,
            stage="answer_generation",
            label="答案生成",
            status="completed",
            hit_type=result.hit_type,
            judgement=_judgement_from_hit_type(result.hit_type),
            source_count=len(result.sources),
        )
        return result

    # FAQ 和文档都没有可靠证据时，返回无命中结果。
    _emit_progress(
        progress_callback,
        stage="answer_generation",
        label="答案生成",
        status="skipped",
        hit_type="none",
        judgement=_judgement_from_hit_type("none"),
    )
    return RetrievalResult(
        answer="未检索到足够相关的知识库内容，请换一种说法再试。",
        hit_type="none",
        need_human_transfer=False,
        sources=[],
        faq_evidence=[],
        doc_evidence=[],
        metadata={"need_human_transfer": False},
        debug=debug,
    )


def inspect_retrieval_candidates(
    db: Session,
    *,
    question: str,
    knowledge_base_type: str,
    hot_config_overrides: Mapping[str, Any] | RetrievalHotConfigValues | None = None,
    kb_version: str | None = None,
) -> dict[str, Any]:
    """Return reranked FAQ/Doc candidates before confidence-threshold filtering."""

    raw_question = question.strip()
    if not raw_question:
        raise BadRequestException("question cannot be empty")
    normalized_type = _normalize_knowledge_base_type(knowledge_base_type)
    ctx = load_retrieval_context(
        db,
        knowledge_base_type=normalized_type,
        require_knowledge_base=False,
        hot_config_overrides=hot_config_overrides,
        kb_version=kb_version,
    )
    normalized_question = normalize_question(raw_question)
    rule_hit = _match_first_rule(normalized_question, ctx.keyword_rules)
    standalone_question = _rewrite_follow_up(raw_question, [], ctx.hot, follow_up_rewriter=None)

    base = {
        "normalized_question": normalized_question,
        "standalone_question": standalone_question,
        "rule_hit_type": rule_hit.rule_code if rule_hit else None,
        "knowledge_base_type": normalized_type,
        "thresholds": {
            "faq_high_conf_threshold": ctx.hot.faq_high_conf_threshold,
            "faq_middle_conf_threshold": ctx.hot.faq_middle_conf_threshold,
            "doc_evidence_threshold": ctx.hot.doc_evidence_threshold,
        },
        "hot_config": ctx.hot.model_dump(),
        "knowledge_base": None,
        "query_variants": {
            "base_question": standalone_question,
            "rule_variant_question": standalone_question,
            "llm_variant_questions": [],
            "query_variants": [standalone_question],
        },
        "faq_candidates": [],
        "doc_candidates": [],
    }
    if rule_hit and rule_hit.rule_code in DIRECT_RULE_CODES:
        return base

    ctx = _ensure_knowledge_base(db, ctx)
    if ctx.knowledge_base is not None:
        base["knowledge_base"] = ctx.knowledge_base.model_dump(mode="json")

    variants = build_query_variants(standalone_question, ctx.term_normalizations, ctx.hot)
    base["query_variants"] = variants.model_dump(mode="json")

    faq_hits = _search_multi_query(
        ctx=ctx,
        source_type="faq",
        collection_name=ctx.knowledge_base.faq_collection_name,
        queries=variants.query_variants,
        per_query_limit=ctx.hot.faq_candidate_limit_per_query,
        fusion_top_k=ctx.hot.faq_fusion_top_k,
        dense_weight=ctx.hot.faq_dense_weight,
        sparse_weight=ctx.hot.faq_sparse_weight,
    )
    faq_candidates = _rerank_and_trim(
        standalone_question,
        faq_hits,
        source_type="faq",
        top_k=ctx.hot.faq_rerank_top_k,
    )

    doc_hits = _search_multi_query(
        ctx=ctx,
        source_type="doc",
        collection_name=ctx.knowledge_base.doc_collection_name,
        queries=variants.query_variants,
        per_query_limit=ctx.hot.doc_candidate_limit_per_query,
        fusion_top_k=ctx.hot.doc_fusion_top_k,
        dense_weight=ctx.hot.doc_dense_weight,
        sparse_weight=ctx.hot.doc_sparse_weight,
    )
    doc_candidates = _rerank_and_trim(
        standalone_question,
        doc_hits,
        source_type="doc",
        top_k=ctx.hot.doc_rerank_top_k,
    )

    base["faq_candidates"] = [
        {
            **item.model_dump(mode="json"),
            "passed_high_threshold": item.confidence >= ctx.hot.faq_high_conf_threshold,
            "passed_middle_threshold": item.confidence >= ctx.hot.faq_middle_conf_threshold,
        }
        for item in faq_candidates
    ]
    base["doc_candidates"] = [
        {
            **item.model_dump(mode="json"),
            "passed_threshold": item.confidence >= ctx.hot.doc_evidence_threshold,
        }
        for item in doc_candidates
    ]
    return base


def load_retrieval_context(
    db: Session,
    *,
    knowledge_base_type: str,
    require_knowledge_base: bool = True,
    hot_config_overrides: Mapping[str, Any] | RetrievalHotConfigValues | None = None,
    kb_version: str | None = None,
    knowledge_base: ActiveKnowledgeVersion | None = None,
) -> RetrievalContext:
    normalized_type = _normalize_knowledge_base_type(knowledge_base_type)
    config, _, _ = get_effective_retrieval_config(db)
    hot = _build_hot_config(config, hot_config_overrides)
    resolved_knowledge_base = _resolve_knowledge_base(
        db,
        require_knowledge_base=require_knowledge_base,
        kb_version=kb_version,
        knowledge_base=knowledge_base,
    )
    return RetrievalContext(
        hot=hot,
        keyword_rules=_load_keyword_rules(db),
        term_normalizations=_load_term_normalizations(db),
        knowledge_base=resolved_knowledge_base,
        knowledge_base_type=normalized_type,
    )


def _ensure_knowledge_base(db: Session, ctx: RetrievalContext) -> RetrievalContext:
    if ctx.knowledge_base is not None:
        return ctx
    return replace(ctx, knowledge_base=get_active_knowledge_version(db))


def _build_hot_config(
    config: Mapping[str, Any],
    overrides: Mapping[str, Any] | RetrievalHotConfigValues | None,
) -> RetrievalHotConfigValues:
    if isinstance(overrides, RetrievalHotConfigValues):
        return overrides
    hot_values = {field: config[field] for field in HOT_CONFIG_FIELDS}
    if overrides:
        unsupported = sorted(set(overrides) - set(HOT_CONFIG_FIELDS))
        if unsupported:
            raise BadRequestException(f"unsupported hot config override fields: {', '.join(unsupported)}")
        hot_values.update({field: overrides[field] for field in HOT_CONFIG_FIELDS if field in overrides})
    try:
        return RetrievalHotConfigValues.model_validate(hot_values)
    except ValueError as exc:
        raise BadRequestException(f"invalid retrieval hot config overrides: {exc}") from exc


def _resolve_knowledge_base(
    db: Session,
    *,
    require_knowledge_base: bool,
    kb_version: str | None,
    knowledge_base: ActiveKnowledgeVersion | None,
) -> ActiveKnowledgeVersion | None:
    if knowledge_base is not None:
        if kb_version and knowledge_base.kb_version != kb_version:
            raise BadRequestException("kb_version and knowledge_base.kb_version do not match")
        return knowledge_base
    if kb_version:
        return get_knowledge_version(db, kb_version=kb_version)
    if require_knowledge_base:
        return get_active_knowledge_version(db)
    return None


def get_knowledge_version(db: Session, *, kb_version: str) -> ActiveKnowledgeVersion:
    cleaned_version = kb_version.strip()
    if not cleaned_version:
        raise BadRequestException("kb_version cannot be empty")
    row = db.execute(
        text(
            """
            SELECT kb_version, faq_collection_name, doc_collection_name, status
            FROM kb_versions
            WHERE kb_version = :kb_version
              AND faq_collection_name IS NOT NULL
              AND doc_collection_name IS NOT NULL
            LIMIT 1
            """
        ),
        {"kb_version": cleaned_version},
    ).mappings().first()
    if row is None:
        raise BadRequestException("knowledge base version not found or missing collections")
    return ActiveKnowledgeVersion.model_validate(dict(row))


def get_active_knowledge_version(db: Session) -> ActiveKnowledgeVersion:
    row = db.execute(
        text(
            """
            SELECT v.kb_version, v.faq_collection_name, v.doc_collection_name, v.status
            FROM kb_version_pointers p
            JOIN kb_versions v ON v.kb_version = p.kb_active_version
            WHERE v.status = 'active'
              AND v.faq_collection_name IS NOT NULL
              AND v.doc_collection_name IS NOT NULL
            ORDER BY p.updated_at DESC, p.id DESC
            LIMIT 1
            """
        )
    ).mappings().first()
    if row is None:
        row = db.execute(
            text(
                """
                SELECT kb_version, faq_collection_name, doc_collection_name, status
                FROM kb_versions
                WHERE status = 'active'
                  AND faq_collection_name IS NOT NULL
                  AND doc_collection_name IS NOT NULL
                ORDER BY created_at DESC, id DESC
                LIMIT 1
                """
            )
        ).mappings().first()
    if row is None:
        raise ServiceUnavailableException("active knowledge base version is not configured")
    return ActiveKnowledgeVersion.model_validate(dict(row))


def normalize_question(question: str) -> str:
    return re.sub(r"\s+", "", question.strip()).lower()


def build_query_variants(
    standalone_question: str,
    term_normalizations: Sequence[TermNormalization],
    hot: RetrievalHotConfigValues,
    *,
    llm_variant_generator: LLMVariantGenerator | None = None,
) -> QueryVariants:
    base_question = standalone_question
    rule_variant_question = apply_term_normalizations(base_question, term_normalizations)
    llm_variant_questions: list[str] = []
    if hot.variant_generation_enabled and hot.llm_variant_count > 0 and llm_variant_generator:
        try:
            generated = llm_variant_generator(base_question, hot.llm_variant_count)
            llm_variant_questions = _unique_non_empty(generated)[: hot.llm_variant_count]
        except Exception:
            llm_variant_questions = []
    query_variants = _clean_non_empty([base_question, rule_variant_question, *llm_variant_questions])
    return QueryVariants(
        base_question=base_question,
        rule_variant_question=rule_variant_question,
        llm_variant_questions=llm_variant_questions,
        query_variants=query_variants,
    )


def apply_term_normalizations(question: str, term_normalizations: Sequence[TermNormalization]) -> str:
    result = question
    replacements: list[tuple[str, str]] = []
    for item in term_normalizations:
        for alias in item.aliases:
            replacements.append((alias, item.canonical_term))
    replacements.sort(key=lambda item: len(item[0]), reverse=True)
    for alias, canonical in replacements:
        if not alias or alias == canonical:
            continue
        result = re.sub(re.escape(alias), canonical, result, flags=re.IGNORECASE)
    return result


def _rewrite_follow_up(
    question: str,
    history_messages: Sequence[Mapping[str, Any]],
    hot: RetrievalHotConfigValues,
    *,
    follow_up_rewriter: FollowUpRewriter | None,
) -> str:
    if not follow_up_rewriter or not history_messages:
        return question
    if len(normalize_question(question)) > hot.follow_up_max_length:
        return question
    keep_count = hot.recent_message_keep_count
    recent_messages = list(history_messages)[-keep_count:] if keep_count > 0 else []
    if not recent_messages:
        return question
    try:
        rewritten = follow_up_rewriter(question, recent_messages, hot)
    except Exception:
        return question
    cleaned = (rewritten or "").strip()
    return cleaned or question


def _load_keyword_rules(db: Session) -> tuple[KeywordRule, ...]:
    rules: list[KeywordRule] = []
    for row in list_keyword_rules(db, include_disabled=False):
        keywords = tuple(str(item).strip() for item in row.get("keywords", []) if str(item).strip())
        if not keywords:
            continue
        rules.append(
            KeywordRule(
                rule_code=str(row["rule_code"]),
                rule_name=str(row["rule_name"]),
                keywords=keywords,
                response_text=row.get("response_text"),
                match_type=str(row.get("match_type") or "contains"),
                match_order=int(row.get("match_order") or 100),
            )
        )
    return tuple(sorted(rules, key=lambda item: item.match_order))


def _load_term_normalizations(db: Session) -> tuple[TermNormalization, ...]:
    terms: list[TermNormalization] = []
    for row in list_term_normalizations(db, include_disabled=False):
        aliases = tuple(str(item).strip() for item in row.get("aliases", []) if str(item).strip())
        canonical = str(row.get("canonical_term") or "").strip()
        if canonical and aliases:
            terms.append(TermNormalization(canonical_term=canonical, aliases=aliases))
    return tuple(terms)


def _match_first_rule(question: str, rules: Sequence[KeywordRule]) -> KeywordRule | None:
    for rule in rules:
        if _rule_matches(question, rule):
            return rule
    return None


def _rule_matches(question: str, rule: KeywordRule) -> bool:
    normalized_keywords = [normalize_question(keyword) for keyword in rule.keywords]
    if rule.match_type == "exact":
        return any(question == keyword for keyword in normalized_keywords)
    return any(keyword and keyword in question for keyword in normalized_keywords)


def _should_run_fast_faq(
    rule_hit: KeywordRule | None,
    normalized_question: str,
    hot: RetrievalHotConfigValues,
) -> bool:
    return (
        rule_hit is not None
        and rule_hit.rule_code == FAQ_FAST_RULE_CODE
        and len(normalized_question) <= hot.faq_exact_match_max_length
    )


def _faq_fast_exact_match(ctx: RetrievalContext, question: str) -> SearchHit | None:
    if ctx.knowledge_base is None:
        raise ServiceUnavailableException("active knowledge base version is not configured")
    hits = _search_multi_query(
        ctx=ctx,
        source_type="faq",
        collection_name=ctx.knowledge_base.faq_collection_name,
        queries=[question],
        per_query_limit=ctx.hot.faq_fast_retrieval_limit,
        fusion_top_k=ctx.hot.faq_fast_retrieval_limit,
        dense_weight=ctx.hot.faq_fast_dense_weight,
        sparse_weight=ctx.hot.faq_fast_sparse_weight,
    )
    normalized_question = normalize_question(question)
    for hit in hits:
        candidate_question = str(hit.metadata.get("standard_question") or hit.text)
        if normalize_question(candidate_question) == normalized_question:
            return hit
    return None


def _search_multi_query(
    *,
    ctx: RetrievalContext,
    source_type: Literal["faq", "doc"],
    collection_name: str,
    queries: Sequence[str],
    per_query_limit: int,
    fusion_top_k: int,
    dense_weight: float,
    sparse_weight: float,
) -> list[SearchHit]:
    retriever = MilvusHybridRetriever(collection_name=collection_name)
    expr = _build_milvus_expr(ctx)
    merged: dict[str, SearchHit] = {}
    for query in _unique_non_empty(queries):
        hits = retriever.hybrid_search(
            query=query,
            source_type=source_type,
            limit=per_query_limit,
            dense_weight=dense_weight,
            sparse_weight=sparse_weight,
            expr=expr,
        )
        for hit in hits:
            previous = merged.get(hit.key)
            if previous is None or hit.score > previous.score:
                merged[hit.key] = hit
    return sorted(merged.values(), key=lambda item: item.score, reverse=True)[:fusion_top_k]


class MilvusHybridRetriever:
    def __init__(self, *, collection_name: str) -> None:
        self.collection_name = collection_name
        self.config = get_runtime_config().app.milvus

    def hybrid_search(
        self,
        *,
        query: str,
        source_type: Literal["faq", "doc"],
        limit: int,
        dense_weight: float,
        sparse_weight: float,
        expr: str,
    ) -> list[SearchHit]:
        from pymilvus import AnnSearchRequest, Collection, WeightedRanker, connections

        self._connect(connections)
        collection = Collection(self.collection_name, using=self.config.alias)
        collection.load()
        dense_metric = self._dense_metric(collection)
        dense_req = AnnSearchRequest(
            data=[embed_query(query)],
            anns_field=DEFAULT_DENSE_FIELD,
            param={"metric_type": dense_metric, "params": {}},
            limit=limit,
            expr=expr,
        )
        sparse_req = AnnSearchRequest(
            data=[query],
            anns_field=DEFAULT_SPARSE_FIELD,
            param={"metric_type": "BM25", "params": {}},
            limit=limit,
            expr=expr,
        )
        results = collection.hybrid_search(
            reqs=[dense_req, sparse_req],
            rerank=WeightedRanker(float(dense_weight), float(sparse_weight)),
            limit=limit,
            output_fields=_output_fields(source_type),
        )
        return [_milvus_hit_to_search_hit(hit, source_type=source_type) for hit in results[0]]

    def _connect(self, connections: Any) -> None:
        kwargs = {
            "alias": self.config.alias,
            "host": self.config.host,
            "port": str(self.config.port),
        }
        database = getattr(self.config, "database", None)
        if database:
            kwargs["db_name"] = database
        try:
            current = connections.get_connection_addr(self.config.alias)
        except Exception:
            current = None
        if current:
            current_db = current.get("db_name") or current.get("database")
            if (
                str(current.get("host")) == str(self.config.host)
                and str(current.get("port")) == str(self.config.port)
                and (not database or current_db == database)
            ):
                return
            connections.disconnect(self.config.alias)
        connections.connect(**kwargs)

    @staticmethod
    def _dense_metric(collection: Any) -> str:
        for index in collection.indexes:
            data = index.to_dict()
            if data.get("field") == DEFAULT_DENSE_FIELD:
                return str(data.get("index_param", {}).get("metric_type") or "L2")
        return "L2"


def _output_fields(source_type: Literal["faq", "doc"]) -> list[str]:
    common = [
        "pk",
        DEFAULT_TEXT_FIELD,
        "kb_version",
        "source",
        "reference_source",
        "title",
        "record_type",
    ]
    if source_type == "faq":
        return [*common, "faq_id", "standard_question", "answer"]
    return [
        *common,
        "doc_id",
        "chunk_id",
        "child_chunk_id",
        "source_doc_id",
        "parent_id",
        "parent_content",
        "title_path",
        "file_name",
    ]


@lru_cache(maxsize=1)
def _embedding_model() -> Any:
    os.environ.setdefault("TOKENIZERS_PARALLELISM", "false")
    from langchain_huggingface import HuggingFaceEmbeddings

    model_path = _require_path(get_runtime_config().retrieval.embedding_model_path, "embedding model")
    return HuggingFaceEmbeddings(
        model_name=str(model_path),
        model_kwargs={"device": _device(), "local_files_only": True},
        encode_kwargs={"normalize_embeddings": True},
    )


def embed_query(query: str) -> list[float]:
    return list(_embedding_model().embed_query(query))


@lru_cache(maxsize=1)
def _reranker_model() -> Any:
    from sentence_transformers import CrossEncoder

    model_path = _require_path(get_runtime_config().retrieval.rerank_model_path, "reranker model")
    vocab_file = model_path / "sentencepiece.bpe.model"
    tokenizer_kwargs = {"use_fast": False}
    if vocab_file.exists():
        tokenizer_kwargs["vocab_file"] = str(_cached_sentencepiece_vocab(model_path, vocab_file))
    return CrossEncoder(
        str(model_path),
        device=_device(),
        local_files_only=True,
        tokenizer_kwargs=tokenizer_kwargs,
    )


def _cached_sentencepiece_vocab(model_path: Path, vocab_file: Path) -> Path:
    """Copy SentencePiece vocab to an ASCII cache path for Windows Chinese-path compatibility."""

    try:
        cache_root = Path(os.getenv("KNOWFORGE_MODEL_CACHE", "D:/knowforge_model_cache"))
        cache_dir = cache_root / model_path.name
        cache_dir.mkdir(parents=True, exist_ok=True)
        cached = cache_dir / vocab_file.name
        if not cached.exists() or cached.stat().st_mtime < vocab_file.stat().st_mtime:
            shutil.copy2(vocab_file, cached)
        return cached
    except Exception as exc:  # noqa: BLE001 - fallback keeps existing local model loading behavior.
        logger.warning("failed to cache sentencepiece vocab for reranker: %s", exc)
        return vocab_file


def _device() -> str:
    try:
        import torch

        return "cuda" if torch.cuda.is_available() else "cpu"
    except Exception:
        return "cpu"


def _require_path(path: str, label: str) -> Path:
    resolved = Path(path)
    if not resolved.exists():
        raise ServiceUnavailableException(f"{label} path does not exist: {resolved}")
    return resolved


def _rerank_and_trim(
    query: str,
    hits: Sequence[SearchHit],
    *,
    source_type: Literal["faq", "doc"],
    top_k: int,
) -> list[RetrievalEvidence]:
    if not hits:
        return []
    reranked_hits = list(hits)
    try:
        pairs = [(query, hit.text) for hit in reranked_hits]
        scores = [float(score) for score in _reranker_model().predict(pairs)]
        reranked_hits = [
            SearchHit(
                source_type=hit.source_type,
                key=hit.key,
                text=hit.text,
                score=score,
                metadata=hit.metadata,
            )
            for hit, score in zip(reranked_hits, scores, strict=False)
        ]
    except Exception as exc:
        # If the local reranker is unavailable, preserve Milvus hybrid ranking.
        logger.warning("reranker unavailable, fallback to Milvus hybrid scores: %s", exc)
    reranked_hits.sort(key=lambda item: item.score, reverse=True)
    return [_hit_to_evidence(hit, confidence=_score_to_confidence(hit.score)) for hit in reranked_hits[:top_k]]


def _milvus_hit_to_search_hit(hit: Any, *, source_type: Literal["faq", "doc"]) -> SearchHit:
    entity = hit.entity
    metadata: dict[str, Any] = {}
    for field in _output_fields(source_type):
        try:
            value = entity.get(field)
        except Exception:
            value = None
        if value is not None:
            metadata[field] = value
    text_value = str(metadata.get(DEFAULT_TEXT_FIELD) or "")
    if source_type == "faq":
        key = str(metadata.get("faq_id") or metadata.get("pk") or hit.id)
    else:
        key = str(metadata.get("chunk_id") or metadata.get("child_chunk_id") or metadata.get("pk") or hit.id)
    return SearchHit(
        source_type=source_type,
        key=key,
        text=text_value,
        score=float(hit.distance),
        metadata=metadata,
    )


def _hit_to_evidence(hit: SearchHit, *, confidence: float) -> RetrievalEvidence:
    metadata = dict(hit.metadata)
    if hit.source_type == "faq":
        evidence_id = str(metadata.get("faq_id") or hit.key)
        return RetrievalEvidence(
            source_type="faq",
            evidence_id=evidence_id,
            text=hit.text,
            score=hit.score,
            confidence=confidence,
            answer=_clean_text(metadata.get("answer")),
            reference_source=_clean_text(metadata.get("reference_source")),
            title=_clean_text(metadata.get("standard_question") or metadata.get("title")),
            metadata=metadata,
        )
    evidence_id = str(metadata.get("chunk_id") or metadata.get("child_chunk_id") or hit.key)
    return RetrievalEvidence(
        source_type="doc",
        evidence_id=evidence_id,
        text=hit.text,
        score=hit.score,
        confidence=confidence,
        parent_content=_clean_text(metadata.get("parent_content")),
        source_doc_id=_clean_text(metadata.get("source_doc_id") or metadata.get("doc_id")),
        reference_source=_clean_text(metadata.get("reference_source")),
        title=_clean_text(metadata.get("title_path") or metadata.get("title")),
        metadata=metadata,
    )


def _score_to_confidence(score: float) -> float:
    if 0 <= score <= 1:
        return score
    return 1 / (1 + math.exp(-score))


def _best_confidence(evidence: Sequence[RetrievalEvidence]) -> float | None:
    if not evidence:
        return None
    return max(float(item.confidence) for item in evidence)


def _judgement_from_hit_type(hit_type: str) -> str:
    mapping = {
        "rule_greeting": "问候语",
        "rule_human_transfer": "请求人工",
        "rule_out_of_scope": "越界问题",
        "faq_fast": "FAQ快速匹配",
        "faq_high": "FAQ高置信匹配",
        "faq_middle_doc": "FAQ中置信+文档混合检索",
        "doc": "文档混合检索",
        "none": "未命中",
        "retrieval_error": "检索异常",
    }
    return mapping.get(hit_type, hit_type)


def _direct_rule_result(rule: KeywordRule, debug: RetrievalDebugInfo) -> RetrievalResult:
    need_human_transfer = rule.rule_code == "human_transfer"
    answer = rule.response_text or ""
    return RetrievalResult(
        answer=answer,
        hit_type=f"rule_{rule.rule_code}",
        need_human_transfer=need_human_transfer,
        sources=[],
        faq_evidence=[],
        doc_evidence=[],
        metadata={
            "rule_code": rule.rule_code,
            "rule_name": rule.rule_name,
            "need_human_transfer": need_human_transfer,
        },
        debug=debug,
    )


def _faq_answer_result(
    *,
    hit_type: str,
    answer: str,
    faq_evidence: list[RetrievalEvidence],
    doc_evidence: list[RetrievalEvidence],
    debug: RetrievalDebugInfo,
    metadata: dict[str, Any] | None = None,
) -> RetrievalResult:
    return RetrievalResult(
        answer=answer,
        hit_type=hit_type,
        need_human_transfer=False,
        sources=[_evidence_to_source(item) for item in [*faq_evidence, *doc_evidence]],
        faq_evidence=faq_evidence,
        doc_evidence=doc_evidence,
        final_evidence=[*faq_evidence, *doc_evidence],
        metadata=metadata or {},
        debug=debug,
    )


def _evidence_answer_result(
    *,
    hit_type: str,
    question: str,
    faq_evidence: list[RetrievalEvidence],
    doc_evidence: list[RetrievalEvidence],
    debug: RetrievalDebugInfo,
    answer_generator: AnswerGenerator | None,
    final_top_k: int,
    evidence_for_answer: Sequence[RetrievalEvidence],
) -> RetrievalResult:
    final_evidence = _final_rerank(question, evidence_for_answer, top_k=final_top_k)
    metadata: dict[str, Any] = {}
    if answer_generator:
        try:
            answer = answer_generator(question, final_evidence)
            generated = True
        except Exception as exc:
            answer = _fallback_evidence_answer(final_evidence)
            generated = False
            metadata["answer_generation_error"] = str(exc)
    else:
        answer = _fallback_evidence_answer(final_evidence)
        generated = False
    metadata["answer_generated"] = generated
    return RetrievalResult(
        answer=answer,
        hit_type=hit_type,
        need_human_transfer=False,
        sources=[_evidence_to_source(item) for item in final_evidence],
        faq_evidence=faq_evidence,
        doc_evidence=doc_evidence,
        final_evidence=final_evidence,
        metadata=metadata,
        debug=debug,
    )


def _fallback_evidence_answer(evidence: Sequence[RetrievalEvidence]) -> str:
    if not evidence:
        return "已完成检索，但没有可用于回答的证据。"
    chunks: list[str] = []
    for index, item in enumerate(evidence[:3], start=1):
        content = item.answer or item.parent_content or item.text
        chunks.append(f"{index}. {content}")
    return "已检索到相关知识库内容，待接入最终生成模型后可组织为正式回答：\n" + "\n".join(chunks)


def _final_rerank(
    query: str,
    evidence: Sequence[RetrievalEvidence],
    *,
    top_k: int,
) -> list[RetrievalEvidence]:
    items = list(evidence)
    if not items:
        return []
    try:
        pairs = [(query, _evidence_text_for_rerank(item)) for item in items]
        scores = [float(score) for score in _reranker_model().predict(pairs)]
        items = [
            item.model_copy(
                update={
                    "score": score,
                    "confidence": _score_to_confidence(score),
                }
            )
            for item, score in zip(items, scores, strict=False)
        ]
        items.sort(key=lambda item: item.score, reverse=True)
    except Exception as exc:
        logger.warning("final reranker unavailable, preserve evidence order: %s", exc)
    return items[:top_k]


def _evidence_text_for_rerank(evidence: RetrievalEvidence) -> str:
    return evidence.answer or evidence.parent_content or evidence.text


def _evidence_to_source(evidence: RetrievalEvidence) -> dict[str, Any]:
    return {
        "source_type": evidence.source_type,
        "id": evidence.evidence_id,
        "score": evidence.score,
        "confidence": evidence.confidence,
        "title": evidence.title,
        "reference_source": evidence.reference_source,
        "source_doc_id": evidence.source_doc_id,
        "text": evidence.answer or evidence.parent_content or evidence.text,
    }


def _base_debug(
    *,
    ctx: RetrievalContext,
    normalized_question: str,
    standalone_question: str,
    rule_hit_type: str | None,
    follow_up_rewritten: bool,
) -> RetrievalDebugInfo:
    return RetrievalDebugInfo(
        normalized_question=normalized_question,
        standalone_question=standalone_question,
        query_variants=QueryVariants(
            base_question=standalone_question,
            rule_variant_question=standalone_question,
            llm_variant_questions=[],
            query_variants=[standalone_question],
        ),
        rule_hit_type=rule_hit_type,
        follow_up_rewritten=follow_up_rewritten,
        knowledge_base=ctx.knowledge_base,
        hot_config=ctx.hot.model_dump(),
    )


def _build_milvus_expr(ctx: RetrievalContext) -> str:
    if ctx.knowledge_base is None:
        raise ServiceUnavailableException("active knowledge base version is not configured")
    scope = KNOWLEDGE_BASE_TYPE_TO_SCOPE[ctx.knowledge_base_type]
    return (
        f'kb_version == "{_escape_expr_value(ctx.knowledge_base.kb_version)}" '
        f'and scope == "{_escape_expr_value(scope)}"'
    )


def _escape_expr_value(value: str) -> str:
    return value.replace("\\", "\\\\").replace('"', '\\"')


def _normalize_knowledge_base_type(knowledge_base_type: str) -> str:
    if knowledge_base_type not in KNOWLEDGE_BASE_TYPES:
        raise BadRequestException("invalid knowledge_base_type")
    return knowledge_base_type


def _unique_non_empty(values: Sequence[str]) -> list[str]:
    unique: list[str] = []
    seen: set[str] = set()
    for value in values:
        cleaned = str(value).strip()
        if not cleaned or cleaned in seen:
            continue
        unique.append(cleaned)
        seen.add(cleaned)
    return unique


def _clean_non_empty(values: Sequence[str]) -> list[str]:
    return [str(value).strip() for value in values if str(value).strip()]


def _clean_text(value: Any) -> str | None:
    if value is None:
        return None
    cleaned = str(value).strip()
    return cleaned or None


def _default_llm_variant_generator(question: str, count: int) -> Sequence[str]:
    from app.services.llm import generate_query_variants

    return generate_query_variants(question, count)


def _default_follow_up_rewriter(
    question: str,
    history_messages: Sequence[Mapping[str, Any]],
    hot: RetrievalHotConfigValues,
) -> str | None:
    from app.services.llm import rewrite_follow_up_question

    return rewrite_follow_up_question(question, history_messages, hot)


def _default_answer_generator(question: str, evidence: Sequence[RetrievalEvidence]) -> str:
    from app.services.llm import generate_answer

    return generate_answer(question, evidence)
