"""Admin service for offline ingestion configs and tasks."""

from __future__ import annotations

import csv
import os
import uuid
from datetime import UTC, datetime
from pathlib import Path

from fastapi import UploadFile
from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.core.config import get_runtime_config
from app.core.exceptions import BadRequestException, NotFoundException
from app.db.models.offline_ingestion import OfflineIngestionConfig, OfflineIngestionTask
from app.db.mysql import SessionLocal
from app.enterprise_offline_ingestion.bge_m3_provider import BGEModelConfig, BGEM3EmbeddingProvider
from app.enterprise_offline_ingestion.cleaner import FAQCleaner
from app.enterprise_offline_ingestion.milvus_writer import MilvusIngestionWriter
from app.enterprise_offline_ingestion.pipeline import OfflineIngestionPipeline
from app.enterprise_offline_ingestion.settings import IngestionSettings, PROJECT_ROOT
from app.enterprise_offline_ingestion.splitter import stable_id
from app.enterprise_offline_ingestion.vectorization import VectorizationService
from app.kb_version.service import KbVersionService
from app.schemas.offline_ingestion import OfflineIngestionConfigCreate, OfflineIngestionTaskCreate, OfflineUploadTaskCreate


DEFAULT_CONFIG_NAME = "default"
TASK_PENDING = "pending"
TASK_RUNNING = "running"
TASK_COMPLETED = "completed"
TASK_FAILED = "failed"
INGEST_TYPE_MIXED = "mixed"
INGEST_TYPE_DOCUMENT = "document"
INGEST_TYPE_FAQ = "faq"
UPLOAD_ROOT = PROJECT_ROOT / "data" / "offline_uploads"
FAQ_UPLOAD_REQUIRED_FIELDS = {"question", "answer"}
FAQ_CANONICAL_FIELDNAMES = [
    "question",
    "answer",
    "source",
    "reference_source",
    "scope",
]


def list_configs(db: Session, config_name: str = DEFAULT_CONFIG_NAME) -> list[dict]:
    rows = db.execute(
        select(OfflineIngestionConfig)
        .where(OfflineIngestionConfig.config_name == config_name)
        .order_by(
            OfflineIngestionConfig.is_enabled.desc(),
            OfflineIngestionConfig.created_at.desc(),
            OfflineIngestionConfig.id.desc(),
        )
    ).scalars()
    return [_config_to_info(row) for row in rows]


def get_active_config(db: Session, config_name: str = DEFAULT_CONFIG_NAME) -> OfflineIngestionConfig:
    row = db.execute(
        select(OfflineIngestionConfig)
        .where(
            OfflineIngestionConfig.config_name == config_name,
            OfflineIngestionConfig.is_enabled.is_(True),
        )
        .order_by(
            OfflineIngestionConfig.updated_at.desc(),
            OfflineIngestionConfig.created_at.desc(),
            OfflineIngestionConfig.id.desc(),
        )
    ).scalar_one_or_none()
    if not row:
        raise NotFoundException("active offline ingestion config not found")
    return row


def get_active_config_info(db: Session) -> dict:
    return _config_to_info(get_active_config(db))


def list_server_directories(path: str | None = None) -> dict:
    if not path:
        roots = _list_directory_roots()
        return {
            "current_path": "",
            "parent_path": None,
            "directories": [{"name": str(root), "path": str(root), "is_root": True} for root in roots],
        }

    current = Path(path).expanduser()
    if not current.exists():
        raise BadRequestException(f"directory not found: {current}")
    if not current.is_dir():
        raise BadRequestException(f"path is not a directory: {current}")

    directories: list[dict] = []
    try:
        children = sorted(current.iterdir(), key=lambda item: item.name.casefold())
    except PermissionError as exc:
        raise BadRequestException(f"directory permission denied: {current}") from exc

    for child in children:
        try:
            if child.is_dir():
                directories.append({"name": child.name, "path": str(child), "is_root": False})
        except PermissionError:
            continue

    parent = current.parent
    parent_path = None if parent == current else str(parent)
    return {
        "current_path": str(current),
        "parent_path": parent_path,
        "directories": directories,
    }


