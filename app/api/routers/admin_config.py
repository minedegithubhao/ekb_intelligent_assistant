"""Admin retrieval runtime configuration APIs."""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.api.deps import CurrentUser, require_admin
from app.core.response import success_response
from app.db.mysql import get_db
from app.schemas.config import DashboardConfigSave
from app.schemas.retrieval_config import (
    RetrievalKeywordRuleKeywordsUpdate,
    RetrievalTermNormalizationCreate,
    RetrievalTermNormalizationUpdate,
)
from app.services.retrieval_config import (
    activate_hot_config,
    build_dashboard_payload,
    create_term_normalization,
    delete_term_normalization,
    get_effective_retrieval_config,
    keyword_rule_to_info,
    list_hot_configs,
    list_keyword_rules,
    list_term_normalizations,
    save_hot_config,
    term_normalization_to_info,
    update_keyword_rule_keywords,
    update_term_normalization,
)

router = APIRouter(prefix="/admin", dependencies=[Depends(require_admin)])


@router.get("/dashboard/config")
def get_dashboard_config(db: Session = Depends(get_db)) -> dict:
    config, hot_config, source = get_effective_retrieval_config(db)
    return success_response(build_dashboard_payload(config, hot_config, source))


@router.put("/dashboard/config")
def save_dashboard_config(
    payload: DashboardConfigSave,
    current_user: CurrentUser = Depends(require_admin),
    db: Session = Depends(get_db),
) -> dict:
    hot_config = save_hot_config(
        db,
        config=payload.config,
        created_by=current_user.id,
        description=payload.description,
        activate=False,
    )
    db.flush()
    db.refresh(hot_config)
    return success_response({"id": hot_config.id, "config_name": hot_config.config_name, "status": "standby"})


@router.get("/config/versions")
def get_config_versions(db: Session = Depends(get_db)) -> dict:
    return success_response(list_hot_configs(db))


@router.post("/config/versions")
def create_version(
    payload: DashboardConfigSave,
    current_user: CurrentUser = Depends(require_admin),
    db: Session = Depends(get_db),
) -> dict:
    hot_config = save_hot_config(
        db,
        config=payload.config,
        created_by=current_user.id,
        description=payload.description,
        activate=False,
    )
    db.flush()
    db.refresh(hot_config)
    return success_response(
        {
            "id": hot_config.id,
            "config_name": hot_config.config_name,
            "version_no": hot_config.id,
            "status": "standby",
        }
    )


@router.post("/config/versions/{version_id}/activate")
def activate_version(
    version_id: int,
    current_user: CurrentUser = Depends(require_admin),
    db: Session = Depends(get_db),
) -> dict:
    hot_config = activate_hot_config(db, config_id=version_id, activated_by=current_user.id)
    db.flush()
    db.refresh(hot_config)
    return success_response(
        {
            "id": hot_config.id,
            "config_name": hot_config.config_name,
            "version_no": hot_config.id,
            "status": "active" if hot_config.is_enabled else "standby",
            "activated_at": hot_config.activated_at,
        }
    )


@router.get("/retrieval/keyword-rules")
def get_keyword_rules(db: Session = Depends(get_db)) -> dict:
    return success_response(list_keyword_rules(db))


@router.put("/retrieval/keyword-rules/{rule_code}/keywords")
def update_keywords(
    rule_code: str,
    payload: RetrievalKeywordRuleKeywordsUpdate,
    current_user: CurrentUser = Depends(require_admin),
    db: Session = Depends(get_db),
) -> dict:
    row = update_keyword_rule_keywords(
        db,
        rule_code=rule_code,
        keywords=payload.keywords,
        updated_by=current_user.id,
    )
    return success_response(keyword_rule_to_info(row))


@router.get("/retrieval/term-normalizations")
def get_term_normalizations(db: Session = Depends(get_db)) -> dict:
    return success_response(list_term_normalizations(db))


@router.post("/retrieval/term-normalizations")
def create_normalization(
    payload: RetrievalTermNormalizationCreate,
    current_user: CurrentUser = Depends(require_admin),
    db: Session = Depends(get_db),
) -> dict:
    row = create_term_normalization(db, payload=payload, created_by=current_user.id)
    return success_response(term_normalization_to_info(row))


@router.put("/retrieval/term-normalizations/{term_id}")
def update_normalization(
    term_id: int,
    payload: RetrievalTermNormalizationUpdate,
    current_user: CurrentUser = Depends(require_admin),
    db: Session = Depends(get_db),
) -> dict:
    row = update_term_normalization(db, term_id=term_id, payload=payload, updated_by=current_user.id)
    return success_response(term_normalization_to_info(row))


@router.delete("/retrieval/term-normalizations/{term_id}")
def delete_normalization(
    term_id: int,
    current_user: CurrentUser = Depends(require_admin),
    db: Session = Depends(get_db),
) -> dict:
    return success_response(delete_term_normalization(db, term_id=term_id, updated_by=current_user.id))
