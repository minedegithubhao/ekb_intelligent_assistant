"""Admin retrieval hot configuration service.

仪表台参数当前只维护 retrieval_hot_configs 里的热参数。
模型名称、模型路径等静态参数仍从 config/retrieval.yaml 读取，只用于展示和兜底。
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.core.config import ConfigManager, RetrievalConfig
from app.core.exceptions import BadRequestException, NotFoundException
from app.db.models.retrieval_config import RetrievalHotConfig

DEFAULT_CONFIG_NAME = "default"

HOT_CONFIG_FIELDS = (
    "variant_generation_enabled",
    "rerank_enabled",
    "rule_variant_count",
    "llm_variant_count",
    "query_variant_total",
    "faq_exact_match_max_length",
    "follow_up_max_length",
    "recent_message_keep_count",
    "history_summary_boundary_round",
    "history_summary_max_chars",
    "faq_dense_top_k_exact",
    "faq_sparse_top_k_exact",
    "faq_fetch_k",
    "faq_k",
    "doc_fetch_k",
    "doc_k",
    "rerank_top_k",
    "faq_rerank_top_k",
    "doc_rerank_top_k",
    "final_evidence_top_k",
    "faq_dense_weight",
    "faq_sparse_weight",
    "doc_dense_weight",
    "doc_sparse_weight",
    "faq_high_conf_threshold",
    "faq_middle_conf_threshold",
    "doc_evidence_threshold",
    "rule_hit_priority",
    "faq_exact_match_policy",
    "standby_keep_days",
    "standby_min_keep_versions",
)

_effective_retrieval_cache: dict[str, Any] | None = None


def load_yaml_retrieval_config() -> dict[str, Any]:
    return ConfigManager().read_config_file("retrieval.yaml")


def _hot_config_to_dict(config: RetrievalHotConfig) -> dict[str, Any]:
    return {field: getattr(config, field) for field in HOT_CONFIG_FIELDS}


def _extract_hot_config(config: dict[str, Any]) -> dict[str, Any]:
    hot_config = {field: config[field] for field in HOT_CONFIG_FIELDS if field in config}
    missing = [field for field in HOT_CONFIG_FIELDS if field not in hot_config]
    if missing:
        raise BadRequestException(f"missing hot config fields: {', '.join(missing)}")
    _validate_weight_pair(hot_config, "faq_dense_weight", "faq_sparse_weight", "FAQ")
    _validate_weight_pair(hot_config, "doc_dense_weight", "doc_sparse_weight", "Doc")
    return hot_config


def _validate_weight_pair(config: dict[str, Any], dense_key: str, sparse_key: str, label: str) -> None:
    total = float(config[dense_key]) + float(config[sparse_key])
    if abs(total - 1.0) > 0.000001:
        raise BadRequestException(f"{label} dense and sparse weights must sum to 1")


def _validate_retrieval_config(config: dict[str, Any]) -> dict[str, Any]:
    try:
        RetrievalConfig.model_validate(config)
    except Exception as exc:
        raise BadRequestException(f"invalid retrieval config: {exc}") from exc
    return config


def get_active_hot_config(db: Session, config_name: str = DEFAULT_CONFIG_NAME) -> RetrievalHotConfig | None:
    return db.execute(
        select(RetrievalHotConfig)
        .where(
            RetrievalHotConfig.config_name == config_name,
            RetrievalHotConfig.is_enabled.is_(True),
        )
        .order_by(RetrievalHotConfig.created_at.desc(), RetrievalHotConfig.id.desc())
    ).scalars().first()


def get_effective_retrieval_config(
    db: Session,
    config_name: str = DEFAULT_CONFIG_NAME,
) -> tuple[dict[str, Any], RetrievalHotConfig | None, str]:
    yaml_config = load_yaml_retrieval_config()
    active_hot_config = get_active_hot_config(db, config_name=config_name)
    if active_hot_config:
        merged = {**yaml_config, **_hot_config_to_dict(active_hot_config)}
        return _validate_retrieval_config(merged), active_hot_config, "retrieval_hot_configs"
    return _validate_retrieval_config(yaml_config), None, "yaml"


def refresh_effective_retrieval_cache(db: Session) -> dict[str, Any]:
    global _effective_retrieval_cache
    config, _, _ = get_effective_retrieval_config(db)
    _effective_retrieval_cache = config
    return config


def get_effective_retrieval_cache() -> dict[str, Any] | None:
    return _effective_retrieval_cache


def build_dashboard_payload(
    config: dict[str, Any],
    hot_config: RetrievalHotConfig | None,
    source: str,
) -> dict[str, Any]:
    return {
        "source": source,
        "version": _hot_config_to_info(hot_config) if hot_config else None,
        "hot_config": _hot_config_to_info(hot_config) if hot_config else None,
        "model": config.get("model"),
        "embedding_model": config.get("embedding_model"),
        "sparse_retrieval": config.get("sparse_retrieval"),
        "rerank_model": config.get("rerank_model"),
        "variant_generation_enabled": config.get("variant_generation_enabled"),
        "rerank_enabled": config.get("rerank_enabled"),
        "top_k": {
            "faq": config.get("faq_k"),
            "doc": config.get("doc_k"),
            "rerank": config.get("rerank_top_k"),
            "final_evidence": config.get("final_evidence_top_k"),
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
        "raw": config,
        "editable_fields": list(HOT_CONFIG_FIELDS),
    }


def list_hot_configs(db: Session, config_name: str = DEFAULT_CONFIG_NAME) -> list[dict[str, Any]]:
    rows = db.execute(
        select(RetrievalHotConfig)
        .where(RetrievalHotConfig.config_name == config_name)
        .order_by(RetrievalHotConfig.created_at.desc(), RetrievalHotConfig.id.desc())
    ).scalars()
    return [_hot_config_to_info(row) for row in rows]


def save_hot_config(
    db: Session,
    config: dict[str, Any],
    created_by: int,
    config_name: str = DEFAULT_CONFIG_NAME,
) -> RetrievalHotConfig:
    yaml_config = load_yaml_retrieval_config()
    hot_config = _extract_hot_config(config)
    _validate_retrieval_config({**yaml_config, **hot_config})

    db.execute(
        update(RetrievalHotConfig)
        .where(
            RetrievalHotConfig.config_name == config_name,
            RetrievalHotConfig.is_enabled.is_(True),
        )
        .values(is_enabled=False)
    )
    row = RetrievalHotConfig(
        config_name=config_name,
        is_enabled=True,
        created_by=created_by,
        **hot_config,
    )
    db.add(row)
    db.flush()
    refresh_effective_retrieval_cache(db)
    return row


def activate_hot_config(db: Session, config_id: int, activated_by: int) -> RetrievalHotConfig:
    row = db.get(RetrievalHotConfig, config_id)
    if not row:
        raise NotFoundException("hot config not found")

    yaml_config = load_yaml_retrieval_config()
    _validate_retrieval_config({**yaml_config, **_hot_config_to_dict(row)})

    db.execute(
        update(RetrievalHotConfig)
        .where(
            RetrievalHotConfig.config_name == row.config_name,
            RetrievalHotConfig.id != row.id,
            RetrievalHotConfig.is_enabled.is_(True),
        )
        .values(is_enabled=False)
    )
    row.is_enabled = True
    row.created_by = activated_by
    db.flush()
    refresh_effective_retrieval_cache(db)
    return row


def _hot_config_to_info(config: RetrievalHotConfig) -> dict[str, Any]:
    return {
        "id": config.id,
        "config_name": config.config_name,
        "is_enabled": config.is_enabled,
        "status": "active" if config.is_enabled else "standby",
        "version_no": config.id,
        "created_by": config.created_by,
        "created_at": config.created_at,
    }
