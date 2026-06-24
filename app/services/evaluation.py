"""Business services for evaluation datasets, runs, and mock execution."""

from __future__ import annotations

from dataclasses import asdict
from datetime import datetime
from zoneinfo import ZoneInfo
from typing import Any
from uuid import uuid4

from sqlalchemy import delete, func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.exceptions import BadRequestException, NotFoundException
from app.db.models.evaluation import EvaluationCase, EvaluationCaseResult, EvaluationDataset, EvaluationRun
from app.evaluation.ingestion_quality.runner import evaluate_chunk_quality_dataset
from app.evaluation.retrieval.metrics import score_case
from app.evaluation.retrieval.schemas import FAQHit, KBHit, RetrievalEvalCase, RetrievalEvalConfig, RetrievalTrace
from app.schemas.evaluation import (
    EVALUATION_TYPES,
    EvaluationCaseImportItem,
    EvaluationCasesImport,
    EvaluationDatasetCreate,
    IngestionQualityRunCreate,
    RetrievalRunCreate,
)

LOCAL_TZ = ZoneInfo("Asia/Singapore")


def list_datasets(
    db: Session,
    *,
    keyword: str | None = None,
    evaluation_type: str | None = None,
) -> list[dict[str, Any]]:
    case_counts = (
        select(EvaluationCase.dataset_id, func.count(EvaluationCase.id).label("sample_count"))
        .group_by(EvaluationCase.dataset_id)
        .subquery()
    )
    stmt = (
        select(EvaluationDataset, func.coalesce(case_counts.c.sample_count, 0))
        .outerjoin(case_counts, EvaluationDataset.dataset_id == case_counts.c.dataset_id)
        .order_by(EvaluationDataset.created_at.desc(), EvaluationDataset.id.desc())
    )
    filters = []
    if keyword:
        pattern = f"%{keyword.strip()}%"
        filters.append(or_(EvaluationDataset.dataset_id.like(pattern), EvaluationDataset.name.like(pattern)))
    if evaluation_type:
        filters.append(EvaluationDataset.evaluation_type == evaluation_type)
    if filters:
        stmt = stmt.where(*filters)
    rows = db.execute(stmt).all()
    return [_dataset_to_info(row, int(sample_count or 0)) for row, sample_count in rows]


def create_dataset(db: Session, payload: EvaluationDatasetCreate) -> dict[str, Any]:
    _validate_evaluation_type(payload.evaluation_type)
    row = EvaluationDataset(
        dataset_id=payload.dataset_id.strip(),
        name=payload.name.strip(),
        evaluation_type=payload.evaluation_type,
        description=payload.description,
    )
    db.add(row)
    try:
        db.flush()
    except IntegrityError as exc:
        raise BadRequestException("evaluation dataset_id already exists") from exc
    return _dataset_to_info(row, 0)


def list_cases(db: Session, dataset_id: str) -> list[dict[str, Any]]:
    _get_dataset(db, dataset_id)
    rows = db.execute(
        select(EvaluationCase)
        .where(EvaluationCase.dataset_id == dataset_id)
        .order_by(EvaluationCase.created_at.asc(), EvaluationCase.id.asc())
    ).scalars()
    return [_case_to_info(row) for row in rows]


def import_cases(db: Session, dataset_id: str, payload: EvaluationCasesImport) -> dict[str, Any]:
    _get_dataset(db, dataset_id)
    created = 0
    updated = 0
    for item in payload.items:
        existing = db.execute(
            select(EvaluationCase).where(
                EvaluationCase.dataset_id == dataset_id,
                EvaluationCase.case_id == item.case_id,
            )
        ).scalar_one_or_none()
        if existing:
            if not payload.overwrite:
                continue
            _apply_case_values(existing, item)
            updated += 1
        else:
            db.add(
                EvaluationCase(
                    dataset_id=dataset_id,
                    case_id=item.case_id.strip(),
                    question=item.question.strip(),
                    expected_json=item.expected_json or {},
                    category=item.category,
                )
            )
            created += 1
    db.flush()
    return {"created": created, "updated": updated, "total": created + updated}