def create_config(db: Session, payload: OfflineIngestionConfigCreate, created_by: int | None) -> OfflineIngestionConfig:
    base = get_active_config(db, config_name=payload.config_name)
    row = OfflineIngestionConfig(
        config_name=payload.config_name,
        is_enabled=False,
        created_by=created_by,
        source_data_root=base.source_data_root,
        clean_markdown_dir=base.clean_markdown_dir,
        index_csv_name=base.index_csv_name,
        faq_csv_dir=base.faq_csv_dir,
        doc_parent_chunk_size=payload.doc_parent_chunk_size,
        doc_child_chunk_size=payload.doc_child_chunk_size,
        doc_child_chunk_overlap=payload.doc_child_chunk_overlap,
        table_split_strategy=payload.table_split_strategy,
        table_header_required=payload.table_header_required,
        table_row_max_chars=payload.table_row_max_chars,
        rule_metadata_filter_keys=base.rule_metadata_filter_keys,
        doc_collection_name=base.doc_collection_name,
        faq_collection_name=base.faq_collection_name,
        dense_vector_dim=base.dense_vector_dim,
        sparse_vector_enabled=base.sparse_vector_enabled,
        embedding_batch_size=base.embedding_batch_size,
        milvus_insert_batch_size=base.milvus_insert_batch_size,
        scope_enum=base.scope_enum,
    )
    db.add(row)
    db.flush()
    return row


def activate_config(db: Session, config_id: int) -> OfflineIngestionConfig:
    row = db.execute(select(OfflineIngestionConfig).where(OfflineIngestionConfig.id == config_id)).scalar_one_or_none()
    if not row:
        raise NotFoundException("offline ingestion config not found")
    db.execute(
        update(OfflineIngestionConfig)
        .where(
            OfflineIngestionConfig.config_name == row.config_name,
            OfflineIngestionConfig.is_enabled.is_(True),
        )
        .values(is_enabled=False)
    )
    row.is_enabled = True
    row.updated_at = datetime.now(UTC)
    db.flush()
    return row


def create_task(db: Session, payload: OfflineIngestionTaskCreate, created_by: int | None) -> OfflineIngestionTask:
    config = get_active_config(db)
    source_data_root = _clean_override(payload.source_data_root, config.source_data_root)
    clean_markdown_dir = _clean_override(payload.clean_markdown_dir, config.clean_markdown_dir)
    index_csv_name = _clean_override(payload.index_csv_name, config.index_csv_name)
    faq_csv_dir = _clean_override(payload.faq_csv_dir, config.faq_csv_dir)
    _validate_source_files(
        config,
        source_data_root=source_data_root,
        clean_markdown_dir=clean_markdown_dir,
        index_csv_name=index_csv_name,
        faq_csv_dir=faq_csv_dir,
    )
    task = OfflineIngestionTask(
        task_id=_new_task_id(),
        status=TASK_PENDING,
        progress_percent=0,
        current_stage="等待执行",
        config_id=config.id,
        ingest_type=INGEST_TYPE_MIXED,
        source_data_root=source_data_root,
        clean_markdown_dir=clean_markdown_dir,
        index_csv_name=index_csv_name,
        faq_csv_dir=faq_csv_dir,
        auto_publish=payload.auto_publish,
        version_description=payload.version_description,
        created_by=created_by,
    )
    db.add(task)
    db.flush()
    return task


async def create_uploaded_document_task(
    db: Session,
    *,
    payload: OfflineUploadTaskCreate,
    files: list[UploadFile],
    created_by: int | None,
) -> OfflineIngestionTask:
    config = get_active_config(db)
    _validate_scope(config, payload.scope)
    _validate_target_staged_version(db, payload.kb_version)
    task_id = _new_task_id()
    upload_root = UPLOAD_ROOT / task_id
    document_root = upload_root / "documents"
    markdown_paths = await _save_upload_files(files, target_root=document_root, allowed_suffix=".md")
    if not markdown_paths:
        raise BadRequestException("please upload at least one markdown file")
    index_csv_path = _write_generated_index_csv(document_root, markdown_paths, scope=payload.scope)
    task = _new_upload_task(
        config,
        task_id=task_id,
        ingest_type=INGEST_TYPE_DOCUMENT,
        upload_root=upload_root,
        source_data_root=str(upload_root.relative_to(PROJECT_ROOT)),
        clean_markdown_dir="documents",
        index_csv_name=index_csv_path.name,
        faq_csv_dir="faq",
        auto_publish=payload.auto_publish,
        version_description=payload.version_description,
        kb_version=payload.kb_version,
        created_by=created_by,
    )
    db.add(task)
    db.flush()
    return task


