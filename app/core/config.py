"""Load YAML files into typed runtime configuration objects."""

from __future__ import annotations

import os
import re
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from app.core.exceptions import ConfigException


PROJECT_ROOT = Path(__file__).resolve().parents[2]
CONFIG_DIR = PROJECT_ROOT / "config"
ENV_PATTERN = re.compile(r"\$\{([A-Z0-9_]+)(?::([^}]*))?\}")


class AppInfo(BaseModel):
    name: str
    env: str = "local"
    debug: bool = False
    api_prefix: str = "/api"


class ServerConfig(BaseModel):
    host: str = "0.0.0.0"
    port: int = 8000


class CorsConfig(BaseModel):
    allow_origins: list[str] = Field(default_factory=list)
    allow_credentials: bool = True
    allow_methods: list[str] = Field(default_factory=lambda: ["*"])
    allow_headers: list[str] = Field(default_factory=lambda: ["*"])


class LoggingConfig(BaseModel):
    """Runtime log file settings loaded from config/app.yaml."""

    level: str = "INFO"
    dir: str = "logs"
    app_file: str = "app.log"
    error_file: str = "error.log"
    max_bytes: int = 10 * 1024 * 1024
    backup_count: int = 5


class SecurityConfig(BaseModel):
    secret_key: str
    algorithm: str = "HS256"
    access_token_expire_minutes: int = 120
    password_hash_iterations: int = 260000


class MySQLConfig(BaseModel):
    host: str
    port: int = 3306
    database: str
    user: str
    password: str
    echo: bool = False
    pool_size: int = 5
    max_overflow: int = 10
    pool_recycle_seconds: int = 1800

    @property
    def sqlalchemy_url(self) -> str:
        return (
            f"mysql+pymysql://{self.user}:{self.password}"
            f"@{self.host}:{self.port}/{self.database}?charset=utf8mb4"
        )


class DatabaseConfig(BaseModel):
    mysql: MySQLConfig


class RedisConfig(BaseModel):
    host: str
    port: int = 6379
    db: int = 0
    password: str | None = None
    socket_timeout_seconds: int = 5


class MilvusConfig(BaseModel):
    alias: str = "default"
    host: str
    port: int = 19530
    collection_prefix: str = "knowforge"


class ModelPathConfig(BaseModel):
    base_dir: str
    embedding_model_path: str
    rerank_model_path: str
    query_classifier_path: str


class AppConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    app: AppInfo
    server: ServerConfig
    cors: CorsConfig
    logging: LoggingConfig = Field(default_factory=LoggingConfig)
    security: SecurityConfig
    database: DatabaseConfig
    redis: RedisConfig
    milvus: MilvusConfig
    models: ModelPathConfig


class RetrievalConfig(BaseModel):
    """Static retrieval settings kept in YAML because they rebuild resources."""

    model_config = ConfigDict(extra="allow")

    model: str
    embedding_model: str
    embedding_model_path: str
    sparse_retrieval: str
    rerank_model: str
    rerank_model_path: str


class RuntimeConfig(BaseModel):
    app: AppConfig
    retrieval: RetrievalConfig


def _interpolate_env(value: Any) -> Any:
    if isinstance(value, dict):
        return {k: _interpolate_env(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_interpolate_env(item) for item in value]
    if not isinstance(value, str):
        return value

    def replace(match: re.Match[str]) -> str:
        key, default = match.group(1), match.group(2)
        if key in os.environ:
            return os.environ[key]
        if default is not None:
            return default
        raise ConfigException(f"missing environment variable: {key}")

    return ENV_PATTERN.sub(replace, value)


def load_yaml(path: Path) -> dict[str, Any]:
    if not path.exists():
        raise ConfigException(f"config file not found: {path}")
    with path.open("r", encoding="utf-8") as f:
        loaded = yaml.safe_load(f) or {}
    if not isinstance(loaded, dict):
        raise ConfigException(f"config file must be a YAML mapping: {path}")
    return _interpolate_env(loaded)


class ConfigManager:
    """Loads YAML config files and validates them into typed objects."""

    def __init__(self, config_dir: Path = CONFIG_DIR) -> None:
        self.config_dir = config_dir

    def load(self) -> RuntimeConfig:
        try:
            app = AppConfig.model_validate(load_yaml(self.config_dir / "app.yaml"))
            retrieval = RetrievalConfig.model_validate(load_yaml(self.config_dir / "retrieval.yaml"))
            return RuntimeConfig(app=app, retrieval=retrieval)
        except ValidationError as exc:
            raise ConfigException(f"invalid config: {exc}") from exc

    def read_config_file(self, filename: str) -> dict[str, Any]:
        return load_yaml(self.config_dir / filename)

    def write_config_file(self, filename: str, data: dict[str, Any]) -> None:
        # Reserved for later admin-side config editing.
        path = self.config_dir / filename
        with path.open("w", encoding="utf-8") as f:
            yaml.safe_dump(data, f, allow_unicode=True, sort_keys=False)


@lru_cache(maxsize=1)
def get_runtime_config() -> RuntimeConfig:
    return ConfigManager().load()


def reload_runtime_config() -> RuntimeConfig:
    get_runtime_config.cache_clear()
    return get_runtime_config()