def run_ingestion_quality_evaluation(
    db: Session,
    payload: IngestionQualityRunCreate,
) -> dict[str, Any]:
    run_id = _new_run_id("ingest")
    config = payload.model_dump()
    row = EvaluationRun(
        run_id=run_id,
        dataset_id=None,
        evaluation_type="ingestion_quality",
        knowledge_base_version=payload.knowledge_base_version,
        config_json=config,
        status="running",
    )
    db.add(row)
    db.flush()

    try:
        result = evaluate_chunk_quality_dataset(
            payload.dataset,
            min_chunk_length=payload.min_length,
            max_chunk_length=payload.max_length,
        )
        result_dict = result.model_dump()
        chunk_metrics = result_dict.get("chunk_metrics", {})
        summary = {
            "chunk_count": chunk_metrics.get("chunk_count", 0),
            "low_quality_issue_count": chunk_metrics.get("low_quality_issue_count", 0),
            "too_short_chunk_rate": chunk_metrics.get("too_short_chunk_rate", 0),
            "too_long_chunk_rate": chunk_metrics.get("too_long_chunk_rate", 0),
            "duplicate_chunk_count": chunk_metrics.get("duplicate_chunk_count", 0),
            "duplicate_group_count": chunk_metrics.get("duplicate_group_count", 0),
        }
        row.status = "success"
        row.summary_json = summary
        row.detail_json = result_dict
        row.finished_at = _now()
    except Exception as exc:
        row.status = "failed"
        row.summary_json = {"error": str(exc)}
        row.finished_at = _now()

    db.flush()
    return run_to_info(row)


def run_retrieval_evaluation(
    db: Session,
    payload: RetrievalRunCreate,
) -> dict[str, Any]:
    dataset = _get_dataset(db, payload.dataset_id)
    if dataset.evaluation_type not in {"retrieval_eval", "mixed"}:
        raise BadRequestException("dataset is not suitable for retrieval evaluation")

    cases = list(
        db.execute(
            select(EvaluationCase)
            .where(EvaluationCase.dataset_id == payload.dataset_id)
            .order_by(EvaluationCase.created_at.asc(), EvaluationCase.id.asc())
        ).scalars()
    )
    if not cases:
        raise BadRequestException("evaluation dataset has no cases")

    config = RetrievalEvalConfig(faq_top_k=payload.faq_top_k, kb_top_k=payload.kb_top_k)
    run = EvaluationRun(
        run_id=_new_run_id("retrieval"),
        dataset_id=payload.dataset_id,
        evaluation_type="retrieval_eval",
        knowledge_base_version=payload.knowledge_base_version,
        config_json=payload.model_dump(),
        status="running",
    )
    db.add(run)
    db.flush()

    case_scores = []
    for index, row in enumerate(cases, start=1):
        eval_case = _to_retrieval_case(row, payload.knowledge_base_version)
        trace = _build_mock_trace(eval_case, index, payload)
        score = score_case(eval_case, trace, config)
        score_dict = asdict(score)
        case_scores.append(score_dict)
        db.add(
            EvaluationCaseResult(
                run_id=run.run_id,
                case_id=row.case_id,
                retrieved_items_json={
                    "question": trace.question,
                    "rewritten_query": trace.rewritten_query,
                    "faq_hits": [asdict(item) for item in trace.faq_hits],
                    "kb_hits": [asdict(item) for item in trace.kb_hits],
                    "mock_mode": payload.mock_mode,
                },
                metric_results_json={
                    "faq_hit_at_k": score.faq_hit_at_k,
                    "kb_recall_at_k": score.kb_recall_at_k,
                    "kb_rr": score.kb_rr,
                    "error": score.error,
                },
                latency_json={
                    "total_ms": 0,
                    "mock_mode": payload.mock_mode,
                },
            )
        )

    summary = _summarize_retrieval_scores(case_scores, config)
    run.status = "success"
    run.summary_json = summary
    run.detail_json = {"case_count": len(cases), "mock_mode": payload.mock_mode}
    run.finished_at = _now()
    db.flush()
    return run_to_info(run)


def list_runs(
    db: Session,
    *,
    evaluation_type: str | None = None,
    status: str | None = None,
    keyword: str | None = None,
    page: int = 1,
    page_size: int = 20,
) -> tuple[list[dict[str, Any]], int]:
    filters = []
    if evaluation_type:
        filters.append(EvaluationRun.evaluation_type == evaluation_type)
    if status:
        filters.append(EvaluationRun.status == status)
    if keyword:
        pattern = f"%{keyword.strip()}%"
        filters.append(
            or_(
                EvaluationRun.run_id.like(pattern),
                EvaluationRun.dataset_id.like(pattern),
                EvaluationRun.knowledge_base_version.like(pattern),
            )
        )

    count_stmt = select(func.count(EvaluationRun.id))
    stmt = select(EvaluationRun).order_by(EvaluationRun.created_at.desc(), EvaluationRun.id.desc())
    if filters:
        count_stmt = count_stmt.where(*filters)
        stmt = stmt.where(*filters)

    total = int(db.execute(count_stmt).scalar_one())
    rows = db.execute(stmt.offset((page - 1) * page_size).limit(page_size)).scalars()
    return [run_to_info(row) for row in rows], total


