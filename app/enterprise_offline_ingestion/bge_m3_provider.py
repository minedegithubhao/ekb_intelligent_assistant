"""本地 BGE-M3 向量提供器。

模型采用懒加载方式，只有真正执行向量化时才会加载。这样即使当前环境
还没有安装推理依赖，项目也可以正常导入并做非推理类验证。
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class BGEModelConfig:
    """本地 BGE-M3 推理所需的最小运行参数。"""

    model_path: str
    device: str = "cpu"
    use_fp16: bool = False
    batch_size: int = 32
    max_length: int = 8192


class BGEM3EmbeddingProvider:
    """真实的本地 BGE-M3 适配器。

    该适配器同时负责 dense 向量和 sparse 词项权重生成，是离线入库的
    关键模型层。
    """

    def __init__(self, config: BGEModelConfig) -> None:
        self.config = config
        self._model: Any | None = None

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        """调用本地 BGE-M3 生成 dense 向量。"""

        model = self._load_model()
        outputs = model.encode(
            texts,
            batch_size=self.config.batch_size,
            max_length=self.config.max_length,
            return_dense=True,
            return_sparse=False,
            return_colbert_vecs=False,
        )
        dense_vectors = outputs["dense_vecs"] if isinstance(outputs, dict) else outputs
        return [self._to_float_list(vector) for vector in dense_vectors]

    def encode_documents(self, texts: list[str]) -> list[dict[int, float]]:
        """调用本地 BGE-M3 生成 sparse 向量。

        BGE-M3 返回的是 token 级 lexical weights。Milvus sparse vector 更适合
        使用稳定的整数 key，因此这里把 token 统一哈希成整数键。
        """

        model = self._load_model()
        outputs = model.encode(
            texts,
            batch_size=self.config.batch_size,
            max_length=self.config.max_length,
            return_dense=False,
            return_sparse=True,
            return_colbert_vecs=False,
        )
        lexical_weights = outputs["lexical_weights"] if isinstance(outputs, dict) else outputs
        return [self._normalize_sparse_vector(weights) for weights in lexical_weights]

    def _load_model(self) -> Any:
        """按需导入 FlagEmbedding。

        这样可以避免普通导入阶段就强依赖推理库，也方便做无模型环境下的单元测试。
        """

        if self._model is None:
            try:
                from FlagEmbedding import BGEM3FlagModel
            except ModuleNotFoundError as exc:  # pragma: no cover - dependency guard
                raise ModuleNotFoundError(
                    "运行 BGE-M3 推理需要安装 FlagEmbedding。请先安装项目推理依赖。"
                ) from exc

            # 不同版本的 FlagEmbedding 在 device 参数上存在细微差异。
            # 这里做兼容处理，保证本地 CPU 推理不因为参数差异而失败。
            try:
                self._model = BGEM3FlagModel(
                    self.config.model_path,
                    use_fp16=self.config.use_fp16,
                    device=self.config.device,
                )
            except TypeError:
                self._model = BGEM3FlagModel(
                    self.config.model_path,
                    use_fp16=self.config.use_fp16,
                )
        return self._model

    @staticmethod
    def _to_float_list(vector: Any) -> list[float]:
        """把模型返回的向量转换成标准 Python float 列表。"""

        if hasattr(vector, "tolist"):
            return [float(item) for item in vector.tolist()]
        return [float(item) for item in vector]

    @classmethod
    def _normalize_sparse_vector(cls, weights: Any) -> dict[int, float]:
        """把 token 键的 sparse 权重转换成稳定整数键。"""

        normalized: dict[int, float] = {}
        for key, value in dict(weights).items():
            normalized[cls._stable_token_id(key)] = float(value)
        return normalized

    @staticmethod
    def _stable_token_id(token: Any) -> int:
        """把 token 哈希成稳定的 63 位正整数 key。"""

        digest = hashlib.blake2b(str(token).encode("utf-8"), digest_size=8).digest()
        return int.from_bytes(digest, "big") & 0x7FFFFFFFFFFFFFFF