async def create_uploaded_faq_task(
    db: Session,
    *,
    payload: OfflineUploadTaskCreate,
    files: list[UploadFile],
    created_by: int | None,
) -> OfflineIngestionTask:
    config = get_active_config(db)
    _validate_scope(config, payload.scope)
    _validate_target_staged_version(db, payload.kb_version)
    task_id = _new_task_id()
    upload_root = UPLOAD_ROOT / task_id
    faq_root = upload_root / "faq"
    faq_paths = await _save_upload_files(files, target_root=faq_root, allowed_suffix=".csv")
    if not faq_paths:
        raise BadRequestException("please upload at least one faq csv file")
    for path in faq_paths:
        _rewrite_faq_csv_with_scope(path, scope=payload.scope)
    task = _new_upload_task(
        config,
        task_id=task_id,
        ingest_type=INGEST_TYPE_FAQ,
        upload_root=upload_root,
        source_data_root=str(upload_root.relative_to(PROJECT_ROOT)),
        clean_markdown_dir=".",
        index_csv_name="index.csv",
        faq_csv_dir="faq",
        auto_publish=payload.auto_publish,
        version_description=payload.version_description,
        kb_version=payload.kb_version,
        created_by=created_by,
    )
    db.add(task)
    db.flush()
    return task


def list_tasks(db: Session, limit: int = 20) -> list[dict]:
    rows = db.execute(
        select(OfflineIngestionTask)
        .order_by(OfflineIngestionTask.created_at.desc(), OfflineIngestionTask.id.desc())
        .limit(limit)
    ).scalars()
    return [_task_to_info(row) for row in rows]


def get_task(db: Session, task_id: str) -> OfflineIngestionTask:
    row = db.execute(select(OfflineIngestionTask).where(OfflineIngestionTask.task_id == task_id)).scalar_one_or_none()
    if not row:
        raise NotFoundException("offline ingestion task not found")
    return row


def _validate_target_staged_version(db: Session, kb_version: str) -> None:
    """上传入库必须写入已存在的 staged 版本。"""

    row = KbVersionService(db).repo.get_version(kb_version)
    if not row:
        raise NotFoundException("kb version not found")
    if row["status"] != "staged":
        raise BadRequestException("offline ingestion can only write to staged kb version")


def run_offline_ingestion_task(task_id: str) -> None:
    db = SessionLocal()
    try:
        task = get_task(db, task_id)
        config = db.get(OfflineIngestionConfig, task.config_id)
        if not config:
            raise NotFoundException("offline ingestion config not found")

        _update_task(db, task, status=TASK_RUNNING, progress_percent=5, current_stage="校验数据目录", started_at=datetime.now(UTC))
        markdown_paths, faq_paths, index_csv_path = _build_source_paths(
            config,
            source_data_root=task.source_data_root,
            clean_markdown_dir=task.clean_markdown_dir,
            index_csv_name=task.index_csv_name,
            faq_csv_dir=task.faq_csv_dir,
        )
        _update_task(db, task, progress_percent=15, current_stage="准备模型和向量库")

        settings = _settings_from_config(
            config,
            source_data_root=task.source_data_root,
            clean_markdown_dir=task.clean_markdown_dir,
            index_csv_name=task.index_csv_name,
            faq_csv_dir=task.faq_csv_dir,
        )
        runtime = get_runtime_config()
        embedding_provider = BGEM3EmbeddingProvider(
            BGEModelConfig(
                model_path=runtime.app.models.embedding_model_path,
                device=os.getenv("KNOWFORGE_EMBEDDING_DEVICE", "cuda"),
                use_fp16=os.getenv("KNOWFORGE_EMBEDDING_FP16", "false").lower() == "true",
                batch_size=settings.embedding_batch_size,
            )
        )
        vectorization_service = VectorizationService(
            dense_provider=embedding_provider,
            sparse_provider=None,
            batch_size=settings.embedding_batch_size,
        )
        pipeline = OfflineIngestionPipeline(
            settings,
            vectorization_service=vectorization_service,
            writer=MilvusIngestionWriter(settings),
            db_session=db,
            version_created_by=str(task.created_by) if task.created_by else None,
            version_description=task.version_description,
        )

        _update_task(db, task, progress_percent=25, current_stage="清洗、切分、向量化并写入 Milvus")
        batch = pipeline.ingest(markdown_paths=markdown_paths, faq_paths=faq_paths, index_csv_path=index_csv_path)
        task.kb_version = pipeline.kb_version
        task.document_count = len(batch.documents)
        task.parent_chunk_count = len(batch.parent_chunks)
        task.child_chunk_count = len(batch.child_chunks)
        task.faq_count = len(batch.faq_records)

        if task.auto_publish:
            task.current_stage = "发布知识库版本"
            task.progress_percent = 92
            db.flush()
            KbVersionService(db).publish(
                pipeline.kb_version,
                operator_id=str(task.created_by) if task.created_by else None,
                message="auto publish after offline ingestion",
            )

        task.status = TASK_COMPLETED
        task.progress_percent = 100
        task.current_stage = "完成"
        task.finished_at = datetime.now(UTC)
        db.commit()
    except Exception as exc:
        db.rollback()
        task = db.execute(select(OfflineIngestionTask).where(OfflineIngestionTask.task_id == task_id)).scalar_one_or_none()
        if task:
            task.status = TASK_FAILED
            task.progress_percent = task.progress_percent or 0
            task.current_stage = "失败"
            task.error_message = str(exc)
            task.finished_at = datetime.now(UTC)
            db.commit()
    finally:
        db.close()


