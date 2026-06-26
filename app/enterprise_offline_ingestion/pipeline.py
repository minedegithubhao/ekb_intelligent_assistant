"""企业级离线入库编排层。

这一层把读取、清洗、切分、向量化和写入串起来，但不内置具体模型实现，
便于替换和测试。
"""

from __future__ import annotations

from pathlib import Path

from app.enterprise_offline_ingestion.cleaner import FAQCleaner, MarkdownCleaner
from app.enterprise_offline_ingestion.index_reader import IndexRepository
from app.enterprise_offline_ingestion.models import IngestionBatch
from app.enterprise_offline_ingestion.settings import IngestionSettings
from app.enterprise_offline_ingestion.splitter import MarkdownSplitter
from app.enterprise_offline_ingestion.vectorization import VectorizationService
from app.kb_version.service import generate_kb_version


class OfflineIngestionPipeline:
    """离线入库总流程编排器。"""

    def __init__(
        self,
        settings: IngestionSettings,
        *,
        vectorization_service: VectorizationService | None = None,
        writer: object | None = None,
        kb_version: str | None = None,
    ) -> None:
        settings.validate()
        self.settings = settings
        self.index_repository = IndexRepository(settings)
        self.markdown_cleaner = MarkdownCleaner(settings)
        self.faq_cleaner = FAQCleaner(reference_required=settings.faq_reference_required)
        self.splitter = MarkdownSplitter(settings)
        self.vectorization_service = vectorization_service
        self.writer = writer
        self.kb_version = kb_version or generate_kb_version()

    def prepare(
        self,
        *,
        markdown_paths: list[Path],
        faq_paths: list[Path] | None = None,
        index_csv_path: Path | None = None,
    ) -> IngestionBatch:
        """只做准备，不写外部系统。

        适合做预览、单元测试和数据校验。这个阶段会完成：
        1. 读取 index.csv
        2. 清洗 Markdown
        3. 切分父子块
        4. 读取 FAQ
        """

        index_records = self.index_repository.load(index_csv_path)
        documents = []
        parents = []
        children = []

        for path in markdown_paths:
            # 文件名前缀的 rule_id 用于关联 index.csv 的索引记录。
            rule_id = path.stem.split("_", 1)[0]
            index_record = index_records.get(rule_id)
            if index_record is None and self.settings.strict_index_match:
                raise ValueError(f"Markdown 文件 {path.name} 未在 index.csv 中找到 rule_id={rule_id!r} 的记录")
            document = self.markdown_cleaner.clean(path, index_record, kb_version=self.kb_version)
            doc_parents, doc_children = self.splitter.split(document)
            documents.append(document)
            parents.extend(doc_parents)
            children.extend(doc_children)

        faq_records = []
        for path in faq_paths or []:
            faq_records.extend(self.faq_cleaner.load(path, kb_version=self.kb_version))

        return IngestionBatch(
            documents=documents,
            parent_chunks=parents,
            child_chunks=children,
            faq_records=faq_records,
        )

    def ingest(
        self,
        *,
        markdown_paths: list[Path],
        faq_paths: list[Path] | None = None,
        index_csv_path: Path | None = None,
    ) -> IngestionBatch:
        """执行完整入库。

        这里要求调用方显式注入真实向量化服务和写入器，避免把环境依赖
        隐藏在流程内部。
        """

        if self.vectorization_service is None:
            raise ValueError("执行 ingest 前必须提供 vectorization_service")
        if self.writer is None:
            raise ValueError("执行 ingest 前必须提供 writer")

        batch = self.prepare(markdown_paths=markdown_paths, faq_paths=faq_paths, index_csv_path=index_csv_path)
        self._delete_existing(batch)
        document_rows = self.vectorization_service.vectorize_documents(batch.child_chunks)
        self.writer.write_documents(document_rows)

        if batch.faq_records:
            faq_rows = self.vectorization_service.vectorize_faq(batch.faq_records)
            self.writer.write_faq(faq_rows)
        return batch

    def _delete_existing(self, batch: IngestionBatch) -> None:
        """在写入前删除同业务键旧数据，保证重跑幂等。"""

        if hasattr(self.writer, "delete_documents_by_source_doc_ids"):
            source_doc_ids = sorted({str(document.metadata["source_doc_id"]) for document in batch.documents})
            if source_doc_ids:
                self.writer.delete_documents_by_source_doc_ids(source_doc_ids, kb_version=self.kb_version)
        if hasattr(self.writer, "delete_faq_by_ids"):
            faq_ids = sorted({record.faq_id for record in batch.faq_records})
            if faq_ids:
                self.writer.delete_faq_by_ids(faq_ids, kb_version=self.kb_version)
