"""知识库版本管理的数据库访问层。"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime
from typing import Any

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.kb_version.enums import VersionAction, VersionStatus


class KbVersionRepository:
    """只访问版本管理模块自己的三张表。"""

    def __init__(self, db: Session) -> None:
        self.db = db

    def list_versions(self, keyword: str | None = None) -> Sequence[Any]:
        """查询版本列表；版本管理只按 kb_version 过滤，不按 source 区分。"""

        params: dict[str, Any] = {}
        where = ""
        if keyword:
            where = "WHERE kb_version LIKE :keyword"
            params["keyword"] = f"%{keyword}%"
        return self.db.execute(
            text(
                f"""
                SELECT
                    id, kb_version, status, embedding_model,
                    faq_collection_name, doc_collection_name,
                    created_at, created_by, description,
                    doc_ready, faq_ready, document_count, child_chunk_count, faq_count
                FROM kb_versions
                {where}
                ORDER BY
                    CASE status
                        WHEN 'active' THEN 0
                        WHEN 'staged' THEN 1
                        ELSE 2
                    END,
                    created_at DESC,
                    id DESC
                """
            ),
            params,
        ).mappings().all()

    def get_version(self, kb_version: str, *, for_update: bool = False) -> Any | None:
        """按 kb_version 查询版本；发布/回滚前可加 FOR UPDATE 锁。"""

        suffix = " FOR UPDATE" if for_update else ""
        return self.db.execute(
            text(
                f"""
                SELECT
                    id, kb_version, status, embedding_model,
                    faq_collection_name, doc_collection_name,
                    created_at, created_by, description,
                    doc_ready, faq_ready, document_count, child_chunk_count, faq_count
                FROM kb_versions
                WHERE kb_version=:kb_version
                {suffix}
                """
            ),
            {"kb_version": kb_version},
        ).mappings().first()

    def get_active_version(self, *, for_update: bool = False) -> Any | None:
        """查询当前 active 版本；异常数据下取最新的一条。"""

        suffix = " FOR UPDATE" if for_update else ""
        return self.db.execute(
            text(
                f"""
                SELECT
                    id, kb_version, status, embedding_model,
                    faq_collection_name, doc_collection_name,
                    created_at, created_by, description,
                    doc_ready, faq_ready, document_count, child_chunk_count, faq_count
                FROM kb_versions
                WHERE status='active'
                ORDER BY created_at DESC, id DESC
                LIMIT 1
                {suffix}
                """
            )
        ).mappings().first()

    def count_active_versions(self) -> int:
        """校验全局只能有一个 active 版本。"""

        return int(self.db.execute(text("SELECT COUNT(*) FROM kb_versions WHERE status='active'")).scalar_one())

    def insert_version(
        self,
        *,
        kb_version: str,
        embedding_model: str,
        faq_collection_name: str,
        doc_collection_name: str,
        created_by: str | None,
        description: str | None,
    ) -> None:
        """插入新版本，初始状态固定为 staged。"""

        self.db.execute(
            text(
                """
                INSERT INTO kb_versions (
                    kb_version, status, embedding_model, faq_collection_name,
                    doc_collection_name, created_at, created_by, description
                )
                VALUES (
                    :kb_version, 'staged', :embedding_model, :faq_collection_name,
                    :doc_collection_name, NOW(), :created_by, :description
                )
                """
            ),
            {
                "kb_version": kb_version,
                "embedding_model": embedding_model,
                "faq_collection_name": faq_collection_name,
                "doc_collection_name": doc_collection_name,
                "created_by": created_by,
                "description": description,
            },
        )

    def update_status(self, kb_version: str, status: VersionStatus) -> None:
        """更新指定版本的 status 状态。"""

        self.db.execute(
            text("UPDATE kb_versions SET status=:status WHERE kb_version=:kb_version"),
            {"status": status.value, "kb_version": kb_version},
        )

    def update_content_state(
        self,
        kb_version: str,
        *,
        doc_ready: bool | None = None,
        faq_ready: bool | None = None,
        document_count: int | None = None,
        child_chunk_count: int | None = None,
        faq_count: int | None = None,
    ) -> None:
        """更新版本内 Doc/FAQ 准备状态和统计数量。"""

        values: dict[str, Any] = {}
        if doc_ready is not None:
            values["doc_ready"] = int(doc_ready)
        if faq_ready is not None:
            values["faq_ready"] = int(faq_ready)
        if document_count is not None:
            values["document_count"] = document_count
        if child_chunk_count is not None:
            values["child_chunk_count"] = child_chunk_count
        if faq_count is not None:
            values["faq_count"] = faq_count
        if not values:
            return

        assignments = ", ".join(f"{field}=:{field}" for field in values)
        self.db.execute(
            text(f"UPDATE kb_versions SET {assignments} WHERE kb_version=:kb_version"),
            {**values, "kb_version": kb_version},
        )

    def get_pointer(self, *, for_update: bool = False) -> Any | None:
        """查询全局 active/previous 指针。"""

        suffix = " FOR UPDATE" if for_update else ""
        return self.db.execute(
            text(
                f"""
                SELECT id, kb_active_version, kb_previous_version, updated_at
                FROM kb_version_pointers
                ORDER BY id ASC
                LIMIT 1
                {suffix}
                """
            )
        ).mappings().first()

    def upsert_pointer(self, *, active_version: str | None, previous_version: str | None) -> None:
        """更新全局指针；不存在记录时创建一条。"""

        pointer = self.get_pointer(for_update=True)
        if pointer:
            self.db.execute(
                text(
                    """
                    UPDATE kb_version_pointers
                    SET
                        kb_active_version=:active_version,
                        kb_previous_version=:previous_version,
                        updated_at=NOW()
                    WHERE id=:id
                    """
                ),
                {"id": pointer["id"], "active_version": active_version, "previous_version": previous_version},
            )
            return

        self.db.execute(
            text(
                """
                INSERT INTO kb_version_pointers (
                    kb_active_version, kb_previous_version, updated_at
                )
                VALUES (:active_version, :previous_version, NOW())
                """
            ),
            {"active_version": active_version, "previous_version": previous_version},
        )

    def insert_action_log(
        self,
        *,
        action: VersionAction,
        source_version: str | None,
        target_version: str,
        source_from_status: str | None,
        source_to_status: str | None,
        target_from_status: str,
        target_to_status: str,
        operator_id: str | None,
        message: str | None,
    ) -> None:
        """记录发布/回滚操作。"""

        self.db.execute(
            text(
                """
                INSERT INTO kb_version_action_logs (
                    action, source_version, target_version,
                    source_from_status, source_to_status,
                    target_from_status, target_to_status,
                    operator_id, message, created_at
                )
                VALUES (
                    :action, :source_version, :target_version,
                    :source_from_status, :source_to_status,
                    :target_from_status, :target_to_status,
                    :operator_id, :message, NOW()
                )
                """
            ),
            {
                "action": action.value,
                "source_version": source_version,
                "target_version": target_version,
                "source_from_status": source_from_status,
                "source_to_status": source_to_status,
                "target_from_status": target_from_status,
                "target_to_status": target_to_status,
                "operator_id": operator_id,
                "message": message,
            },
        )

    def list_action_logs(self, limit: int = 20) -> Sequence[Any]:
        """按时间倒序查询最近的版本操作日志。"""

        return self.db.execute(
            text(
                """
                SELECT
                    id, action, source_version, target_version,
                    source_from_status, source_to_status,
                    target_from_status, target_to_status,
                    operator_id, message, created_at
                FROM kb_version_action_logs
                ORDER BY created_at DESC, id DESC
                LIMIT :limit
                """
            ),
            {"limit": limit},
        ).mappings().all()


def row_to_dict(row: Any) -> dict[str, Any]:
    """将 SQLAlchemy row 转成普通 dict，保留 datetime 对象。"""

    data = dict(row)
    for key, value in list(data.items()):
        if isinstance(value, datetime):
            data[key] = value
    return data