def run_offline_ingestion_task(task_id: str) -> None:
    db = SessionLocal()
    try:
        task = get_task(db, task_id)
        config = db.get(OfflineIngestionConfig, task.config_id)
        if not config:
            raise NotFoundException("offline ingestion config not found")

        _update_task(db, task, status=TASK_RUNNING, progress_percent=5, current_stage="校验入库文件", started_at=datetime.now(UTC))
        markdown_paths, faq_paths, index_csv_path = _build_task_source_paths(config, task)
        _update_task(db, task, progress_percent=15, current_stage="准备模型和向量库")

        settings = _settings_from_config(
            config,
            source_data_root=task.source_data_root,
            clean_markdown_dir=task.clean_markdown_dir,
            index_csv_name=task.index_csv_name,
            faq_csv_dir=task.faq_csv_dir,
        )
        runtime = get_runtime_config()
        embedding_provider = BGEM3EmbeddingProvider(
            BGEModelConfig(
                model_path=runtime.app.models.embedding_model_path,
                device=os.getenv("KNOWFORGE_EMBEDDING_DEVICE", "cuda"),
                use_fp16=os.getenv("KNOWFORGE_EMBEDDING_FP16", "false").lower() == "true",
                batch_size=settings.embedding_batch_size,
            )
        )
        vectorization_service = VectorizationService(
            dense_provider=embedding_provider,
            sparse_provider=None,
            batch_size=settings.embedding_batch_size,
        )
        writer = MilvusIngestionWriter(settings)
        if task.ingest_type in {INGEST_TYPE_DOCUMENT, INGEST_TYPE_FAQ}:
            _ensure_staged_version_baseline(db, task, writer)
        pipeline = OfflineIngestionPipeline(
            settings,
            vectorization_service=vectorization_service,
            writer=writer,
            kb_version=task.kb_version,
            db_session=db,
            version_created_by=str(task.created_by) if task.created_by else None,
            version_description=task.version_description,
        )

        _update_task(db, task, progress_percent=25, current_stage="清洗、向量化并写入 Milvus")
        batch = pipeline.ingest(markdown_paths=markdown_paths, faq_paths=faq_paths, index_csv_path=index_csv_path)
        task.kb_version = pipeline.kb_version
        task.document_count = len(batch.documents)
        task.parent_chunk_count = len(batch.parent_chunks)
        task.child_chunk_count = len(batch.child_chunks)
        task.faq_count = len(batch.faq_records)
        _update_version_content_state(db, task, writer)

        if task.auto_publish:
            task.current_stage = "发布知识库版本"
            task.progress_percent = 92
            db.flush()
            KbVersionService(db).publish(
                pipeline.kb_version,
                operator_id=str(task.created_by) if task.created_by else None,
                message="auto publish after offline ingestion",
            )

        task.status = TASK_COMPLETED
        task.progress_percent = 100
        task.current_stage = "完成"
        task.finished_at = datetime.now(UTC)
        db.commit()
    except Exception as exc:
        db.rollback()
        task = db.execute(select(OfflineIngestionTask).where(OfflineIngestionTask.task_id == task_id)).scalar_one_or_none()
        if task:
            task.status = TASK_FAILED
            task.progress_percent = task.progress_percent or 0
            task.current_stage = "失败"
            task.error_message = str(exc)
            task.finished_at = datetime.now(UTC)
            db.commit()
    finally:
        db.close()


def _ensure_staged_version_baseline(
    db: Session,
    task: OfflineIngestionTask,
    writer: MilvusIngestionWriter,
) -> None:
    """首次向 staged 版本入库前，从当前 active 版本复制完整基线。"""

    if not task.kb_version:
        raise BadRequestException("kb_version is required for upload ingestion task")

    service = KbVersionService(db)
    target = service.repo.get_version(task.kb_version, for_update=True)
    if not target:
        raise NotFoundException("kb version not found")
    if target["status"] != "staged":
        raise BadRequestException("offline ingestion can only write to staged kb version")

    active = service.repo.get_active_version()
    if not active:
        return
    active_version = active["kb_version"]
    if active_version == task.kb_version:
        return

    if task.ingest_type == INGEST_TYPE_DOCUMENT:
        if not target["doc_ready"]:
            _update_task(db, task, progress_percent=18, current_stage="复制当前 active 文档基线")
            writer.copy_documents_between_versions(active_version, task.kb_version)
        if not target["faq_ready"]:
            _update_task(db, task, progress_percent=20, current_stage="复制当前 active FAQ 基线")
            copied_faq = writer.copy_faq_between_versions(active_version, task.kb_version)
            service.repo.update_content_state(task.kb_version, faq_ready=True, faq_count=copied_faq)
            db.flush()
        return

    if task.ingest_type == INGEST_TYPE_FAQ:
        if not target["faq_ready"]:
            _update_task(db, task, progress_percent=18, current_stage="复制当前 active FAQ 基线")
            writer.copy_faq_between_versions(active_version, task.kb_version)
        if not target["doc_ready"]:
            _update_task(db, task, progress_percent=20, current_stage="复制当前 active 文档基线")
            copied_doc_chunks = writer.copy_documents_between_versions(active_version, task.kb_version)
            document_count = writer.count_document_sources_by_version(task.kb_version)
            service.repo.update_content_state(
                task.kb_version,
                doc_ready=True,
                document_count=document_count,
                child_chunk_count=copied_doc_chunks,
            )
            db.flush()


