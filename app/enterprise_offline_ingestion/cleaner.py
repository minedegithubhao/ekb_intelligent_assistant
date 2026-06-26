"""Markdown 和 FAQ 的清洗规则。

这里负责把原始输入整理成适合离线入库的标准文本，同时保留必要的元数据。
"""

from __future__ import annotations

import csv
import html
import re
from pathlib import Path

from app.enterprise_offline_ingestion.models import CleanedDocument, FAQRecord, IndexRecord, Metadata
from app.enterprise_offline_ingestion.settings import IngestionSettings


MARKDOWN_LINK_RE = re.compile(r"\[([^\]]+)\]\((https?://[^)]+)\)")
HTML_LINK_RE = re.compile(r"<a\b[^>]*href=[\"'][^\"']+[\"'][^>]*>(.*?)</a>", re.IGNORECASE)
BARE_URL_RE = re.compile(r"https?://[^\s)>\]]+")
DELIMITER_RE = re.compile(r"[,，、;；|]+")


def normalize_text(text: str) -> str:
    """标准化换行和不可见空白。

    先统一字符形态，再做规则匹配，可以避免不同来源文件带来的格式差异。
    """

    return text.replace("\r\n", "\n").replace("\r", "\n").replace("\ufeff", "").replace("\u00a0", " ")


def strip_links_keep_text(text: str) -> str:
    """保留链接锚文本，移除 URL 地址。

    检索阶段更关心语义文本，而不是长 URL，所以正文中只保留可读文本。
    """

    text = HTML_LINK_RE.sub(lambda match: html.unescape(match.group(1)).strip(), text)
    text = MARKDOWN_LINK_RE.sub(lambda match: match.group(1).strip(), text)
    return BARE_URL_RE.sub("", text)


def split_delimited_text(value: str) -> list[str]:
    """把逗号/顿号/分号等分隔的文本拆成列表。"""

    return [item.strip() for item in DELIMITER_RE.split(value) if item.strip()]


class MarkdownCleaner:
    """按照企业级离线入库规则清洗 Markdown。"""

    def __init__(self, settings: IngestionSettings) -> None:
        self.settings = settings
        keys = "|".join(re.escape(key) for key in settings.rule_metadata_filter_keys)
        self.rule_meta_re = re.compile(rf"^\s*[-*]\s*({keys})\s*:\s*(.*)\s*$")

    def clean(
        self,
        path: Path,
        index_record: IndexRecord | None = None,
        *,
        kb_version: str = "",
    ) -> CleanedDocument:
        """清洗单个 Markdown 文件。

        处理顺序：
        1. 统一文本格式
        2. 过滤开头规则元信息块
        3. 清理链接
        4. 合并并压缩空行
        5. 将索引表中的字段补充到 metadata
        """

        raw = normalize_text(path.read_text(encoding="utf-8"))
        lines = raw.split("\n")
        body_lines: list[str] = []
        extracted: Metadata = {}
        leading_area = True

        for line in lines:
            match = self.rule_meta_re.match(line)
            if leading_area and match:
                # 红框中的元信息块不进入正文，不参与 chunk、embedding 和 BM25。
                extracted[match.group(1)] = match.group(2).strip()
                continue

            body_lines.append(strip_links_keep_text(line).rstrip())
            stripped = line.strip()
            if stripped and not stripped.startswith("#"):
                leading_area = False

        metadata = self._build_metadata(path, extracted, index_record, kb_version=kb_version)
        return CleanedDocument(
            path=path,
            content=self._collapse_blank_lines(body_lines),
            metadata=metadata,
        )

    def _build_metadata(
        self,
        path: Path,
        extracted: Metadata,
        index_record: IndexRecord | None,
        *,
        kb_version: str = "",
    ) -> Metadata:
        """合并文档头部元信息和 index.csv 元数据。"""

        metadata: Metadata = dict(extracted)
        if index_record is not None:
            metadata.update(
                {
                    "rule_id": index_record.rule_id,
                    "scope": index_record.scope,
                    "scope_name": self.settings.scope_enum[index_record.scope],
                    "title": index_record.title,
                    "summary": index_record.summary,
                    "created": index_record.created,
                    "modified": index_record.modified,
                    "active_time": index_record.active_time,
                    "label_names": index_record.label_names,
                    "source_url": index_record.source_url,
                    "json_path": index_record.json_path,
                    "markdown_path": index_record.markdown_path,
                }
            )

        metadata.setdefault("rule_id", path.stem.split("_", 1)[0])
        metadata.setdefault("scope", "")
        metadata.setdefault("source_url", "")
        metadata["source_doc_id"] = metadata["rule_id"]
        metadata["reference_source"] = metadata["source_url"]
        metadata["file_name"] = path.name
        metadata["label_list"] = split_delimited_text(str(metadata.get("label_names", "")))
        metadata["record_type"] = "document_chunk"
        metadata["kb_version"] = kb_version
        return metadata

    @staticmethod
    def _collapse_blank_lines(lines: list[str]) -> str:
        """把连续空行压缩成一个空行，并保证结尾结构干净。"""

        cleaned: list[str] = []
        previous_blank = False
        for line in lines:
            is_blank = not line.strip()
            if is_blank:
                if cleaned and not previous_blank:
                    cleaned.append("")
                previous_blank = True
                continue
            cleaned.append(line.rstrip())
            previous_blank = False
        while cleaned and cleaned[-1] == "":
            cleaned.pop()
        return "\n".join(cleaned).strip() + "\n"


