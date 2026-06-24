"""知识库版本管理模块。

该 package 尽量保持自包含，便于在不改动项目其他模块的情况下接入
``app/kb_version``。
"""

from app.kb_version.enums import VersionAction, VersionStatus
from app.kb_version.service import KbVersionService, generate_kb_version

__all__ = [
    "KbVersionService",
    "VersionAction",
    "VersionStatus",
    "generate_kb_version",
]