def _update_version_content_state(
    db: Session,
    task: OfflineIngestionTask,
    writer: MilvusIngestionWriter,
) -> None:
    """入库完成后更新版本内容状态和统计。"""

    if not task.kb_version:
        return

    service = KbVersionService(db)
    if task.ingest_type == INGEST_TYPE_DOCUMENT:
        document_count = writer.count_document_sources_by_version(task.kb_version)
        child_chunk_count = writer.count_documents_by_version(task.kb_version)
        service.repo.update_content_state(
            task.kb_version,
            doc_ready=True,
            document_count=document_count,
            child_chunk_count=child_chunk_count,
        )
        task.document_count = document_count
        task.child_chunk_count = child_chunk_count
        return

    if task.ingest_type == INGEST_TYPE_FAQ:
        faq_count = writer.count_faq_by_version(task.kb_version)
        service.repo.update_content_state(task.kb_version, faq_ready=True, faq_count=faq_count)
        task.faq_count = faq_count
        return

    if task.ingest_type == INGEST_TYPE_MIXED:
        document_count = writer.count_document_sources_by_version(task.kb_version)
        child_chunk_count = writer.count_documents_by_version(task.kb_version)
        faq_count = writer.count_faq_by_version(task.kb_version)
        service.repo.update_content_state(
            task.kb_version,
            doc_ready=True,
            faq_ready=True,
            document_count=document_count,
            child_chunk_count=child_chunk_count,
            faq_count=faq_count,
        )


def _update_task(db: Session, task: OfflineIngestionTask, **values: object) -> None:
    for key, value in values.items():
        setattr(task, key, value)
    db.commit()
    db.refresh(task)


def _settings_from_config(
    config: OfflineIngestionConfig,
    *,
    source_data_root: str | None = None,
    clean_markdown_dir: str | None = None,
    index_csv_name: str | None = None,
    faq_csv_dir: str | None = None,
) -> IngestionSettings:
    return IngestionSettings(
        source_data_root=_resolve_path(source_data_root or config.source_data_root),
        clean_markdown_dir=clean_markdown_dir or config.clean_markdown_dir,
        index_csv_name=index_csv_name or config.index_csv_name,
        faq_csv_dir=faq_csv_dir or config.faq_csv_dir,
        doc_parent_chunk_size=config.doc_parent_chunk_size,
        doc_child_chunk_size=config.doc_child_chunk_size,
        doc_child_chunk_overlap=config.doc_child_chunk_overlap,
        table_split_strategy=config.table_split_strategy,
        table_header_required=config.table_header_required,
        table_row_max_chars=config.table_row_max_chars,
        rule_metadata_filter_keys=tuple(config.rule_metadata_filter_keys or []),
        doc_collection_name=config.doc_collection_name,
        faq_collection_name=config.faq_collection_name,
        dense_vector_dim=config.dense_vector_dim,
        sparse_vector_enabled=config.sparse_vector_enabled,
        embedding_batch_size=config.embedding_batch_size,
        milvus_insert_batch_size=config.milvus_insert_batch_size,
        faq_reference_required=False,
        scope_enum=config.scope_enum or {},
    )