class FAQCleaner:
    """读取 FAQ CSV。

    每一行 FAQ 都保持为完整逻辑块，不做长文本切分。
    """

    REQUIRED_FIELDS = {"question", "answer", "source", "reference_source"}

    def __init__(self, reference_required: bool = True) -> None:
        self.reference_required = reference_required

    def load(self, path: Path, *, kb_version: str = "") -> list[FAQRecord]:
        """读取并清洗 FAQ CSV。"""

        with path.open("r", encoding="utf-8-sig", newline="") as file:
            reader = csv.DictReader(file)
            missing = self.REQUIRED_FIELDS - set(reader.fieldnames or [])
            if missing:
                raise ValueError(f"FAQ CSV 缺少必要字段: {sorted(missing)}")

            records: list[FAQRecord] = []
            for row_number, row in enumerate(reader, start=1):
                question = self._clean_cell(row.get("question", ""))
                answer = self._clean_cell(row.get("answer", ""))
                source = self._clean_reference_cell(row.get("source", ""))
                reference_source = self._clean_reference_cell(row.get("reference_source", ""))
                if not question or not answer:
                    raise ValueError(f"FAQ 第 {row_number} 行的 question 和 answer 不能为空")
                if self.reference_required and not reference_source:
                    raise ValueError(f"FAQ 第 {row_number} 行的 reference_source 不能为空")
                records.append(
                    FAQRecord(
                        faq_id=self._clean_cell(row.get("faq_id", "")) or f"{path.stem}-{row_number}",
                        question=question,
                        answer=answer,
                        source=source,
                        reference_source=reference_source,
                        category=self._clean_cell(row.get("category", "")),
                        tags=self._clean_cell(row.get("tags", "")),
                        doc_refs=self._clean_cell(row.get("doc_refs", "")),
                        metadata={
                            "file_name": path.name,
                            "row_number": row_number,
                            "kb_version": kb_version,
                        },
                    )
                )
            return records

    @staticmethod
    def _clean_cell(value: str) -> str:
        """清理 FAQ 单元格中的多余空白和 URL。"""

        return re.sub(r"\s+", " ", strip_links_keep_text(normalize_text(value))).strip()

    @staticmethod
    def _clean_reference_cell(value: str) -> str:
        """清理来源字段中的多余空白，但保留原始 URL。"""

        return re.sub(r"\s+", " ", normalize_text(value)).strip()
