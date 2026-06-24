"""知识库版本管理的业务服务。"""

from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path

import yaml
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.exceptions import BadRequestException
from app.kb_version.enums import VersionAction, VersionStatus
from app.kb_version.exceptions import KbVersionNotFound, KbVersionStateError
from app.kb_version.repository import KbVersionRepository
from app.kb_version.schemas import (
    DEFAULT_DOC_COLLECTION_NAME,
    DEFAULT_FAQ_COLLECTION_NAME,
    KbVersionActionLogInfo,
    KbVersionCreate,
    KbVersionDetail,
    KbVersionItem,
    KbVersionListPayload,
    KbVersionPointerInfo,
)


def generate_kb_version(now: datetime | None = None) -> str:
    """生成 kb_时间戳 格式的业务版本号。"""

    return f"kb_{(now or datetime.now()).strftime('%Y%m%d%H%M%S')}"


def load_default_embedding_model() -> str:
    """从 config/retrieval.yaml 读取默认 embedding_model。"""

    config_path = Path(__file__).resolve().parents[2] / "config" / "retrieval.yaml"
    try:
        data = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
    except OSError as exc:
        raise BadRequestException("failed to load retrieval.yaml") from exc
    embedding_model = data.get("embedding_model")
    if not embedding_model:
        raise BadRequestException("embedding_model is missing in retrieval.yaml")
    return str(embedding_model)