def _build_source_paths(
    config: OfflineIngestionConfig,
    *,
    source_data_root: str | None = None,
    clean_markdown_dir: str | None = None,
    index_csv_name: str | None = None,
    faq_csv_dir: str | None = None,
) -> tuple[list[Path], list[Path], Path]:
    settings = _settings_from_config(
        config,
        source_data_root=source_data_root,
        clean_markdown_dir=clean_markdown_dir,
        index_csv_name=index_csv_name,
        faq_csv_dir=faq_csv_dir,
    )
    clean_root = settings.clean_data_root
    index_csv_path = clean_root / settings.index_csv_name
    markdown_paths = sorted(clean_root.rglob("*.md"))
    faq_dir = clean_root / settings.faq_csv_dir
    faq_paths = sorted(faq_dir.glob("*.csv")) if faq_dir.exists() else []
    if not clean_root.exists():
        raise BadRequestException(f"clean markdown directory not found: {clean_root}")
    if not index_csv_path.exists():
        raise BadRequestException(f"index csv not found: {index_csv_path}")
    if not markdown_paths:
        raise BadRequestException(f"markdown files not found: {clean_root}")
    return markdown_paths, faq_paths, index_csv_path


def _build_task_source_paths(
    config: OfflineIngestionConfig,
    task: OfflineIngestionTask,
) -> tuple[list[Path], list[Path], Path | None]:
    if task.ingest_type == INGEST_TYPE_DOCUMENT:
        markdown_paths, _faq_paths, index_csv_path = _build_source_paths(
            config,
            source_data_root=task.source_data_root,
            clean_markdown_dir=task.clean_markdown_dir,
            index_csv_name=task.index_csv_name,
            faq_csv_dir=task.faq_csv_dir,
        )
        return markdown_paths, [], index_csv_path

    if task.ingest_type == INGEST_TYPE_FAQ:
        settings = _settings_from_config(
            config,
            source_data_root=task.source_data_root,
            clean_markdown_dir=task.clean_markdown_dir,
            index_csv_name=task.index_csv_name,
            faq_csv_dir=task.faq_csv_dir,
        )
        faq_dir = settings.clean_data_root / settings.faq_csv_dir
        if not faq_dir.exists():
            raise BadRequestException(f"faq directory not found: {faq_dir}")
        faq_paths = sorted(faq_dir.rglob("*.csv"))
        if not faq_paths:
            raise BadRequestException(f"faq csv files not found: {faq_dir}")
        return [], faq_paths, None

    return _build_source_paths(
        config,
        source_data_root=task.source_data_root,
        clean_markdown_dir=task.clean_markdown_dir,
        index_csv_name=task.index_csv_name,
        faq_csv_dir=task.faq_csv_dir,
    )


def _validate_source_files(
    config: OfflineIngestionConfig,
    *,
    source_data_root: str | None = None,
    clean_markdown_dir: str | None = None,
    index_csv_name: str | None = None,
    faq_csv_dir: str | None = None,
) -> None:
    _build_source_paths(
        config,
        source_data_root=source_data_root,
        clean_markdown_dir=clean_markdown_dir,
        index_csv_name=index_csv_name,
        faq_csv_dir=faq_csv_dir,
    )


def _new_task_id() -> str:
    return f"offline_ingest_{uuid.uuid4().hex[:20]}"


def _new_upload_task(
    config: OfflineIngestionConfig,
    *,
    task_id: str,
    ingest_type: str,
    upload_root: Path,
    source_data_root: str,
    clean_markdown_dir: str,
    index_csv_name: str,
    faq_csv_dir: str,
    auto_publish: bool,
    version_description: str | None,
    kb_version: str,
    created_by: int | None,
) -> OfflineIngestionTask:
    return OfflineIngestionTask(
        task_id=task_id,
        status=TASK_PENDING,
        progress_percent=0,
        current_stage="等待执行",
        kb_version=kb_version,
        config_id=config.id,
        ingest_type=ingest_type,
        upload_root=str(upload_root.relative_to(PROJECT_ROOT)),
        source_data_root=source_data_root,
        clean_markdown_dir=clean_markdown_dir,
        index_csv_name=index_csv_name,
        faq_csv_dir=faq_csv_dir,
        auto_publish=auto_publish,
        version_description=version_description,
        created_by=created_by,
    )


def _validate_scope(config: OfflineIngestionConfig, scope: str) -> None:
    if scope not in (config.scope_enum or {}):
        raise BadRequestException(f"unsupported scope: {scope}")


async def _save_upload_files(files: list[UploadFile], *, target_root: Path, allowed_suffix: str) -> list[Path]:
    if not files:
        return []
    saved_paths: list[Path] = []
    seen_paths: set[Path] = set()
    target_root.mkdir(parents=True, exist_ok=True)

    for upload in files:
        relative_path = _safe_upload_relative_path(upload.filename or "")
        if relative_path.suffix.lower() != allowed_suffix:
            continue
        destination = target_root / relative_path
        destination = destination.resolve()
        root = target_root.resolve()
        if root not in destination.parents and destination != root:
            raise BadRequestException(f"invalid upload path: {upload.filename}")
        if destination in seen_paths:
            raise BadRequestException(f"duplicate upload path: {upload.filename}")
        seen_paths.add(destination)
        destination.parent.mkdir(parents=True, exist_ok=True)
        with destination.open("wb") as file:
            while chunk := await upload.read(1024 * 1024):
                file.write(chunk)
        saved_paths.append(destination)

    return saved_paths


