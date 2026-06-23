"""Low-level Milvus client helpers for the first backend foundation stage."""

from __future__ import annotations

import logging
import re
from collections.abc import Sequence

from pymilvus import Collection, CollectionSchema, FieldSchema, connections, db, utility

from app.core.config import get_runtime_config
from app.core.exceptions import ServiceUnavailableException

logger = logging.getLogger(__name__)


class MilvusClient:
    """Wraps pymilvus connection and collection utility operations."""

    def __init__(self) -> None:
        self.config = get_runtime_config().app.milvus

    def connect(self) -> None:
        connections.connect(
            alias=self.config.alias,
            host=self.config.host,
            port=str(self.config.port),
            db_name=self.config.database,
        )
        db.using_database(self.config.database, using=self.config.alias)

    def disconnect(self) -> None:
        connections.disconnect(self.config.alias)

    def ping(self) -> dict[str, str]:
        try:
            self.connect()
            version = utility.get_server_version(using=self.config.alias)
            return {"status": "ok", "version": version}
        except Exception as exc:
            logger.exception("milvus ping failed")
            raise ServiceUnavailableException("milvus unavailable") from exc

    def build_collection_name(self, version: str, collection_type: str = "doc") -> str:
        # Version-specific names keep future knowledge-base builds isolated.
        safe_version = re.sub(r"[^0-9a-zA-Z_]+", "_", version).strip("_").lower()
        safe_type = re.sub(r"[^0-9a-zA-Z_]+", "_", collection_type).strip("_").lower()
        return f"{self.config.collection_prefix}_{safe_type}_{safe_version}"

    def has_collection(self, name: str) -> bool:
        self.connect()
        return bool(utility.has_collection(name, using=self.config.alias))

    def create_collection(
        self,
        name: str,
        fields: Sequence[FieldSchema],
        description: str = "",
        shards_num: int = 2,
    ) -> Collection:
        self.connect()
        if self.has_collection(name):
            return Collection(name=name, using=self.config.alias)
        schema = CollectionSchema(fields=list(fields), description=description)
        return Collection(name=name, schema=schema, using=self.config.alias, shards_num=shards_num)

    def load_collection(self, name: str) -> None:
        self.connect()
        Collection(name=name, using=self.config.alias).load()

    def release_collection(self, name: str) -> None:
        self.connect()
        Collection(name=name, using=self.config.alias).release()

    def drop_collection(self, name: str) -> None:
        self.connect()
        if utility.has_collection(name, using=self.config.alias):
            utility.drop_collection(name, using=self.config.alias)


milvus_client = MilvusClient()


def ping_milvus() -> dict[str, str]:
    return milvus_client.ping()
