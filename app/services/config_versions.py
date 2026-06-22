"""Admin configuration version service."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from app.core.config import ConfigManager, RetrievalConfig
from app.core.exceptions import BadRequestException, NotFoundException
from app.db.models.config import ConfigVersion
from app.schemas.config import ConfigVersionInfo

CONFIG_KEY_RETRIEVAL = "retrieval"

_effective_retrieval_cache: dict[str, Any] | None = None


def _validate_retrieval_config(config: dict[str, Any]) -> dict[str, Any]:
    try:
        RetrievalConfig.model_validate(config)
    except Exception as exc:
        raise BadRequestException(f"invalid retrieval config: {exc}") from exc
    return config


def load_yaml_retrieval_config() -> dict[str, Any]:
    # 当 MySQL 没有 active 配置版本时，回退读取本地 YAML 默认配置。
    return ConfigManager().read_config_file("retrieval.yaml")


def get_active_config_version(db: Session) -> ConfigVersion | None:
    # 从 MySQL 读取唯一生效的仪表台/检索配置。
    # 管理端接口和项目启动加载配置都会依赖这个查询。
    return db.execute(
        select(ConfigVersion).where(
            ConfigVersion.config_key == CONFIG_KEY_RETRIEVAL,
            ConfigVersion.status == "active",
            ConfigVersion.is_deleted.is_(False),
        )
    ).scalar_one_or_none()


def get_effective_retrieval_config(db: Session) -> tuple[dict[str, Any], ConfigVersion | None, str]:
    # 优先使用 MySQL active 版本；YAML 只作为首次启动或未初始化时的兜底来源。
    active = get_active_config_version(db)
    if active:
        return dict(active.config_json), active, "mysql"
    return load_yaml_retrieval_config(), None, "yaml"


def refresh_effective_retrieval_cache(db: Session) -> dict[str, Any]:
    # 刷新进程内缓存，后续检索逻辑可以低成本读取当前生效配置。
    global _effective_retrieval_cache
    config, _, _ = get_effective_retrieval_config(db)
    _effective_retrieval_cache = config
    return config


def get_effective_retrieval_cache() -> dict[str, Any] | None:
    return _effective_retrieval_cache


def build_dashboard_payload(config: dict[str, Any], version: ConfigVersion | None, source: str) -> dict[str, Any]:
    # 返回前端易展示的摘要字段，同时在 raw 中保留完整原始配置。
    return {
        "source": source,
        "version": _version_to_info(version).model_dump(mode="json") if version else None,
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
    }


def list_config_versions(db: Session) -> list[ConfigVersionInfo]:
    versions = db.execute(
        select(ConfigVersion)
        .where(ConfigVersion.config_key == CONFIG_KEY_RETRIEVAL, ConfigVersion.is_deleted.is_(False))
        .order_by(ConfigVersion.version_no.desc())
    ).scalars()
    return [_version_to_info(item) for item in versions]


def create_config_version(
    db: Session,
    config: dict[str, Any],
    created_by: int,
    description: str | None = None,
    activate: bool = False,
) -> ConfigVersion:
    validated = _validate_retrieval_config(config)
    # 同一个 config_key 下版本号递增，旧版本保留用于查询和回滚参考。
    latest = db.execute(
        select(func.max(ConfigVersion.version_no)).where(ConfigVersion.config_key == CONFIG_KEY_RETRIEVAL)
    ).scalar()
    version = ConfigVersion(
        config_key=CONFIG_KEY_RETRIEVAL,
        version_no=int(latest or 0) + 1,
        status="draft",
        config_json=validated,
        description=description,
        created_by=created_by,
    )
    db.add(version)
    db.flush()
    if activate:
        activate_config_version(db, version.id, activated_by=created_by)
        db.refresh(version)
    return version


def activate_config_version(db: Session, version_id: int, activated_by: int) -> ConfigVersion:
    version = db.get(ConfigVersion, version_id)
    if not version or version.is_deleted:
        raise NotFoundException("config version not found")
    if version.config_key != CONFIG_KEY_RETRIEVAL:
        raise BadRequestException("unsupported config key")

    _validate_retrieval_config(dict(version.config_json))
    # 同一时间只允许一个 active 检索配置；旧 active 版本统一归档。
    db.execute(
        update(ConfigVersion)
        .where(
            ConfigVersion.config_key == CONFIG_KEY_RETRIEVAL,
            ConfigVersion.status == "active",
            ConfigVersion.id != version.id,
        )
        .values(status="archived")
    )
    version.status = "active"
    version.activated_by = activated_by
    version.activated_at = datetime.now(UTC)
    db.flush()
    # 切换 active 版本后，立即刷新内存中的生效配置。
    refresh_effective_retrieval_cache(db)
    return version


def _version_to_info(version: ConfigVersion) -> ConfigVersionInfo:
    return ConfigVersionInfo(
        id=version.id,
        config_key=version.config_key,
        version_no=version.version_no,
        status=version.status,
        description=version.description,
        created_by=version.created_by,
        activated_by=version.activated_by,
        activated_at=version.activated_at,
        created_at=version.created_at,
        updated_at=version.updated_at,
    )
