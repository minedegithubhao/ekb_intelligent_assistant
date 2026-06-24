"""Admin evaluation APIs."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.api.deps import require_admin
from app.core.response import page_response, success_response
from app.db.mysql import get_db
from app.evaluation.ingestion_quality.runner import (
    evaluate_chunk_quality_dataset,
    list_chunk_quality_datasets,
)
from app.schemas.evaluation import (
    EvaluationCasesImport,
    EvaluationDatasetCreate,
    IngestionQualityRunCreate,
    RetrievalRunCreate,
)
from app.services.evaluation import (
    create_dataset,
    delete_dataset,
    get_run,
    import_cases,
    list_case_results,
    list_cases,
    list_datasets,
    list_runs,
    run_ingestion_quality_evaluation,
    run_retrieval_evaluation,
)

router = APIRouter(prefix="/admin/evaluations", dependencies=[Depends(require_admin)])


@router.get("/datasets")
def get_evaluation_datasets(
    keyword: str | None = None,
    evaluation_type: str | None = None,
    db: Session = Depends(get_db),
) -> dict:
    items = list_datasets(db, keyword=keyword, evaluation_type=evaluation_type)
    return success_response({"items": items, "total": len(items)})


@router.post("/datasets")
def create_evaluation_dataset(
    payload: EvaluationDatasetCreate,
    db: Session = Depends(get_db),
) -> dict:
    return success_response(create_dataset(db, payload))


@router.delete("/datasets/{dataset_id}")
def remove_evaluation_dataset(dataset_id: str, db: Session = Depends(get_db)) -> dict:
    return success_response(delete_dataset(db, dataset_id))


@router.get("/datasets/{dataset_id}/cases")
def get_evaluation_cases(dataset_id: str, db: Session = Depends(get_db)) -> dict:
    items = list_cases(db, dataset_id)
    return success_response({"items": items, "total": len(items)})


@router.post("/datasets/{dataset_id}/cases/import")
def import_evaluation_cases(
    dataset_id: str,
    payload: EvaluationCasesImport,
    db: Session = Depends(get_db),
) -> dict:
    return success_response(import_cases(db, dataset_id, payload))


@router.post("/ingestion-quality/runs")
def create_ingestion_quality_run(
    payload: IngestionQualityRunCreate,
    db: Session = Depends(get_db),
) -> dict:
    return success_response(run_ingestion_quality_evaluation(db, payload))


@router.post("/retrieval/runs")
def create_retrieval_run(
    payload: RetrievalRunCreate,
    db: Session = Depends(get_db),
) -> dict:
    return success_response(run_retrieval_evaluation(db, payload))


@router.get("/runs")
def get_evaluation_runs(
    evaluation_type: str | None = None,
    status: str | None = None,
    keyword: str | None = None,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    db: Session = Depends(get_db),
) -> dict:
    items, total = list_runs(
        db,
        evaluation_type=evaluation_type,
        status=status,
        keyword=keyword,
        page=page,
        page_size=page_size,
    )
    return page_response(items, total, page, page_size)


@router.get("/runs/{run_id}")
def get_evaluation_run(run_id: str, db: Session = Depends(get_db)) -> dict:
    return success_response(get_run(db, run_id))


@router.get("/runs/{run_id}/cases")
def get_evaluation_run_cases(run_id: str, db: Session = Depends(get_db)) -> dict:
    items = list_case_results(db, run_id)
    return success_response({"items": items, "total": len(items)})


@router.get("/chunk-quality/datasets")
def get_chunk_quality_datasets() -> dict:
    datasets = [item.model_dump() for item in list_chunk_quality_datasets()]
    return success_response({"items": datasets, "total": len(datasets)})


@router.get("/chunk-quality/{dataset}")
def evaluate_chunk_quality(dataset: str) -> dict:
    result = evaluate_chunk_quality_dataset(dataset)
    return success_response(result.model_dump())
