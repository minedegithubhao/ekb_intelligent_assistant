"""Admin APIs for fixed-format JSON vector ingestion."""

from __future__ import annotations

from fastapi import APIRouter, Depends, File, Form, UploadFile

from app.api.deps import CurrentUser, require_admin
from app.core.exceptions import BadRequestException
from app.core.response import success_response
from app.services.vector_ingest_json import JsonVectorIngestService

router = APIRouter(prefix="/admin/vector-ingest", dependencies=[Depends(require_admin)])


@router.post("/json")
async def ingest_json_vectors(
    record_type: str = Form(...),
    files: list[UploadFile] | None = File(default=None),
    file: UploadFile | None = File(default=None),
    current_user: CurrentUser = Depends(require_admin),
) -> dict:
    upload_files = [*(files or []), *([file] if file else [])]
    if not upload_files:
        raise BadRequestException("at least one json file is required")

    file_payloads = [
        (upload_file.filename or "", await upload_file.read())
        for upload_file in upload_files
    ]
    result = JsonVectorIngestService().ingest_json_files(
        files=file_payloads,
        record_type=record_type,
        imported_by=current_user.id,
    )
    return success_response(result.model_dump(mode="json"))
