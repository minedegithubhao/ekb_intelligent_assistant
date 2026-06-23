"""把离线入库流水线和本地 BGE-M3、Milvus 组装起来的工厂函数。"""

from __future__ import annotations

from app.core.config import get_runtime_config
from app.enterprise_offline_ingestion.bge_m3_provider import BGEM3EmbeddingProvider, BGEModelConfig
from app.enterprise_offline_ingestion.milvus_writer import MilvusIngestionWriter
from app.enterprise_offline_ingestion.pipeline import OfflineIngestionPipeline
from app.enterprise_offline_ingestion.settings import IngestionSettings
from app.enterprise_offline_ingestion.vectorization import VectorizationService


def build_default_vectorization_service(settings: IngestionSettings | None = None) -> VectorizationService:
    """根据 `config/app.yaml` 里的路径创建默认向量化服务。"""

    runtime = get_runtime_config()
    model_paths = runtime.app.models
    active_settings = settings or IngestionSettings()
    provider = BGEM3EmbeddingProvider(
        BGEModelConfig(
            model_path=model_paths.embedding_model_path,
            device="cpu",
            use_fp16=False,
            batch_size=active_settings.embedding_batch_size,
        )
    )
    return VectorizationService(
        dense_provider=provider,
        sparse_provider=provider,
        batch_size=active_settings.embedding_batch_size,
    )


def build_default_offline_ingestion_pipeline() -> OfflineIngestionPipeline:
    """创建一个可以直接使用的默认离线入库流水线。"""

    settings = IngestionSettings()
    vectorization_service = build_default_vectorization_service(settings)
    writer = MilvusIngestionWriter(settings)
    return OfflineIngestionPipeline(
        settings,
        vectorization_service=vectorization_service,
        writer=writer,
    )
