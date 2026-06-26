"""Milvus 写入层。

这里只负责把已经准备好的向量行写进 DOC / FAQ 两类 collection，
不负责清洗、切分和向量生成。
"""

from __future__ import annotations

import json
import os
from collections.abc import Iterable
from typing import Any

from app.enterprise_offline_ingestion.models import DocumentVectorRow, FAQVectorRow
from app.enterprise_offline_ingestion.settings import IngestionSettings


class MilvusIngestionWriter:
    """把文档和 FAQ 的向量行写入对应 collection。

    pymilvus 采用懒加载，这样在没有安装 Milvus 依赖的环境里，清洗和切分
    仍然可以独立验证。
    """

    def __init__(self, settings: IngestionSettings) -> None:
        self.settings = settings

    def write_documents(self, rows: list[DocumentVectorRow]) -> None:
        """写入文档向量行。"""

        if not rows:
            return
        collection = self._ensure_collection(self.settings.doc_collection_name, self._doc_fields())
        self._insert_in_batches(collection, [self._doc_to_entity(row) for row in rows])

    def write_faq(self, rows: list[FAQVectorRow]) -> None:
        """写入 FAQ 向量行。"""

        if not rows:
            return
        collection = self._ensure_collection(self.settings.faq_collection_name, self._faq_fields())
        self._insert_in_batches(collection, [self._faq_to_entity(row) for row in rows])

    def delete_documents_by_source_doc_ids(self, source_doc_ids: list[str], *, kb_version: str | None = None) -> None:
        """删除指定版本内、指定 source_doc_id 的旧文档数据。"""

        if not source_doc_ids:
            return
        collection = self._ensure_collection(self.settings.doc_collection_name, self._doc_fields())
        self._delete_by_values(collection, "source_doc_id", source_doc_ids, kb_version=kb_version)

    def delete_faq_by_ids(self, faq_ids: list[str], *, kb_version: str | None = None) -> None:
        """删除指定版本内、指定 faq_id 的旧 FAQ 数据。"""

        if not faq_ids:
            return
        collection = self._ensure_collection(self.settings.faq_collection_name, self._faq_fields())
        self._delete_by_values(collection, "faq_id", faq_ids, kb_version=kb_version)

    def copy_documents_between_versions(self, source_kb_version: str, target_kb_version: str) -> int:
        """把一个版本的全部文档向量复制到另一个版本。"""

        collection = self._ensure_collection(self.settings.doc_collection_name, self._doc_fields())
        self.delete_documents_by_kb_version(target_kb_version)
        rows = self._query_by_kb_version(collection, source_kb_version)
        entities = [self._copy_entity_to_version(row, target_kb_version, record_id_field="child_chunk_id") for row in rows]
        if entities:
            self._insert_in_batches(collection, entities)
        return len(entities)

    def copy_faq_between_versions(self, source_kb_version: str, target_kb_version: str) -> int:
        """把一个版本的全部 FAQ 向量复制到另一个版本。"""

        collection = self._ensure_collection(self.settings.faq_collection_name, self._faq_fields())
        self.delete_faq_by_kb_version(target_kb_version)
        rows = self._query_by_kb_version(collection, source_kb_version)
        entities = [self._copy_entity_to_version(row, target_kb_version, record_id_field="faq_id") for row in rows]
        if entities:
            self._insert_in_batches(collection, entities)
        return len(entities)

    def delete_documents_by_kb_version(self, kb_version: str) -> None:
        """删除目标版本内全部文档向量。"""

        collection = self._ensure_collection(self.settings.doc_collection_name, self._doc_fields())
        self._delete_by_expr(collection, self._kb_version_expr(kb_version))

    def delete_faq_by_kb_version(self, kb_version: str) -> None:
        """删除目标版本内全部 FAQ 向量。"""

        collection = self._ensure_collection(self.settings.faq_collection_name, self._faq_fields())
        self._delete_by_expr(collection, self._kb_version_expr(kb_version))

    def count_documents_by_version(self, kb_version: str) -> int:
        """统计指定版本的文档 child chunk 数。"""

        collection = self._ensure_collection(self.settings.doc_collection_name, self._doc_fields())
        return self._count_by_kb_version(collection, kb_version)

    def count_document_sources_by_version(self, kb_version: str) -> int:
        """统计指定版本的文档 source_doc_id 去重数量。"""

        collection = self._ensure_collection(self.settings.doc_collection_name, self._doc_fields())
        rows = self._query_by_kb_version(collection, kb_version, output_fields=["source_doc_id"])
        return len({str(row.get("source_doc_id", "")).strip() for row in rows if str(row.get("source_doc_id", "")).strip()})

    def count_faq_by_version(self, kb_version: str) -> int:
        """统计指定版本的 FAQ 数。"""

        collection = self._ensure_collection(self.settings.faq_collection_name, self._faq_fields())
        return self._count_by_kb_version(collection, kb_version)

    def _ensure_collection(self, name: str, fields: list[object]) -> object:
        """确保 collection 存在；不存在时按字段定义创建。"""

        from pymilvus import Collection, CollectionSchema, connections, db, utility

        from app.core.config import get_runtime_config

        milvus = get_runtime_config().app.milvus
        database_name = self._get_database_name(milvus.database)
        connect_kwargs = {
            "alias": milvus.alias,
            "host": milvus.host,
            "port": str(milvus.port),
        }
        if database_name:
            connect_kwargs["db_name"] = database_name
        connections.connect(**connect_kwargs)
        if database_name:
            db.using_database(database_name, using=milvus.alias)
        if utility.has_collection(name, using=milvus.alias):
            collection = Collection(name=name, using=milvus.alias)
            self._validate_collection_schema(collection, fields)
            self._ensure_collection_indexes(collection)
            return collection
        schema = CollectionSchema(
            fields=fields,
            description=f"offline ingestion collection: {name}",
            functions=self._functions(),
            enable_dynamic_field=True,
        )
        collection = Collection(name=name, schema=schema, using=milvus.alias, shards_num=2)
        self._ensure_collection_indexes(collection)
        return collection

    def _doc_fields(self) -> list[object]:
        """文档 collection 的字段定义。

        为兼容在线检索阶段通过 expr 过滤动态字段，显式字段只保留：
        - pk
        - text
        - dense
        - sparse
        其余业务字段全部走 dynamic field。
        """

        from pymilvus import DataType, FieldSchema

        return [
            FieldSchema(name="pk", dtype=DataType.VARCHAR, is_primary=True, max_length=64),
            FieldSchema(
                name="text",
                dtype=DataType.VARCHAR,
                max_length=65535,
                enable_match=True,
                enable_analyzer=True,
            ),
            FieldSchema(name="dense", dtype=DataType.FLOAT_VECTOR, dim=self.settings.dense_vector_dim),
            FieldSchema(name="sparse", dtype=DataType.SPARSE_FLOAT_VECTOR),
        ]

    def _faq_fields(self) -> list[object]:
        """FAQ collection 的字段定义。"""

        from pymilvus import DataType, FieldSchema

        return [
            FieldSchema(name="pk", dtype=DataType.VARCHAR, is_primary=True, max_length=128),
            FieldSchema(
                name="text",
                dtype=DataType.VARCHAR,
                max_length=65535,
                enable_match=True,
                enable_analyzer=True,
            ),
            FieldSchema(name="dense", dtype=DataType.FLOAT_VECTOR, dim=self.settings.dense_vector_dim),
            FieldSchema(name="sparse", dtype=DataType.SPARSE_FLOAT_VECTOR),
        ]

    def _insert_in_batches(self, collection: object, entities: list[dict[str, object]]) -> None:
        """按批次写入，避免单次插入过大。"""

        for batch in self._batches(entities, self.settings.milvus_insert_batch_size):
            collection.insert(batch)
        collection.flush()

    def _delete_by_values(
        self,
        collection: object,
        field_name: str,
        values: list[str],
        *,
        kb_version: str | None = None,
    ) -> None:
        """按字段值分批删除旧数据。"""

        collection.load()
        for batch in self._batches(values, self.settings.milvus_insert_batch_size):
            expr = f'{field_name} in {json.dumps(batch, ensure_ascii=False)}'
            if kb_version:
                expr = f"({expr}) and {self._kb_version_expr(kb_version)}"
            collection.delete(expr)
        collection.flush()

    @staticmethod
    def _delete_by_expr(collection: object, expr: str) -> None:
        """按表达式删除数据。"""

        collection.load()
        collection.delete(expr)
        collection.flush()

    def _query_by_kb_version(
        self,
        collection: object,
        kb_version: str,
        *,
        output_fields: list[str] | None = None,
    ) -> list[dict[str, Any]]:
        """查询指定版本数据；当前开发集规模下用单次大 limit 足够。"""

        collection.load()
        return collection.query(
            expr=self._kb_version_expr(kb_version),
            output_fields=output_fields or ["*"],
            limit=100000,
        )

    def _count_by_kb_version(self, collection: object, kb_version: str) -> int:
        return len(self._query_by_kb_version(collection, kb_version, output_fields=["pk"]))

    @staticmethod
    def _kb_version_expr(kb_version: str) -> str:
        escaped = kb_version.replace("\\", "\\\\").replace('"', '\\"')
        return f'kb_version == "{escaped}"'

    @staticmethod
    def _versioned_pk(kb_version: str, record_id: str) -> str:
        return f"{kb_version}:{record_id}"

    def _copy_entity_to_version(self, row: dict[str, Any], target_kb_version: str, *, record_id_field: str) -> dict[str, Any]:
        """复制 Milvus row 时替换 kb_version 和版本化主键。"""

        entity = dict(row)
        entity.pop("sparse", None)
        record_id = str(entity.get(record_id_field) or entity.get("pk") or "")
        if ":" in record_id:
            record_id = record_id.rsplit(":", 1)[-1]
        entity["kb_version"] = target_kb_version
        entity["pk"] = self._versioned_pk(target_kb_version, record_id)
        return self._normalize_json_value(entity)

    @staticmethod
    def _batches(items: list[object], size: int) -> Iterable[list[object]]:
        """把列表切成固定大小的批次。"""

        for start in range(0, len(items), size):
            yield items[start : start + size]

    def _validate_collection_schema(self, collection: object, expected_fields: list[object]) -> None:
        """校验现有 collection schema 是否和离线入库预期一致。"""

        actual_fields = getattr(getattr(collection, "schema", None), "fields", None)
        if actual_fields is None:
            raise ValueError("Milvus collection 缺少 schema.fields，无法校验结构")
        if not getattr(getattr(collection, "schema", None), "enable_dynamic_field", False):
            raise ValueError("Milvus collection 未开启 dynamic field")

        expected_specs = {spec["name"]: spec for spec in (self._field_spec(field) for field in expected_fields)}
        actual_specs = {spec["name"]: spec for spec in (self._field_spec(field) for field in actual_fields)}

        missing = sorted(set(expected_specs) - set(actual_specs))
        extra = sorted(set(actual_specs) - set(expected_specs))
        if missing or extra:
            raise ValueError(
                f"Milvus collection schema 不匹配，missing={missing or []}, extra={extra or []}"
            )

        for field_name, expected in expected_specs.items():
            actual = actual_specs[field_name]
            for key in ("dtype", "is_primary", "max_length", "dim"):
                if expected[key] is None:
                    continue
                if actual[key] != expected[key]:
                    raise ValueError(
                        f"Milvus collection 字段 {field_name!r} 的 {key} 不匹配: "
                        f"expected={expected[key]!r}, actual={actual[key]!r}"
                    )

    def _ensure_collection_indexes(self, collection: object) -> None:
        """为 dense / sparse 向量字段确保索引存在。"""

        if self._collection_has_field(collection, "dense") and not self._has_index(collection, "dense"):
            collection.create_index(
                field_name="dense",
                index_params=self._dense_index_params(),
            )
        if self._collection_has_field(collection, "sparse") and not self._has_index(collection, "sparse"):
            collection.create_index(
                field_name="sparse",
                index_params=self._sparse_index_params(),
            )

    @staticmethod
    def _collection_has_field(collection: object, field_name: str) -> bool:
        """判断 collection 是否包含指定字段。"""

        fields = getattr(getattr(collection, "schema", None), "fields", None) or []
        return any(getattr(field, "name", None) == field_name for field in fields)

    @staticmethod
    def _has_index(collection: object, field_name: str) -> bool:
        """判断指定字段是否已有索引。"""

        indexes = getattr(collection, "indexes", None) or []
        for index in indexes:
            if getattr(index, "field_name", None) == field_name:
                return True
            index_param = getattr(index, "params", None)
            if isinstance(index_param, dict) and index_param.get("field_name") == field_name:
                return True
        return False

    @staticmethod
    def _dense_index_params() -> dict[str, object]:
        """dense 向量索引参数。"""

        return {
            "index_type": "AUTOINDEX",
            "metric_type": "L2",
            "params": {},
        }

    @staticmethod
    def _sparse_index_params() -> dict[str, object]:
        """sparse 向量索引参数。"""

        return {
            "index_type": "AUTOINDEX",
            "metric_type": "BM25",
            "params": {},
        }

    @staticmethod
    def _functions() -> list[object]:
        """Milvus built-in functions。"""

        from pymilvus import Function, FunctionType

        return [
            Function(
                name="text_bm25_to_sparse",
                function_type=FunctionType.BM25,
                input_field_names=["text"],
                output_field_names=["sparse"],
            )
        ]

    @staticmethod
    def _field_spec(field: object) -> dict[str, Any]:
        """提取 schema field 的关键约束，便于比较新旧 collection。"""

        params = getattr(field, "params", None) or {}
        if not isinstance(params, dict):
            params = {}
        return {
            "name": getattr(field, "name", None),
            "dtype": getattr(field, "dtype", None),
            "is_primary": getattr(field, "is_primary", None),
            "max_length": params.get("max_length", getattr(field, "max_length", None)),
            "dim": params.get("dim", getattr(field, "dim", None)),
        }

    @staticmethod
    def _get_database_name(default_database_name: str | None) -> str | None:
        """读取 Milvus 目标数据库名。

        默认使用应用配置中的数据库名；如需临时切换，可通过环境变量覆盖。
        """

        value = os.getenv("KNOWFORGE_MILVUS_DB_NAME", "").strip()
        return value or default_database_name

    def _doc_to_entity(self, row: DocumentVectorRow) -> dict[str, object]:
        """把文档向量行转换成 Milvus 可插入实体。"""

        metadata = self._normalize_json_value(
            {
                **row.metadata,
                "child_chunk_id": row.child_chunk_id,
                "parent_id": row.parent_id,
                "source_doc_id": row.source_doc_id,
                "title_path": row.title_path,
                "parent_content": row.parent_content,
                "reference_source": row.reference_source,
                "scope": row.scope,
            }
        )
        entity: dict[str, object] = {
            "pk": self._versioned_pk(str(metadata.get("kb_version", "")), row.child_chunk_id)
            if metadata.get("kb_version")
            else row.child_chunk_id,
            "text": row.child_content,
            "dense": row.dense_vector,
        }
        entity.update(self._build_dynamic_fields(metadata, reserved_fields=set(entity)))
        return entity

    def _faq_to_entity(self, row: FAQVectorRow) -> dict[str, object]:
        """把 FAQ 向量行转换成 Milvus 可插入实体。"""

        metadata = self._normalize_json_value(
            {
                **row.metadata,
                "faq_id": row.faq_id,
                "answer": row.answer,
                "source": row.source,
                "reference_source": row.reference_source,
            }
        )
        entity: dict[str, object] = {
            "pk": self._versioned_pk(str(metadata.get("kb_version", "")), row.faq_id)
            if metadata.get("kb_version")
            else row.faq_id,
            "text": row.question,
            "dense": row.dense_vector,
        }
        entity.update(self._build_dynamic_fields(metadata, reserved_fields=set(entity)))
        return entity

    @classmethod
    def _build_dynamic_fields(
        cls,
        metadata: dict[str, Any],
        *,
        reserved_fields: set[str],
    ) -> dict[str, object]:
        """把 metadata 展开为 Milvus dynamic fields。"""

        dynamic_fields: dict[str, object] = {}
        for key, value in metadata.items():
            if key in reserved_fields or value is None:
                continue
            dynamic_fields[key] = cls._normalize_dynamic_value(value)
        return dynamic_fields

    @classmethod
    def _normalize_json_value(cls, value: Any) -> Any:
        """把 metadata 归一化为可稳定落库的 JSON 值。"""

        return json.loads(json.dumps(value, ensure_ascii=False, default=str))

    @classmethod
    def _normalize_dynamic_value(cls, value: Any) -> object:
        """归一化 dynamic field 值，避免非 JSON 类型直接写入。"""

        if isinstance(value, (str, bool, int, float)):
            return value
        if isinstance(value, list):
            return [cls._normalize_dynamic_value(item) for item in value]
        if isinstance(value, dict):
            return cls._normalize_json_value(value)
        return str(value)
