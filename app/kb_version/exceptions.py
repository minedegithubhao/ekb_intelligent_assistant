"""知识库版本模块专用异常。"""

from __future__ import annotations

from app.core.exceptions import BadRequestException, NotFoundException


class KbVersionNotFound(NotFoundException):
    """指定 kb_version 不存在时抛出。"""

    def __init__(self, kb_version: str) -> None:
        super().__init__(f"knowledge base version not found: {kb_version}")


class KbVersionStateError(BadRequestException):
    """版本状态不满足当前操作要求时抛出。"""

    def __init__(self, message: str) -> None:
        super().__init__(message)
