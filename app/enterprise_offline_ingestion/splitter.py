"""Markdown 的 parent-child 切分与表格按行处理。"""

from __future__ import annotations

import hashlib
import re

from app.enterprise_offline_ingestion.models import ChildChunk, CleanedDocument, ParentChunk
from app.enterprise_offline_ingestion.settings import IngestionSettings


HEADING_RE = re.compile(r"^(#{1,6})\s+(.+?)\s*$")
TABLE_SEPARATOR_RE = re.compile(r"^\s*\|?\s*:?-{3,}:?\s*(\|\s*:?-{3,}:?\s*)+\|?\s*$")


def stable_id(*parts: str, length: int = 20) -> str:
    """生成稳定 ID。

    离线入库经常需要重复执行。稳定 ID 可以让相同内容在多次构建中
    保持可追踪，便于排查和比对。
    """

    return hashlib.sha1("|".join(parts).encode("utf-8")).hexdigest()[:length]


def is_table_row(line: str) -> bool:
    """判断一行是否是 Markdown 表格行。"""

    return line.strip().startswith("|") and line.strip().endswith("|") and line.count("|") >= 2


def is_table_separator(line: str) -> bool:
    """判断一行是否是 Markdown 表格分隔行。"""

    return bool(TABLE_SEPARATOR_RE.match(line))


def split_cells(line: str) -> list[str]:
    """把 Markdown 表格行拆成单元格。"""

    return [cell.strip() for cell in line.strip().strip("|").split("|")]


class MarkdownSplitter:
    """把 Markdown 切成父块和子块。

    父块保留章节上下文，子块负责检索。表格只按行切分，不做整表回填
    或复杂结构建模。
    """

    def __init__(self, settings: IngestionSettings) -> None:
        self.settings = settings

    def split(self, document: CleanedDocument) -> tuple[list[ParentChunk], list[ChildChunk]]:
        """切分单个清洗后的 Markdown 文档。"""

        parents: list[ParentChunk] = []
        children: list[ChildChunk] = []
        title_stack: list[str] = [str(document.metadata.get("title") or document.path.stem)]
        section_lines: list[str] = []

        def flush_section() -> None:
            """把当前章节内容落成 parent chunk，并继续生成 child chunk。"""

            content = "\n".join(section_lines).strip()
            section_lines.clear()
            if not content:
                return
            for parent_content in self._split_parent_content(content):
                parent = self._new_parent(document, " > ".join(title_stack), parent_content)
                parents.append(parent)
                children.extend(self._split_children(parent))

        for line in document.content.splitlines():
            heading = HEADING_RE.match(line)
            if heading:
                flush_section()
                level = len(heading.group(1))
                title = heading.group(2).strip()
                title_stack = title_stack[: max(1, level - 1)]
                title_stack.append(title)
                continue
            section_lines.append(line)

        flush_section()
        return parents, children

    def _split_parent_content(self, content: str) -> list[str]:
        """把过长父块按段落拆开，但尽量不破坏语义连续性。"""

        if len(content) <= self.settings.doc_parent_chunk_size:
            return [content]

        paragraphs = [item.strip() for item in re.split(r"\n\s*\n", content) if item.strip()]
        result: list[str] = []
        current: list[str] = []
        current_len = 0

        for paragraph in paragraphs:
            if current and current_len + len(paragraph) > self.settings.doc_parent_chunk_size:
                result.append("\n\n".join(current))
                current = []
                current_len = 0
            current.append(paragraph)
            current_len += len(paragraph)
        if current:
            result.append("\n\n".join(current))
        return result

    def _split_children(self, parent: ParentChunk) -> list[ChildChunk]:
        """把父块进一步拆成子块。

        普通段落按文本子块处理；Markdown 表格按行处理，并将每行转换为
        “表头=值”的形式，方便检索时命中表格语义。
        """

        children: list[ChildChunk] = []
        paragraph_lines: list[str] = []
        table_headers: list[str] = []
        in_table = False

        def flush_text() -> None:
            """把累计的普通文本落成一个或多个 text 子块。"""

            text = "\n".join(paragraph_lines).strip()
            paragraph_lines.clear()
            if not text:
                return
            for part in self._split_child_text(text):
                children.append(self._new_child(parent, part, "text", len(children) + 1))

        for line in parent.parent_content.splitlines():
            if is_table_row(line):
                flush_text()
                if not in_table:
                    table_headers = split_cells(line)
                    in_table = True
                    continue
                if is_table_separator(line):
                    continue
                row_text = self._table_row_to_text(table_headers, split_cells(line))
                if row_text:
                    children.append(self._new_child(parent, row_text, "table_row", len(children) + 1))
                continue

            in_table = False
            table_headers = []
            if line.strip():
                paragraph_lines.append(line)
            else:
                flush_text()

        flush_text()
        return children

    def _split_child_text(self, text: str) -> list[str]:
        """按配置对超长子文本做滑窗切分。"""

        if len(text) <= self.settings.doc_child_chunk_size:
            return [text]

        chunks: list[str] = []
        start = 0
        while start < len(text):
            end = min(len(text), start + self.settings.doc_child_chunk_size)
            chunks.append(text[start:end].strip())
            if end >= len(text):
                break
            start = end - self.settings.doc_child_chunk_overlap
        return [chunk for chunk in chunks if chunk]

    def _table_row_to_text(self, headers: list[str], row: list[str]) -> str:
        """把一行表格转换成“表头=值”的检索文本。"""

        if self.settings.table_header_required and not headers:
            raise ValueError("表格行切分前必须先有表头")
        pairs = []
        for index, value in enumerate(row):
            header = headers[index] if index < len(headers) and headers[index] else f"column_{index + 1}"
            pairs.append(f"{header}={value}")
        text = "；".join(pairs)
        if len(text) > self.settings.table_row_max_chars:
            raise ValueError("表格行文本超过 table_row_max_chars")
        return text

    def _new_parent(self, document: CleanedDocument, title_path: str, content: str) -> ParentChunk:
        """构造父块，并把文档 metadata 一并带过去。"""

        metadata = dict(document.metadata)
        parent_id = stable_id(str(metadata["source_doc_id"]), title_path, content)
        return ParentChunk(
            parent_id=parent_id,
            source_doc_id=str(metadata["source_doc_id"]),
            title_path=title_path,
            parent_content=content,
            reference_source=str(metadata.get("reference_source", "")),
            scope=str(metadata.get("scope", "")),
            metadata=metadata,
        )

    @staticmethod
    def _new_child(parent: ParentChunk, content: str, chunk_type: str, order: int) -> ChildChunk:
        """构造子块，保留父块上下文、chunk 类型和顺序。"""

        metadata = dict(parent.metadata)
        metadata["chunk_type"] = chunk_type
        metadata["chunk_order"] = order
        return ChildChunk(
            child_chunk_id=stable_id(parent.parent_id, chunk_type, str(order), content),
            parent_id=parent.parent_id,
            source_doc_id=parent.source_doc_id,
            title_path=parent.title_path,
            child_content=content,
            parent_content=parent.parent_content,
            reference_source=parent.reference_source,
            scope=parent.scope,
            metadata=metadata,
        )