def _safe_upload_relative_path(filename: str) -> Path:
    normalized = filename.replace("\\", "/").strip("/")
    path = Path(normalized)
    if not normalized or path.is_absolute() or any(part in {"", ".", ".."} for part in path.parts):
        raise BadRequestException(f"invalid upload path: {filename}")
    return path


def _write_generated_index_csv(document_root: Path, markdown_paths: list[Path], *, scope: str) -> Path:
    index_csv_path = document_root / "index.csv"
    fields = [
        "rule_id",
        "scope",
        "title",
        "summary",
        "created",
        "modified",
        "active_time",
        "label_names",
        "source_url",
        "json_path",
        "markdown_path",
    ]
    with index_csv_path.open("w", encoding="utf-8-sig", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=fields)
        writer.writeheader()
        used_rule_ids: set[str] = set()
        for markdown_path in sorted(markdown_paths):
            relative_path = markdown_path.relative_to(document_root).as_posix()
            rule_id = _infer_rule_id(markdown_path, relative_path)
            if rule_id in used_rule_ids:
                rule_id = stable_id(relative_path, length=20)
            used_rule_ids.add(rule_id)
            title, summary = _extract_markdown_title_summary(markdown_path)
            writer.writerow(
                {
                    "rule_id": rule_id,
                    "scope": scope,
                    "title": title,
                    "summary": summary,
                    "created": "",
                    "modified": "",
                    "active_time": "",
                    "label_names": "",
                    "source_url": _build_rule_source_url(rule_id),
                    "json_path": "",
                    "markdown_path": relative_path,
                }
            )
    return index_csv_path


def _infer_rule_id(path: Path, relative_path: str) -> str:
    prefix = path.stem.split("_", 1)[0].strip()
    if prefix.isdigit():
        return prefix
    return stable_id(relative_path, length=20)


def _extract_markdown_title_summary(path: Path) -> tuple[str, str]:
    text = path.read_text(encoding="utf-8", errors="ignore")
    title = ""
    summary = ""
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        if not title and line.startswith("#"):
            title = line.lstrip("#").strip()
            continue
        if not summary and not line.startswith("#"):
            summary = line[:160]
        if title and summary:
            break
    if not title:
        title = path.stem
    if not summary:
        summary = title
    return title, summary


def _build_rule_source_url(rule_id: str) -> str:
    if rule_id.isdigit():
        return f"https://learn-jdm.jd.com/knowledge/rule/detail?ruleId={rule_id}"
    return ""


def _rewrite_faq_csv_with_scope(path: Path, *, scope: str) -> None:
    fieldnames, rows = _read_faq_csv_raw(path)
    field_map = _build_faq_field_map(fieldnames)
    normalized_fieldnames = _normalize_faq_fieldnames(fieldnames, field_map)
    for field in FAQ_CANONICAL_FIELDNAMES:
        if field not in normalized_fieldnames:
            normalized_fieldnames.append(field)

    normalized_rows = []
    for row in rows:
        normalized = {}
        for field in normalized_fieldnames:
            source_field = field_map.get(field, field)
            normalized[field] = row.get(source_field, "") or ""
        # FAQ 上传时以页面选择的知识库范围为准，避免 CSV 中遗留的错误 scope 污染新版本。
        normalized["scope"] = scope
        normalized_rows.append(normalized)

    with path.open("w", encoding="utf-8-sig", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=normalized_fieldnames)
        writer.writeheader()
        writer.writerows(normalized_rows)


def _read_faq_csv_raw(path: Path) -> tuple[list[str], list[dict[str, str]]]:
    last_error: Exception | None = None
    missing_required: set[str] | None = None
    for encoding in ("utf-8-sig", "utf-8", "gb18030", "gbk"):
        try:
            with path.open("r", encoding=encoding, newline="") as file:
                reader = csv.DictReader(file)
                if reader.fieldnames is None:
                    raise BadRequestException(f"faq csv has no header: {path.name}")
                fieldnames = list(reader.fieldnames)
                field_map = _build_faq_field_map(fieldnames)
                found_fields = set(field_map)
                if not (FAQ_UPLOAD_REQUIRED_FIELDS <= found_fields):
                    missing_required = FAQ_UPLOAD_REQUIRED_FIELDS - found_fields
                    last_error = ValueError(f"FAQ CSV required fields not found with encoding {encoding}")
                    continue
                return fieldnames, [dict(row) for row in reader]
        except UnicodeDecodeError as exc:
            last_error = exc
            continue
    if missing_required:
        raise BadRequestException(
            f"FAQ CSV 缺少必要字段: {sorted(missing_required)}，至少需要 question/answer，"
            f"也支持中文表头：问题/答案: {path.name}"
        ) from last_error
    raise BadRequestException(f"FAQ CSV 编码无法识别，请保存为 UTF-8 或 GBK: {path.name}") from last_error


