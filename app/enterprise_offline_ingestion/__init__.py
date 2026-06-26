"""企业级离线入库模块入口。

这里只导出离线入库相关能力，不自动挂载 FastAPI 路由，也不修改现有业务服务。
后续如果要在接口层或脚本层调用，需要由调用方显式创建 pipeline 或 factory 产物。
"""

from app.enterprise_offline_ingestion.factory import (
    build_default_offline_ingestion_pipeline,
    build_default_vectorization_service,
)
from app.enterprise_offline_ingestion.pipeline import OfflineIngestionPipeline
from app.enterprise_offline_ingestion.settings import IngestionSettings

__all__ = [
    "IngestionSettings",
    "OfflineIngestionPipeline",
    "build_default_offline_ingestion_pipeline",
    "build_default_vectorization_service",
]