def get_run(db: Session, run_id: str) -> dict[str, Any]:
    return run_to_info(_get_run(db, run_id))


def list_case_results(db: Session, run_id: str) -> list[dict[str, Any]]:
    run = _get_run(db, run_id)
    rows = db.execute(
        select(EvaluationCaseResult, EvaluationCase)
        .outerjoin(
            EvaluationCase,
            (EvaluationCase.case_id == EvaluationCaseResult.case_id)
            & (EvaluationCase.dataset_id == run.dataset_id),
        )
        .where(EvaluationCaseResult.run_id == run_id)
        .order_by(EvaluationCaseResult.created_at.asc(), EvaluationCaseResult.id.asc())
    ).all()
    return [_case_result_to_info(result, case) for result, case in rows]


def delete_dataset(db: Session, dataset_id: str) -> dict[str, Any]:
    _get_dataset(db, dataset_id)
    case_count = db.execute(select(func.count(EvaluationCase.id)).where(EvaluationCase.dataset_id == dataset_id)).scalar_one()
    run_count = db.execute(select(func.count(EvaluationRun.id)).where(EvaluationRun.dataset_id == dataset_id)).scalar_one()
    if run_count:
        raise BadRequestException("dataset has evaluation runs and cannot be deleted")
    db.execute(delete(EvaluationCase).where(EvaluationCase.dataset_id == dataset_id))
    db.execute(delete(EvaluationDataset).where(EvaluationDataset.dataset_id == dataset_id))
    return {"dataset_id": dataset_id, "deleted_cases": int(case_count)}


def _dataset_to_info(row: EvaluationDataset, sample_count: int) -> dict[str, Any]:
    return {
        "id": row.id,
        "dataset_id": row.dataset_id,
        "name": row.name,
        "evaluation_type": row.evaluation_type,
        "description": row.description,
        "sample_count": sample_count,
        "created_at": row.created_at,
    }


def _case_to_info(row: EvaluationCase) -> dict[str, Any]:
    return {
        "id": row.id,
        "case_id": row.case_id,
        "dataset_id": row.dataset_id,
        "question": row.question,
        "expected_json": row.expected_json or {},
        "category": row.category,
        "created_at": row.created_at,
    }


def run_to_info(row: EvaluationRun) -> dict[str, Any]:
    summary = row.summary_json or {}
    return {
        "id": row.id,
        "run_id": row.run_id,
        "dataset_id": row.dataset_id,
        "evaluation_type": row.evaluation_type,
        "knowledge_base_version": row.knowledge_base_version,
        "config_json": row.config_json or {},
        "status": row.status,
        "summary_json": summary,
        "detail_json": row.detail_json or {},
        "created_at": row.created_at,
        "finished_at": row.finished_at,
        "metrics_text": _metrics_text(row.evaluation_type, summary),
    }


def _case_result_to_info(result: EvaluationCaseResult, case: EvaluationCase | None) -> dict[str, Any]:
    return {
        "id": result.id,
        "run_id": result.run_id,
        "case_id": result.case_id,
        "question": case.question if case else None,
        "expected_json": case.expected_json if case else {},
        "retrieved_items_json": result.retrieved_items_json or {},
        "metric_results_json": result.metric_results_json or {},
        "actual_answer": result.actual_answer,
        "latency_json": result.latency_json or {},
        "created_at": result.created_at,
    }


def _apply_case_values(row: EvaluationCase, item: EvaluationCaseImportItem) -> None:
    row.question = item.question.strip()
    row.expected_json = item.expected_json or {}
    row.category = item.category


def _get_dataset(db: Session, dataset_id: str) -> EvaluationDataset:
    row = db.execute(select(EvaluationDataset).where(EvaluationDataset.dataset_id == dataset_id)).scalar_one_or_none()
    if not row:
        raise NotFoundException("evaluation dataset not found")
    return row


def _get_run(db: Session, run_id: str) -> EvaluationRun:
    row = db.execute(select(EvaluationRun).where(EvaluationRun.run_id == run_id)).scalar_one_or_none()
    if not row:
        raise NotFoundException("evaluation run not found")
    return row


def _validate_evaluation_type(evaluation_type: str) -> None:
    if evaluation_type not in EVALUATION_TYPES:
        raise BadRequestException(f"unsupported evaluation_type: {evaluation_type}")


def _new_run_id(prefix: str) -> str:
    stamp = _now().strftime("%Y%m%d%H%M%S")
    return f"{prefix}_{stamp}_{uuid4().hex[:8]}"


