"""基于临时 chunk 数据集的管理员评估接口。"""

from __future__ import annotations

from fastapi import APIRouter, Depends

from app.api.deps import require_admin
from app.core.response import success_response
from app.services.chunk_quality_evaluation import (
    evaluate_chunk_quality_dataset,
    list_chunk_quality_datasets,
)

router = APIRouter(prefix="/admin/evaluations", dependencies=[Depends(require_admin)])


@router.get("/chunk-quality/datasets")
def get_chunk_quality_datasets() -> dict:
    # 返回当前可用的两个临时数据集，方便前端在接入真实数据前选择评估目标。
    datasets = [item.model_dump() for item in list_chunk_quality_datasets()]
    return success_response({"items": datasets, "total": len(datasets)})


@router.get("/chunk-quality/{dataset}")
def evaluate_chunk_quality(dataset: str) -> dict:
    # 对单个权限隔离数据集执行质量评估，可选值为 enterprise 或 personal。
    result = evaluate_chunk_quality_dataset(dataset)
    return success_response(result.model_dump())
