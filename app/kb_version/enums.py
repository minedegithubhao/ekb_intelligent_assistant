"""知识库版本生命周期使用的 Enum。"""

from __future__ import annotations

from enum import StrEnum


class VersionStatus(StrEnum):
    """版本状态：待发布、当前生效、已归档。"""

    STAGED = "staged"
    ACTIVE = "active"
    ARCHIVED = "archived"


class VersionAction(StrEnum):
    """会写入操作日志的版本动作。"""

    PUBLISH = "publish"
    ROLLBACK = "rollback"
