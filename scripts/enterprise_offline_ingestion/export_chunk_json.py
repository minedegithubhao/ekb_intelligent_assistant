from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Any

from app.enterprise_offline_ingestion.cleaner import FAQCleaner, split_delimited_text
from app.enterprise_offline_ingestion.index_reader import IndexRepository
from app.enterprise_offline_ingestion.models import ChildChunk, FAQRecord
from app.enterprise_offline_ingestion.pipeline import OfflineIngestionPipeline
from app.enterprise_offline_ingestion.settings import IngestionSettings


ROOT = Path(__file__).resolve().parents[2]
SOURCE_DATA_DIR = ROOT / "source_data"
RAW_DATA_DIR = SOURCE_DATA_DIR / "原始数据"
OUTPUT_DIR = SOURCE_DATA_DIR / "offline_chunk_json_exports"


def build_settings() -> IngestionSettings:
    return IngestionSettings(
        source_data_root=SOURCE_DATA_DIR,
        clean_markdown_dir="原始数据",
        index_csv_name="index.csv",
        strict_index_match=True,
        faq_reference_required=True,
    )


def build_markdown_paths(scope_name: str) -> list[Path]:
    return sorted((RAW_DATA_DIR / scope_name).glob("*.md"))


def build_faq_paths() -> list[Path]:
    return sorted((RAW_DATA_DIR / "faq").glob("*.csv"))


def prepare_output_dir() -> Path:
    if OUTPUT_DIR.exists():
        shutil.rmtree(OUTPUT_DIR)
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    return OUTPUT_DIR


def export_doc_chunks(
    pipeline: OfflineIngestionPipeline,
    *,
    markdown_paths: list[Path],
    index_csv_path: Path,
) -> list[dict[str, Any]]:
    batch = pipeline.prepare(
        markdown_paths=markdown_paths,
        faq_paths=[],
        index_csv_path=index_csv_path,
    )
    return [doc_chunk_to_json(chunk) for chunk in batch.child_chunks]


def doc_chunk_to_json(chunk: ChildChunk) -> dict[str, Any]:
    metadata = dict(chunk.metadata)
    dynamic_fields = {
        **metadata,
        "child_chunk_id": chunk.child_chunk_id,
        "parent_id": chunk.parent_id,
        "source_doc_id": chunk.source_doc_id,
        "title_path": chunk.title_path,
        "parent_content": chunk.parent_content,
        "reference_source": chunk.reference_source,
        "scope": chunk.scope,
    }
    return {
        "pk": chunk.child_chunk_id,
        "text": chunk.child_content,
        "dense": [],
        "dynamic_fields": dynamic_fields,
    }


def export_faq_records(
    faq_records: list[FAQRecord],
    *,
    index_records: dict[str, Any],
    settings: IngestionSettings,
) -> dict[str, list[dict[str, Any]]]:
    grouped: dict[str, list[dict[str, Any]]] = {
        "enterprise": [],
        "personal_individual": [],
    }
    for record in faq_records:
        scope = infer_faq_scope(record, index_records)
        scope_name = settings.scope_enum[scope]
        dynamic_fields = {
            "faq_id": record.faq_id,
            "answer": record.answer,
            "source": record.source,
            "reference_source": record.reference_source,
            "category": record.category,
            "tags": record.tags,
            "tag_list": split_delimited_text(record.tags),
            "doc_refs": record.doc_refs,
            "doc_ref_ids": split_delimited_text(record.doc_refs),
            "scope": scope,
            "scope_name": scope_name,
            "record_type": "faq",
            **record.metadata,
        }
        grouped[scope].append(
            {
                "pk": record.faq_id,
                "text": record.question,
                "dense": [],
                "dynamic_fields": dynamic_fields,
            }
        )
    return grouped


def infer_faq_scope(record: FAQRecord, index_records: dict[str, Any]) -> str:
    doc_ref_ids = split_delimited_text(record.doc_refs)
    scopes = {
        index_records[doc_ref_id].scope
        for doc_ref_id in doc_ref_ids
        if doc_ref_id in index_records
    }
    if not scopes:
        raise ValueError(f"FAQ {record.faq_id} 无法根据 doc_refs={record.doc_refs!r} 反查 scope")
    if len(scopes) > 1:
        raise ValueError(f"FAQ {record.faq_id} 命中多个 scope={sorted(scopes)}，无法唯一归类")
    return next(iter(scopes))


def write_json(path: Path, rows: list[dict[str, Any]]) -> None:
    path.write_text(
        json.dumps(rows, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def main() -> None:
    settings = build_settings()
    pipeline = OfflineIngestionPipeline(settings)
    output_dir = prepare_output_dir()
    index_csv_path = RAW_DATA_DIR / "index.csv"
    index_records = IndexRepository(settings).load(index_csv_path)

    enterprise_doc_rows = export_doc_chunks(
        pipeline,
        markdown_paths=build_markdown_paths("企业"),
        index_csv_path=index_csv_path,
    )
    personal_doc_rows = export_doc_chunks(
        pipeline,
        markdown_paths=build_markdown_paths("个体"),
        index_csv_path=index_csv_path,
    )

    faq_records: list[FAQRecord] = []
    faq_cleaner = FAQCleaner(reference_required=settings.faq_reference_required)
    for faq_path in build_faq_paths():
        faq_records.extend(faq_cleaner.load(faq_path, kb_version=pipeline.kb_version))
    faq_rows = export_faq_records(faq_records, index_records=index_records, settings=settings)

    write_json(output_dir / "doc_enterprise.json", enterprise_doc_rows)
    write_json(output_dir / "doc_personal_individual.json", personal_doc_rows)
    write_json(output_dir / "faq_enterprise.json", faq_rows["enterprise"])
    write_json(output_dir / "faq_personal_individual.json", faq_rows["personal_individual"])

    print(
        {
            "output_dir": str(output_dir),
            "doc_enterprise": len(enterprise_doc_rows),
            "doc_personal_individual": len(personal_doc_rows),
            "faq_enterprise": len(faq_rows["enterprise"]),
            "faq_personal_individual": len(faq_rows["personal_individual"]),
        }
    )


if __name__ == "__main__":
    main()
