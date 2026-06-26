"""Admin retrieval testing APIs."""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.api.deps import CurrentUser, require_admin
from app.core.response import success_response
from app.db.mysql import get_db
from app.schemas.admin_retrieval import AdminRetrievalTestRequest
from app.services.retrieval import inspect_retrieval_candidates, retrieve_answer

router = APIRouter(prefix="/admin/retrieval")


@router.post("/test")
def test_retrieval(
    payload: AdminRetrievalTestRequest,
    current_user: CurrentUser = Depends(require_admin),
    db: Session = Depends(get_db),
) -> dict:
    candidate_debug = inspect_retrieval_candidates(
        db,
        question=payload.question,
        knowledge_base_type=payload.knowledge_base_type,
        kb_version=payload.kb_version,
    )
    answer_result = None
    if payload.include_answer:
        result = retrieve_answer(
            db,
            question=payload.question,
            knowledge_base_type=payload.knowledge_base_type,
            kb_version=payload.kb_version,
        )
        answer_result = result.model_dump(mode="json")

    return success_response(
        {
            "question": payload.question,
            "knowledge_base_type": payload.knowledge_base_type,
            "kb_version": payload.kb_version,
            "answer_result": answer_result,
            "candidate_debug": candidate_debug,
            "tested_by": current_user.id,
        }
    )

