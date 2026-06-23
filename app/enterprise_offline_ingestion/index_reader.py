"""读取并校验 index.csv 索引元数据。

这一层只负责结构化读取和字段合法性校验，不处理 Markdown 正文内容。
"""

from __future__ import annotations

import csv
from pathlib import Path

from app.enterprise_offline_ingestion.models import IndexRecord
from app.enterprise_offline_ingestion.settings import IngestionSettings


REQUIRED_INDEX_FIELDS = {
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
}


class IndexRepository:
    """读取 index.csv，并按 rule_id 提供索引记录。"""

    def __init__(self, settings: IngestionSettings) -> None:
        self.settings = settings

    def load(self, path: Path | None = None) -> dict[str, IndexRecord]:
        """返回以 rule_id 为键的索引记录字典。"""

        index_path = path or self.settings.index_csv_path
        with index_path.open("r", encoding="utf-8-sig", newline="") as file:
            reader = csv.DictReader(file)
            missing = REQUIRED_INDEX_FIELDS - set(reader.fieldnames or [])
            if missing:
                raise ValueError(f"index.csv 缺少必要字段: {sorted(missing)}")

            records: dict[str, IndexRecord] = {}
            for row in reader:
                record = IndexRecord(**{field: (row.get(field) or "").strip() for field in REQUIRED_INDEX_FIELDS})
                if not record.rule_id:
                    raise ValueError("index.csv 存在空 rule_id")
                if record.scope not in self.settings.scope_enum:
                    raise ValueError(f"不支持的 scope={record.scope!r}，rule_id={record.rule_id}")
                if not record.markdown_path:
                    raise ValueError(f"rule_id={record.rule_id} 的 markdown_path 不能为空")
                if record.rule_id in records:
                    raise ValueError(f"index.csv 存在重复 rule_id={record.rule_id!r}")
                records[record.rule_id] = record
            return records