def _now() -> datetime:
    return datetime.now(LOCAL_TZ).replace(tzinfo=None)


def _to_retrieval_case(row: EvaluationCase, kb_version: str | None) -> RetrievalEvalCase:
    expected = row.expected_json or {}
    return RetrievalEvalCase(
        case_id=row.case_id,
        question=row.question,
        expected_faq_ids=[str(item) for item in expected.get("expected_faq_ids", []) if str(item).strip()],
        expected_rule_ids=[str(item) for item in expected.get("expected_rule_ids", []) if str(item).strip()],
        kb_version=kb_version,
    )


def _build_mock_trace(
    case: RetrievalEvalCase,
    index: int,
    payload: RetrievalRunCreate,
) -> RetrievalTrace:
    faq_hits: list[FAQHit] = []
    kb_hits: list[KBHit] = []
    if case.expected_faq_ids:
        faq_id = case.expected_faq_ids[0] if index % 3 != 0 else f"mock_faq_miss_{index}"
        faq_hits.append(FAQHit(faq_id=faq_id, rank=1, score=0.92, question=f"mock FAQ for {case.question[:32]}"))

    if case.expected_rule_ids:
        if index % 3 == 0:
            kb_hits.append(
                KBHit(
                    rule_id=f"mock_rule_miss_{index}",
                    chunk_id=f"mock_chunk_miss_{index}",
                    rank=1,
                    score=0.71,
                    title="Mock miss document",
                    chunk_text_preview="This mock hit intentionally misses the expected rule id.",
                )
            )
        else:
            rank = 1 if index % 2 else 2
            if rank == 2:
                kb_hits.append(
                    KBHit(
                        rule_id=f"mock_rule_noise_{index}",
                        chunk_id=f"mock_chunk_noise_{index}",
                        rank=1,
                        score=0.79,
                        title="Mock noise document",
                        chunk_text_preview="This mock hit appears before the expected rule id.",
                    )
                )
            kb_hits.append(
                KBHit(
                    rule_id=case.expected_rule_ids[0],
                    chunk_id=f"mock_chunk_{index}",
                    rank=rank,
                    score=0.88,
                    title=f"Mock KB hit {case.expected_rule_ids[0]}",
                    chunk_text_preview=f"Mock retrieval content for: {case.question[:120]}",
                )
            )

    return RetrievalTrace(
        case_id=case.case_id,
        question=case.question,
        rewritten_query=f"{case.question} mock rewrite",
        faq_hits=faq_hits[: payload.faq_top_k],
        kb_hits=kb_hits[: payload.kb_top_k],
        raw_debug_payload={"mock_mode": payload.mock_mode},
    )


def _summarize_retrieval_scores(
    rows: list[dict[str, Any]],
    config: RetrievalEvalConfig,
) -> dict[str, Any]:
    faq_scores = [row["faq_hit_at_k"] for row in rows if row.get("faq_hit_at_k") is not None]
    recall_scores = [row["kb_recall_at_k"] for row in rows if row.get("kb_recall_at_k") is not None]
    rr_scores = [row["kb_rr"] for row in rows if row.get("kb_rr") is not None]
    error_count = sum(1 for row in rows if row.get("error"))
    return {
        "case_count": len(rows),
        "error_count": error_count,
        f"faq_hit_rate_at_{config.faq_top_k}": _average(faq_scores),
        f"kb_recall_at_{config.kb_top_k}": _average(recall_scores),
        f"kb_mrr_at_{config.kb_top_k}": _average(rr_scores),
    }


def _average(values: list[float]) -> float | None:
    if not values:
        return None
    return round(sum(values) / len(values), 4)


def _metrics_text(evaluation_type: str, summary: dict[str, Any]) -> str:
    if not summary:
        return "-"
    if evaluation_type == "retrieval_eval":
        parts = []
        for key, label in (
            ("faq_hit_rate_at_5", "FAQ Hit@5"),
            ("kb_recall_at_10", "KB Recall@10"),
            ("kb_mrr_at_10", "MRR@10"),
        ):
            if summary.get(key) is not None:
                parts.append(f"{label} {summary[key]}")
        return " / ".join(parts) or "-"
    if evaluation_type == "ingestion_quality":
        return (
            f"低质量 {summary.get('low_quality_issue_count', 0)} / "
            f"过短率 {summary.get('too_short_chunk_rate', 0)} / "
            f"过长率 {summary.get('too_long_chunk_rate', 0)} / "
            f"重复组 {summary.get('duplicate_group_count', 0)}"
        )
    return "-"