class KbVersionService:
    """封装版本创建、发布、快速回滚和指定版本回滚等业务规则。"""

    def __init__(self, db: Session) -> None:
        self.db = db
        self.repo = KbVersionRepository(db)

    def list_versions(self, keyword: str | None = None) -> KbVersionListPayload:
        """返回版本列表，并附带全局 active/previous 指针摘要。"""

        pointer = self.repo.get_pointer()
        rows = self.repo.list_versions(keyword=keyword)
        items = [self._build_list_item(row) for row in rows]
        return KbVersionListPayload(
            active_version=pointer["kb_active_version"] if pointer else None,
            previous_version=pointer["kb_previous_version"] if pointer else None,
            total=len(items),
            staged_count=sum(1 for item in items if item.type == VersionStatus.STAGED),
            archived_count=sum(1 for item in items if item.type == VersionStatus.ARCHIVED),
            items=items,
        )

    def get_pointer(self) -> KbVersionPointerInfo:
        """返回全局 active/previous 指针；未初始化时返回空指针。"""

        pointer = self.repo.get_pointer()
        if not pointer:
            return KbVersionPointerInfo(
                id=None,
                kb_active_version=None,
                kb_previous_version=None,
                updated_at=None,
            )
        return KbVersionPointerInfo(
            id=int(pointer["id"]),
            kb_active_version=pointer["kb_active_version"],
            kb_previous_version=pointer["kb_previous_version"],
            updated_at=pointer["updated_at"],
        )

    def create_version(self, payload: KbVersionCreate, operator_id: str | None) -> KbVersionDetail:
        """创建 staged 版本；版本号由服务端统一生成。"""

        embedding_model = payload.embedding_model or load_default_embedding_model()
        for attempt in range(3):
            # 同一秒内连续创建版本时，唯一键可能冲突；重试时顺延秒数但保持 kb_时间戳 格式。
            kb_version = generate_kb_version(datetime.now() + timedelta(seconds=attempt))
            try:
                self.repo.insert_version(
                    kb_version=kb_version,
                    embedding_model=embedding_model,
                    faq_collection_name=payload.faq_collection_name or DEFAULT_FAQ_COLLECTION_NAME,
                    doc_collection_name=payload.doc_collection_name or DEFAULT_DOC_COLLECTION_NAME,
                    created_by=operator_id,
                    description=payload.description,
                )
                self.db.flush()
                row = self.repo.get_version(kb_version)
                if row is None:
                    raise KbVersionStateError("created version cannot be loaded")
                return self._build_detail(row)
            except IntegrityError:
                self.db.rollback()
        raise BadRequestException("failed to generate unique kb_version")

    def publish(self, target_kb_version: str, operator_id: str | None, message: str | None = None) -> KbVersionDetail:
        """发布 staged 版本，并将原 active 版本归档。"""

        target = self.repo.get_version(target_kb_version, for_update=True)
        if not target:
            raise KbVersionNotFound(target_kb_version)
        if target["type"] != VersionStatus.STAGED.value:
            raise KbVersionStateError("only staged version can be published")
        if not target["doc_ready"] or not target["faq_ready"]:
            missing = []
            if not target["doc_ready"]:
                missing.append("Doc")
            if not target["faq_ready"]:
                missing.append("FAQ")
            raise KbVersionStateError(f"version content is incomplete: missing {', '.join(missing)}")

        active = self.repo.get_active_version(for_update=True)
        if active and active["kb_version"] == target_kb_version:
            raise KbVersionStateError("target version is already active")

        if active:
            self.repo.update_status(active["kb_version"], VersionStatus.ARCHIVED)
        self.repo.update_status(target_kb_version, VersionStatus.ACTIVE)
        self.repo.upsert_pointer(
            active_version=target_kb_version,
            previous_version=active["kb_version"] if active else None,
        )
        self.repo.insert_action_log(
            action=VersionAction.PUBLISH,
            source_version=active["kb_version"] if active else None,
            target_version=target_kb_version,
            source_from_status=VersionStatus.ACTIVE.value if active else None,
            source_to_status=VersionStatus.ARCHIVED.value if active else None,
            target_from_status=VersionStatus.STAGED.value,
            target_to_status=VersionStatus.ACTIVE.value,
            operator_id=operator_id,
            message=message or "publish staged version",
        )
        self.db.flush()
        updated = self.repo.get_version(target_kb_version)
        if not updated:
            raise KbVersionNotFound(target_kb_version)
        self._assert_single_active()
        return self._build_detail(updated)

    def rollback(
        self,
        *,
        operator_id: str | None,
        target_kb_version: str | None = None,
        message: str | None = None,
    ) -> KbVersionDetail:
        """快速回滚使用 previous 指针；指定回滚使用传入的 target_kb_version。"""

        pointer = self.repo.get_pointer(for_update=True)
        target_version = target_kb_version or (pointer["kb_previous_version"] if pointer else None)
        if not target_version:
            raise KbVersionStateError("previous version is empty; cannot rollback")

        active = self.repo.get_active_version(for_update=True)
        if not active:
            raise KbVersionStateError("active version is empty; cannot rollback")
        if active["kb_version"] == target_version:
            raise KbVersionStateError("target version is already active")

        target = self.repo.get_version(target_version, for_update=True)
        if not target:
            raise KbVersionNotFound(target_version)
        if target["type"] != VersionStatus.ARCHIVED.value:
            raise KbVersionStateError("rollback target must be archived")

        self.repo.update_status(active["kb_version"], VersionStatus.ARCHIVED)
        self.repo.update_status(target_version, VersionStatus.ACTIVE)
        self.repo.upsert_pointer(active_version=target_version, previous_version=active["kb_version"])
        self.repo.insert_action_log(
            action=VersionAction.ROLLBACK,
            source_version=active["kb_version"],
            target_version=target_version,
            source_from_status=VersionStatus.ACTIVE.value,
            source_to_status=VersionStatus.ARCHIVED.value,
            target_from_status=VersionStatus.ARCHIVED.value,
            target_to_status=VersionStatus.ACTIVE.value,
            operator_id=operator_id,
            message=message or "rollback active version",
        )
        self.db.flush()
        updated = self.repo.get_version(target_version)
        if not updated:
            raise KbVersionNotFound(target_version)
        self._assert_single_active()
        return self._build_detail(updated)

    def list_action_logs(self, limit: int = 20) -> list[KbVersionActionLogInfo]:
        """查询最近的版本操作日志。"""

        return [KbVersionActionLogInfo.model_validate(row) for row in self.repo.list_action_logs(limit=limit)]

    def _assert_single_active(self) -> None:
        """发布或回滚后校验全局 active 版本唯一。"""

        active_count = self.repo.count_active_versions()
        if active_count != 1:
            raise KbVersionStateError(f"expected exactly one active version, got {active_count}")

    def _build_list_item(self, row) -> KbVersionItem:
        """将数据库 row 转成列表响应项。"""

        status = VersionStatus(row["type"])
        return KbVersionItem(
            id=int(row["id"]),
            kb_version=row["kb_version"],
            type=status,
            embedding_model=row["embedding_model"],
            faq_collection_name=row["faq_collection_name"],
            doc_collection_name=row["doc_collection_name"],
            created_at=row["created_at"],
            created_by=row["created_by"],
            description=row["description"],
            doc_ready=bool(row["doc_ready"]),
            faq_ready=bool(row["faq_ready"]),
            document_count=int(row["document_count"] or 0),
            child_chunk_count=int(row["child_chunk_count"] or 0),
            faq_count=int(row["faq_count"] or 0),
            operation=self._operation_for_status(status),
        )

    @staticmethod
    def _operation_for_status(status: VersionStatus) -> str:
        """根据状态给前端返回默认可执行操作。"""

        if status == VersionStatus.STAGED:
            return "publish"
        if status == VersionStatus.ARCHIVED:
            return "rollback"
        return "current"

    @staticmethod
    def _build_detail(row) -> KbVersionDetail:
        """将数据库 row 转成详情响应。"""

        return KbVersionDetail(
            id=int(row["id"]),
            kb_version=row["kb_version"],
            type=VersionStatus(row["type"]),
            embedding_model=row["embedding_model"],
            faq_collection_name=row["faq_collection_name"],
            doc_collection_name=row["doc_collection_name"],
            created_at=row["created_at"],
            created_by=row["created_by"],
            description=row["description"],
            doc_ready=bool(row["doc_ready"]),
            faq_ready=bool(row["faq_ready"]),
            document_count=int(row["document_count"] or 0),
            child_chunk_count=int(row["child_chunk_count"] or 0),
            faq_count=int(row["faq_count"] or 0),
        )
