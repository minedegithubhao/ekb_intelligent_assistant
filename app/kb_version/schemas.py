"""知识库版本 API 使用的 Pydantic schemas。"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from app.kb_version.enums import VersionAction, VersionStatus


DEFAULT_FAQ_COLLECTION_NAME = "faq_collection"
DEFAULT_DOC_COLLECTION_NAME = "doc_collection"


class KbVersionCreate(BaseModel):
    """创建 staged 版本时的请求体。"""

    embedding_model: str | None = Field(default=None, max_length=64)
    faq_collection_name: str = Field(default=DEFAULT_FAQ_COLLECTION_NAME, max_length=191)
    doc_collection_name: str = Field(default=DEFAULT_DOC_COLLECTION_NAME, max_length=191)
    description: str | None = Field(default=None, max_length=255)


class KbVersionOperation(BaseModel):
    """发布、回滚操作的通用请求体。"""

    message: str | None = Field(default=None, max_length=1000)


class KbVersionItem(BaseModel):
    """版本列表项，包含 kb_versions 表的全部字段。"""

    id: int
    kb_version: str
    status: VersionStatus
    embedding_model: str
    faq_collection_name: str
    doc_collection_name: str
    created_at: datetime
    created_by: str | None
    description: str | None
    doc_ready: bool = False
    faq_ready: bool = False
    document_count: int = 0
    child_chunk_count: int = 0
    faq_count: int = 0
    operation: str

    model_config = ConfigDict(from_attributes=True)


class KbVersionDetail(BaseModel):
    """单个版本详情，字段与 kb_versions 表对齐。"""

    id: int
    kb_version: str
    status: VersionStatus
    embedding_model: str
    faq_collection_name: str
    doc_collection_name: str
    created_at: datetime
    created_by: str | None
    description: str | None
    doc_ready: bool = False
    faq_ready: bool = False
    document_count: int = 0
    child_chunk_count: int = 0
    faq_count: int = 0

    model_config = ConfigDict(from_attributes=True)


class KbVersionPointerInfo(BaseModel):
    """全局 active/previous 指针。"""

    id: int | None
    kb_active_version: str | None
    kb_previous_version: str | None
    updated_at: datetime | None


class KbVersionListPayload(BaseModel):
    """版本列表响应，包含指针摘要、统计和列表数据。"""

    active_version: str | None
    previous_version: str | None
    total: int
    staged_count: int
    archived_count: int
    items: list[KbVersionItem]


class KbVersionActionLogInfo(BaseModel):
    """版本操作日志响应项。"""

    id: int
    action: VersionAction
    source_version: str | None
    target_version: str
    source_from_status: str | None
    source_to_status: str | None
    target_from_status: str
    target_to_status: str
    operator_id: str | None
    message: str | None
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)