def _build_faq_field_map(fieldnames: list[str]) -> dict[str, str]:
    aliases = {
        "question": {"question", "问题", "用户问题", "标准问题", "用户可能问的问题"},
        "answer": {"answer", "答案", "回复", "标准答案", "命中后返回的答案"},
        "source": {"source", "来源"},
        "reference_source": {"reference_source", "reference", "链接", "来源链接", "参考来源"},
        "faq_id": {"faq_id", "id", "FAQID"},
        "category": {"category", "分类"},
        "tags": {"tags", "标签"},
        "doc_refs": {"doc_refs", "关联文档", "文档引用"},
        "scope": {"scope", "知识库范围"},
    }
    normalized = {str(field).strip().lower(): field for field in fieldnames}
    field_map: dict[str, str] = {}
    for canonical, names in aliases.items():
        for name in names:
            source = normalized.get(name.lower())
            if source:
                field_map[canonical] = source
                break
    return field_map


def _normalize_faq_fieldnames(fieldnames: list[str], field_map: dict[str, str]) -> list[str]:
    reverse_map = {source: canonical for canonical, source in field_map.items()}
    result = []
    seen = set()
    for field in fieldnames:
        canonical = reverse_map.get(field, field)
        if canonical not in seen:
            result.append(canonical)
            seen.add(canonical)
    return result


def _clean_override(value: str | None, default: str) -> str:
    if value is None:
        return default
    cleaned = value.strip()
    return cleaned or default


def _resolve_path(value: str | Path) -> Path:
    path = Path(value)
    if path.is_absolute():
        return path
    return PROJECT_ROOT / path


def _list_directory_roots() -> list[Path]:
    if os.name == "nt":
        return [Path(f"{chr(code)}:\\") for code in range(65, 91) if Path(f"{chr(code)}:\\").exists()]
    return [Path("/")]


def _config_to_info(row: OfflineIngestionConfig) -> dict:
    return {
        "id": row.id,
        "config_name": row.config_name,
        "is_enabled": row.is_enabled,
        "status": "active" if row.is_enabled else "standby",
        "created_by": row.created_by,
        "source_data_root": row.source_data_root,
        "clean_markdown_dir": row.clean_markdown_dir,
        "index_csv_name": row.index_csv_name,
        "faq_csv_dir": row.faq_csv_dir,
        "doc_parent_chunk_size": row.doc_parent_chunk_size,
        "doc_child_chunk_size": row.doc_child_chunk_size,
        "doc_child_chunk_overlap": row.doc_child_chunk_overlap,
        "table_split_strategy": row.table_split_strategy,
        "table_header_required": row.table_header_required,
        "table_row_max_chars": row.table_row_max_chars,
        "rule_metadata_filter_keys": row.rule_metadata_filter_keys or [],
        "doc_collection_name": row.doc_collection_name,
        "faq_collection_name": row.faq_collection_name,
        "dense_vector_dim": row.dense_vector_dim,
        "sparse_vector_enabled": row.sparse_vector_enabled,
        "embedding_batch_size": row.embedding_batch_size,
        "milvus_insert_batch_size": row.milvus_insert_batch_size,
        "scope_enum": row.scope_enum or {},
        "created_at": row.created_at,
        "updated_at": row.updated_at,
    }


def _task_to_info(row: OfflineIngestionTask) -> dict:
    return {
        "id": row.id,
        "task_id": row.task_id,
        "status": row.status,
        "progress_percent": row.progress_percent,
        "current_stage": row.current_stage,
        "kb_version": row.kb_version,
        "config_id": row.config_id,
        "ingest_type": row.ingest_type,
        "upload_root": row.upload_root,
        "source_data_root": row.source_data_root,
        "clean_markdown_dir": row.clean_markdown_dir,
        "index_csv_name": row.index_csv_name,
        "faq_csv_dir": row.faq_csv_dir,
        "auto_publish": row.auto_publish,
        "version_description": row.version_description,
        "document_count": row.document_count,
        "parent_chunk_count": row.parent_chunk_count,
        "child_chunk_count": row.child_chunk_count,
        "faq_count": row.faq_count,
        "error_message": row.error_message,
        "created_by": row.created_by,
        "started_at": row.started_at,
        "finished_at": row.finished_at,
        "created_at": row.created_at,
        "updated_at": row.updated_at,
    }
