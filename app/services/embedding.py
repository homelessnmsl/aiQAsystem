"""Embedding 适配器（架构设计 6.7；W2-03）

- 默认本地 ``BAAI/bge-small-zh-v1.5``：CPU 可跑、断网可演示（NFR-C-04）；
- 可切在线（OpenAI 兼容协议：硅基流动 / 阿里百炼等，改 .env 即可）；
- 归一化输出 + bge 查询前缀（查询侧加、文档侧不加）+ 查询向量 LRU 缓存；
- 模型维度不一致时由向量库侧给出「请重建知识库」的中文提示（架构 6.7-1）。
"""
from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from functools import lru_cache
from typing import Dict, List, Sequence

import httpx

from ..core.config import settings
from ..core.errors import CODE_VECTOR_STORE_ERROR, BizError

logger = logging.getLogger(__name__)

#: bge 系列官方推荐的查询前缀（架构 6.7-5）
BGE_QUERY_PREFIX = "为这个句子生成表示以用于检索相关文章："


class EmbeddingProvider(ABC):
    """Embedding 提供方接口：业务代码只依赖本抽象（架构 1.3-6 组件可替换）"""

    model_name: str
    dim: int

    @abstractmethod
    def embed_documents(self, texts: Sequence[str]) -> List[List[float]]:
        """批量编码文档（入库用）"""
        raise NotImplementedError

    @abstractmethod
    def embed_query(self, text: str) -> List[float]:
        """编码单条查询（检索用）"""
        raise NotImplementedError


class LocalEmbeddingProvider(EmbeddingProvider):
    """本地 sentence-transformers 模型（默认 bge-small-zh-v1.5，512 维）"""

    def __init__(self, model_name: str | None = None, device: str | None = None) -> None:
        self.model_name = model_name or settings.EMBEDDING_MODEL
        self.device = device or settings.EMBEDDING_DEVICE
        self._model = None

    # -- 模型懒加载（进程内单例；首次约 5~10s + 首次下载约 100MB） -- #
    def _load(self):
        if self._model is None:
            try:
                from sentence_transformers import SentenceTransformer

                logger.info("加载本地 Embedding 模型：%s（device=%s）", self.model_name, self.device)
                self._model = SentenceTransformer(self.model_name, device=self.device)
            except Exception as exc:
                logger.exception("本地 Embedding 模型加载失败：%s", exc)
                raise BizError(
                    CODE_VECTOR_STORE_ERROR,
                    "知识库构建失败：向量模型不可用。首次使用需联网下载模型；"
                    "下载失败时可设置环境变量 HF_ENDPOINT=https://hf-mirror.com 后重试",
                ) from exc
        return self._model

    @property
    def dim(self) -> int:
        """向量维度（架构 6.7-1 维度校验用）"""
        return int(self._model_dim())

    @lru_cache(maxsize=1)
    def _model_dim(self) -> int:
        return int(self._load().get_sentence_embedding_dimension())

    def embed_documents(self, texts: Sequence[str]) -> List[List[float]]:
        """批量编码并 L2 归一化（cosine 空间更稳定，架构 6.7-2）"""
        items = list(texts)
        if not items:
            return []
        vectors = self._load().encode(
            items,
            batch_size=settings.EMBEDDING_BATCH_SIZE,
            normalize_embeddings=True,
            show_progress_bar=False,
        )
        return [vector.tolist() for vector in vectors]

    def embed_query(self, text: str) -> List[float]:
        """查询编码（加 bge 前缀 + LRU 缓存，架构 6.7-4/5）"""
        return list(self._cached_query(text))

    @lru_cache(maxsize=512)
    def _cached_query(self, text: str) -> tuple:
        return tuple(self.embed_documents([BGE_QUERY_PREFIX + text])[0])


class RemoteEmbeddingProvider(EmbeddingProvider):
    """OpenAI 兼容协议的在线 Embedding（硅基流动 bge-m3 / 百炼 text-embedding-v3 等）"""

    def __init__(self, model_name: str, api_key: str, base_url: str, dim: int) -> None:
        self.model_name = model_name
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.dim = int(dim)

    def embed_documents(self, texts: Sequence[str]) -> List[List[float]]:
        items = list(texts)
        if not items:
            return []
        payload = {"model": self.model_name, "input": items, "encoding_format": "float"}
        headers = {"Authorization": f"Bearer {self.api_key}"}
        try:
            response = httpx.post(
                f"{self.base_url}/embeddings", json=payload, headers=headers, timeout=60
            )
            response.raise_for_status()
            data = response.json().get("data", [])
        except Exception as exc:
            logger.exception("在线 Embedding 调用失败：%s", exc)
            raise BizError(
                CODE_VECTOR_STORE_ERROR, "在线向量模型调用失败：请检查网络与密钥，或改用本地模型"
            ) from exc
        ordered = sorted(data, key=lambda item: item.get("index", 0))
        return [item["embedding"] for item in ordered]

    def embed_query(self, text: str) -> List[float]:
        return self.embed_documents([text])[0]


#: 进程内 provider 单例（避免重复加载模型，架构 9.2）
_PROVIDERS: Dict[str, EmbeddingProvider] = {}


def get_embedding_provider() -> EmbeddingProvider:
    """按 .env 的 EMBEDDING_PROVIDER 返回单例（local / siliconflow / dashscope）"""
    name = (settings.EMBEDDING_PROVIDER or "local").strip().lower()
    if name in _PROVIDERS:
        return _PROVIDERS[name]

    if name in {"local", "st", "sentence-transformers"}:
        provider: EmbeddingProvider = LocalEmbeddingProvider()
    elif name in {"siliconflow", "silicon"}:
        if not settings.SILICONFLOW_API_KEY.strip():
            raise BizError(CODE_VECTOR_STORE_ERROR, "未配置在线向量模型密钥（SILICONFLOW_API_KEY）")
        provider = RemoteEmbeddingProvider(
            model_name=settings.EMBEDDING_MODEL,
            api_key=settings.SILICONFLOW_API_KEY,
            base_url=settings.SILICONFLOW_BASE_URL,
            dim=settings.EMBEDDING_DIM,
        )
    elif name in {"dashscope", "bailian"}:
        if not settings.DASHSCOPE_API_KEY.strip():
            raise BizError(CODE_VECTOR_STORE_ERROR, "未配置在线向量模型密钥（DASHSCOPE_API_KEY）")
        provider = RemoteEmbeddingProvider(
            model_name=settings.EMBEDDING_MODEL,
            api_key=settings.DASHSCOPE_API_KEY,
            base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
            dim=settings.EMBEDDING_DIM,
        )
    else:
        raise BizError(CODE_VECTOR_STORE_ERROR, f"不支持的 Embedding 提供方：{name}")

    _PROVIDERS[name] = provider
    return provider
