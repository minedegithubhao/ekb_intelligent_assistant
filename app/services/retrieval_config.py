"""Retrieval runtime configuration service."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.config import ConfigManager
from app.core.exceptions import BadRequestException, NotFoundException
from app.db.models.retrieval_config import RetrievalHotConfig, RetrievalKeywordRule, RetrievalTermNormalization
from app.schemas.retrieval_config import (
    RetrievalHotConfigValues,
    RetrievalKeywordRuleSave,
    RetrievalTermNormalizationCreate,
    RetrievalTermNormalizationUpdate,
)

DEFAULT_CONFIG_NAME = "default"

HOT_CONFIG_FIELDS = tuple(RetrievalHotConfigValues.model_fields.keys())
STATIC_RETRIEVAL_FIELDS = {
    "model",
    "embedding_model",
    "embedding_model_path",
    "sparse_retrieval",
    "rerank_model",
    "rerank_model_path",
}
DEFAULT_HOT_CONFIG = RetrievalHotConfigValues().model_dump()
MATCH_TYPES = {"contains", "exact"}

DEFAULT_KEYWORD_RULES: tuple[dict[str, Any], ...] = (
    {
        "rule_code": "human_transfer",
        "rule_name": "转人工关键词集合",
        "keywords": ["转人工", "人工客服", "人工坐席客服"],
        "response_text": "现在为您转接人工客服，请稍后...",
        "match_order": 10,
    },
    {
        "rule_code": "out_of_scope",
        "rule_name": "越界关键词集合",
        "keywords": ["吃什么", "喝什么", "天气如何"],
        "response_text": "很抱歉，我是知识库 AI，您可以向我提问当前知识库相关的问题。",
        "match_order": 20,
    },
    {
        "rule_code": "greeting",
        "rule_name": "打招呼关键词集合",
        "keywords": ["你好", "嗨", "hello", "请问", "告诉我", "问一下"],
        "response_text": "你好，我是知识库 AI，有什么可以帮您？",
        "match_order": 30,
    },
    {
        "rule_code": "faq_fast_retrieval",
        "rule_name": "FAQ 检索关键词集合",
        "keywords": ["退款流程", "重置密码", "发票开错了"],
        "response_text": None,
        "match_order": 40,
    },
)
FIXED_KEYWORD_RULE_CODES = {item["rule_code"] for item in DEFAULT_KEYWORD_RULES}

DEFAULT_TERM_NORMALIZATIONS: tuple[dict[str, Any], ...] = (
    {"canonical_term": "笔记本电脑", "aliases": ["laptop", "lap top", "笔记型电脑"]},
    {"canonical_term": "CPU", "aliases": ["CPU", "中央处理器", "中央处理单元"]},
    {"canonical_term": "Wi-Fi", "aliases": ["Wi-Fi", "WIFI", "无线网络"]},
)

_effective_retrieval_cache: dict[str, Any] | None = None


def load_yaml_retrieval_config() -> dict[str, Any]:
    return ConfigManager().read_config_file("retrieval.yaml")


def get_active_hot_config(db: Session, config_name: str = DEFAULT_CONFIG_NAME) -> RetrievalHotConfig | None:
    return db.execute(
        select(RetrievalHotConfig)
        .where(
            RetrievalHotConfig.config_name == config_name,
            RetrievalHotConfig.is_enabled.is_(True),
            RetrievalHotConfig.is_deleted.is_(False),
        )
        .order_by(RetrievalHotConfig.activated_at.desc(), RetrievalHotConfig.created_at.desc(), RetrievalHotConfig.id.desc())
    ).scalars().first()


def get_effective_retrieval_config(
    db: Session,
    config_name: str = DEFAULT_CONFIG_NAME,
) -> tuple[dict[str, Any], RetrievalHotConfig | None, str]:
    yaml_config = load_yaml_retrieval_config()
    active_hot_config = get_active_hot_config(db, config_name=config_name)
    hot_config = _hot_config_to_values(active_hot_config) if active_hot_config else DEFAULT_HOT_CONFIG
    source = "retrieval_hot_configs" if active_hot_config else "defaults"
    return {**yaml_config, **hot_config}, active_hot_config, source


def refresh_effective_retrieval_cache(db: Session) -> dict[str, Any]:
    global _effective_retrieval_cache
    config, _, _ = get_effective_retrieval_config(db)
    _effective_retrieval_cache = config
    return config


def get_effective_retrieval_cache() -> dict[str, Any] | None:
    return _effective_retrieval_cache


def list_hot_configs(db: Session, config_name: str = DEFAULT_CONFIG_NAME) -> list[dict[str, Any]]:
    rows = db.execute(
        select(RetrievalHotConfig)
        .where(
            RetrievalHotConfig.config_name == config_name,
            RetrievalHotConfig.is_deleted.is_(False),
        )
        .order_by(RetrievalHotConfig.created_at.desc(), RetrievalHotConfig.id.desc())
    ).scalars()
    return [_hot_config_to_info(row) for row in rows]


def save_hot_config(
    db: Session,
    config: dict[str, Any],
    created_by: int | None,
    *,
    config_name: str = DEFAULT_CONFIG_NAME,
    description: str | None = None,
    activate: bool = True,
) -> RetrievalHotConfig:
    active = get_active_hot_config(db, config_name=config_name)
    base = _hot_config_to_values(active) if active else DEFAULT_HOT_CONFIG
    hot_config = _extract_hot_config(config, base=base)
    now = datetime.now(UTC)

    if activate:
        _disable_active_hot_configs(db, config_name)
    row = RetrievalHotConfig(
        config_name=config_name,
        description=description,
        is_enabled=activate,
        created_by=created_by,
        updated_by=created_by,
        activated_by=created_by if activate else None,
        activated_at=now if activate else None,
        **hot_config,
    )
    db.add(row)
    db.flush()
    if activate:
        refresh_effective_retrieval_cache(db)
    return row


def activate_hot_config(db: Session, config_id: int, activated_by: int | None) -> RetrievalHotConfig:
    row = db.execute(
        select(RetrievalHotConfig).where(
            RetrievalHotConfig.id == config_id,
            RetrievalHotConfig.is_deleted.is_(False),
        )
    ).scalar_one_or_none()
    if not row:
        raise NotFoundException("hot config not found")

    _disable_active_hot_configs(db, row.config_name)
    row.is_enabled = True
    row.updated_by = activated_by
    row.activated_by = activated_by
    row.activated_at = datetime.now(UTC)
    db.flush()
    refresh_effective_retrieval_cache(db)
    return row


def build_dashboard_payload(
    config: dict[str, Any],
    hot_config: RetrievalHotConfig | None,
    source: str,
) -> dict[str, Any]:
    hot_values = {field: config[field] for field in HOT_CONFIG_FIELDS}
    return {
        "source": source,
        "version": _hot_config_to_info(hot_config) if hot_config else None,
        "hot_config": _hot_config_to_info(hot_config) if hot_config else None,
        "model": config.get("model"),
        "embedding_model": config.get("embedding_model"),
        "sparse_retrieval": config.get("sparse_retrieval"),
        "rerank_model": config.get("rerank_model"),
        "variant_generation_enabled": config.get("variant_generation_enabled"),
        "query_variant": {
            "base_question_count": 1,
            "rule_variant_fixed_count": 1,
            "llm_variant_count": config.get("llm_variant_count"),
            "runtime_query_count": 2 + int(config.get("llm_variant_count", 0)),
        },
        "fast_faq": {
            "limit": config.get("faq_fast_retrieval_limit"),
            "dense_weight": config.get("faq_fast_dense_weight"),
            "sparse_weight": config.get("faq_fast_sparse_weight"),
        },
        "top_k": {
            "faq_candidate_limit_per_query": config.get("faq_candidate_limit_per_query"),
            "faq_fusion_top_k": config.get("faq_fusion_top_k"),
            "faq_rerank_top_k": config.get("faq_rerank_top_k"),
            "doc_candidate_limit_per_query": config.get("doc_candidate_limit_per_query"),
            "doc_fusion_top_k": config.get("doc_fusion_top_k"),
            "doc_rerank_top_k": config.get("doc_rerank_top_k"),
            "final_evidence_top_k": config.get("final_evidence_top_k"),
        },
        "thresholds": {
            "faq_high_conf": config.get("faq_high_conf_threshold"),
            "faq_middle_conf": config.get("faq_middle_conf_threshold"),
            "doc_evidence": config.get("doc_evidence_threshold"),
        },
        "weights": {
            "faq_dense": config.get("faq_dense_weight"),
            "faq_sparse": config.get("faq_sparse_weight"),
            "doc_dense": config.get("doc_dense_weight"),
            "doc_sparse": config.get("doc_sparse_weight"),
        },
        "raw": {**config},
        "hot_values": hot_values,
        "editable_fields": list(HOT_CONFIG_FIELDS),
    }


def list_keyword_rules(db: Session, *, include_disabled: bool = True) -> list[dict[str, Any]]:
    filters = [RetrievalKeywordRule.is_deleted.is_(False)]
    if not include_disabled:
        filters.append(RetrievalKeywordRule.is_enabled.is_(True))
    rows = db.execute(
        select(RetrievalKeywordRule)
        .where(*filters)
        .order_by(RetrievalKeywordRule.match_order.asc(), RetrievalKeywordRule.id.asc())
    ).scalars()
    return [keyword_rule_to_info(row) for row in rows]


def save_keyword_rule(
    db: Session,
    *,
    rule_code: str,
    payload: RetrievalKeywordRuleSave,
    updated_by: int | None,
) -> RetrievalKeywordRule:
    _validate_match_type(payload.match_type)
    keywords = _clean_terms(payload.keywords, field_name="keywords")
    normalized_code = _clean_code(rule_code)
    row = db.execute(
        select(RetrievalKeywordRule).where(RetrievalKeywordRule.rule_code == normalized_code)
    ).scalar_one_or_none()
    if row:
        row.rule_name = payload.rule_name.strip()
        row.keywords_json = keywords
        row.response_text = payload.response_text
        row.match_type = payload.match_type
        row.match_order = payload.match_order
        row.is_enabled = payload.is_enabled
        row.is_deleted = False
        row.updated_by = updated_by
    else:
        row = RetrievalKeywordRule(
            rule_code=normalized_code,
            rule_name=payload.rule_name.strip(),
            keywords_json=keywords,
            response_text=payload.response_text,
            match_type=payload.match_type,
            match_order=payload.match_order,
            is_enabled=payload.is_enabled,
            created_by=updated_by,
            updated_by=updated_by,
        )
        db.add(row)
    db.flush()
    return row


def update_keyword_rule_keywords(
    db: Session,
    *,
    rule_code: str,
    keywords: list[str],
    response_text: str | None,
    updated_by: int | None,
) -> RetrievalKeywordRule:
    normalized_code = _clean_code(rule_code)
    if normalized_code not in FIXED_KEYWORD_RULE_CODES:
        raise BadRequestException("keyword rule is not editable")
    row = db.execute(
        select(RetrievalKeywordRule).where(
            RetrievalKeywordRule.rule_code == normalized_code,
            RetrievalKeywordRule.is_deleted.is_(False),
        )
    ).scalar_one_or_none()
    if not row:
        raise NotFoundException("keyword rule not found")
    row.keywords_json = _clean_terms(keywords, field_name="keywords")
    row.response_text = _clean_optional_text(response_text)
    row.updated_by = updated_by
    db.flush()
    return row


def list_term_normalizations(db: Session, *, include_disabled: bool = True) -> list[dict[str, Any]]:
    filters = [RetrievalTermNormalization.is_deleted.is_(False)]
    if not include_disabled:
        filters.append(RetrievalTermNormalization.is_enabled.is_(True))
    rows = db.execute(
        select(RetrievalTermNormalization)
        .where(*filters)
        .order_by(RetrievalTermNormalization.id.asc())
    ).scalars()
    return [term_normalization_to_info(row) for row in rows]


def create_term_normalization(
    db: Session,
    *,
    payload: RetrievalTermNormalizationCreate,
    created_by: int | None,
) -> RetrievalTermNormalization:
    row = RetrievalTermNormalization(
        canonical_term=_clean_required_text(payload.canonical_term, "canonical_term"),
        aliases_json=_clean_terms(payload.aliases, field_name="aliases"),
        match_type="contains",
        description=payload.description,
        is_enabled=payload.is_enabled,
        created_by=created_by,
        updated_by=created_by,
    )
    db.add(row)
    try:
        db.flush()
    except IntegrityError as exc:
        raise BadRequestException("canonical term already exists") from exc
    return row


def update_term_normalization(
    db: Session,
    *,
    term_id: int,
    payload: RetrievalTermNormalizationUpdate,
    updated_by: int | None,
) -> RetrievalTermNormalization:
    row = _get_term_normalization(db, term_id)
    data = payload.model_dump(exclude_unset=True)
    if "canonical_term" in data and data["canonical_term"] is not None:
        row.canonical_term = _clean_required_text(data["canonical_term"], "canonical_term")
    if "aliases" in data and data["aliases"] is not None:
        row.aliases_json = _clean_terms(data["aliases"], field_name="aliases")
    if "description" in data:
        row.description = data["description"]
    if "is_enabled" in data and data["is_enabled"] is not None:
        row.is_enabled = data["is_enabled"]
    row.updated_by = updated_by
    try:
        db.flush()
    except IntegrityError as exc:
        raise BadRequestException("canonical term already exists") from exc
    return row


def delete_term_normalization(db: Session, *, term_id: int, updated_by: int | None) -> dict[str, bool]:
    row = _get_term_normalization(db, term_id)
    row.is_deleted = True
    row.is_enabled = False
    row.updated_by = updated_by
    db.flush()
    return {"deleted": True}


def _disable_active_hot_configs(db: Session, config_name: str) -> None:
    db.execute(
        update(RetrievalHotConfig)
        .where(
            RetrievalHotConfig.config_name == config_name,
            RetrievalHotConfig.is_enabled.is_(True),
            RetrievalHotConfig.is_deleted.is_(False),
        )
        .values(is_enabled=False)
    )


def _extract_hot_config(config: dict[str, Any], *, base: dict[str, Any]) -> dict[str, Any]:
    unsupported = sorted(set(config) - set(HOT_CONFIG_FIELDS) - STATIC_RETRIEVAL_FIELDS)
    if unsupported:
        raise BadRequestException(f"unsupported hot config fields: {', '.join(unsupported)}")
    candidate = {**base}
    candidate.update({field: config[field] for field in HOT_CONFIG_FIELDS if field in config})
    try:
        return RetrievalHotConfigValues.model_validate(candidate).model_dump()
    except ValueError as exc:
        raise BadRequestException(f"invalid retrieval hot config: {exc}") from exc


def _hot_config_to_values(config: RetrievalHotConfig) -> dict[str, Any]:
    values = {field: getattr(config, field) for field in HOT_CONFIG_FIELDS}
    return RetrievalHotConfigValues.model_validate(values).model_dump()


def _hot_config_to_info(config: RetrievalHotConfig) -> dict[str, Any]:
    values = _hot_config_to_values(config)
    return {
        "id": config.id,
        "config_name": config.config_name,
        "description": config.description,
        "is_enabled": config.is_enabled,
        "status": "active" if config.is_enabled else "standby",
        "version_no": config.id,
        "created_by": config.created_by,
        "updated_by": config.updated_by,
        "activated_by": config.activated_by,
        "activated_at": config.activated_at,
        "created_at": config.created_at,
        "updated_at": config.updated_at,
        **values,
    }


def keyword_rule_to_info(row: RetrievalKeywordRule) -> dict[str, Any]:
    return {
        "id": row.id,
        "rule_code": row.rule_code,
        "rule_name": row.rule_name,
        "keywords": row.keywords_json or [],
        "response_text": row.response_text,
        "match_type": row.match_type,
        "match_order": row.match_order,
        "is_enabled": row.is_enabled,
        "created_by": row.created_by,
        "updated_by": row.updated_by,
        "created_at": row.created_at,
        "updated_at": row.updated_at,
    }


def term_normalization_to_info(row: RetrievalTermNormalization) -> dict[str, Any]:
    return {
        "id": row.id,
        "canonical_term": row.canonical_term,
        "aliases": row.alias_terms(),
        "match_type": row.match_type,
        "description": row.description,
        "is_enabled": row.is_enabled,
        "created_by": row.created_by,
        "updated_by": row.updated_by,
        "created_at": row.created_at,
        "updated_at": row.updated_at,
    }


def _get_term_normalization(db: Session, term_id: int) -> RetrievalTermNormalization:
    row = db.execute(
        select(RetrievalTermNormalization).where(
            RetrievalTermNormalization.id == term_id,
            RetrievalTermNormalization.is_deleted.is_(False),
        )
    ).scalar_one_or_none()
    if not row:
        raise NotFoundException("term normalization not found")
    return row


def _clean_code(value: str) -> str:
    cleaned = value.strip()
    if not cleaned:
        raise BadRequestException("rule_code cannot be empty")
    return cleaned


def _clean_required_text(value: str, field_name: str) -> str:
    cleaned = value.strip()
    if not cleaned:
        raise BadRequestException(f"{field_name} cannot be empty")
    return cleaned


def _clean_optional_text(value: str | None) -> str | None:
    if value is None:
        return None
    cleaned = value.strip()
    return cleaned or None


def _clean_terms(values: list[str], *, field_name: str) -> list[str]:
    cleaned: list[str] = []
    seen: set[str] = set()
    for value in values:
        term = value.strip()
        if not term or term in seen:
            continue
        cleaned.append(term)
        seen.add(term)
    if not cleaned:
        raise BadRequestException(f"{field_name} cannot be empty")
    return cleaned


def _validate_match_type(match_type: str) -> None:
    if match_type not in MATCH_TYPES:
        raise BadRequestException("invalid match_type")
