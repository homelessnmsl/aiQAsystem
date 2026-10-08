"""Chroma 向量库封装（架构设计 6.6；W2-03）

- ``PersistentClient`` 本地持久化，服务重启不丢数据（FR-KB-02 / NFR-R-03）；
- 集合 ``enterprise_kb``（.env 可改），cosine 距离，ID = ``{doc_id}:{chunk_index}``；
- 只负责「向量 + 切片元数据」的读写；文档台账/会话等在 SQLite（DEV 的 repository 负责）。
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

import chromadb

from ..core.config import settings
from ..core.errors import CODE_VECTOR_STORE_ERROR, BizError
from .splitter import Chunk

logger = logging.getLogger(__name__)

#: 写入分批大小（架构 6.6：每批 ≤100 条）
BATCH_SIZE = 100


class VectorStore:
    """Chroma 封装：add_chunks / query / delete_by_doc / get_by_doc / count / reset"""

    def __init__(self, path: str | Path | None = None, collection: str | None = None) -> None:
        self.path = Path(path) if path is not None else settings.chroma_dir
        self.collection_name = collection or settings.CHROMA_COLLECTION
        self._client = None
        self._collection = None

    # ------------------------------------------------------------------ #
    # 内部
    # ------------------------------------------------------------------ #
    @property
    def collection(self):
        """懒初始化 Chroma 集合（首次访问时创建目录与集合）"""
        if self._collection is None:
            try:
                self.path.mkdir(parents=True, exist_ok=True)
                self._client = chromadb.PersistentClient(path=str(self.path))
                self._collection = self._client.get_or_create_collection(
                    name=self.collection_name,
                    metadata={"hnsw:space": "cosine"},
                )
            except Exception as exc:  # 磁盘/权限/索引损坏
                logger.exception("向量库初始化失败：%s", exc)
                raise BizError(CODE_VECTOR_STORE_ERROR, "知识库暂时不可用，请稍后重试") from exc
        return self._collection

    @staticmethod
    def _wrap(exc: Exception, message: str) -> BizError:
        """把底层异常翻译成接口文档 1.4 的业务错误（2003）"""
        if "dimension" in str(exc).lower():
            return BizError(
                CODE_VECTOR_STORE_ERROR,
                "向量维度不一致：请执行 python scripts/build_kb.py --rebuild 重建知识库",
            )
        logger.exception("向量库操作失败：%s", exc)
        return BizError(CODE_VECTOR_STORE_ERROR, message)

    # ------------------------------------------------------------------ #
    # 写入 / 删除
    # ------------------------------------------------------------------ #
    def add_chunks(
        self,
        chunks: Sequence[Chunk],
        embeddings: Sequence[Sequence[float]],
        batch_size: int = BATCH_SIZE,
    ) -> int:
        """批量写入切片（幂等：同 ID 覆盖），返回写入条数"""
        if len(chunks) != len(embeddings):
            raise ValueError("chunks 与 embeddings 数量不一致")
        written = 0
        for start in range(0, len(chunks), batch_size):
            batch = chunks[start : start + batch_size]
            vectors = embeddings[start : start + batch_size]
            try:
                self.collection.add(
                    ids=[c.chunk_id for c in batch],
                    embeddings=[list(v) for v in vectors],
                    metadatas=[c.metadata for c in batch],
                    documents=[c.content for c in batch],
                )
            except Exception as exc:
                raise self._wrap(exc, "写入知识库失败，请稍后重试") from exc
            written += len(batch)
        return written

    def delete_by_doc(self, doc_id: str) -> int:
        """删除某文档的全部向量，返回删除条数（FR-KB-05）"""
        try:
            before = self.count()
            self.collection.delete(where={"doc_id": doc_id})
            after = self.count()
            return max(0, before - after)
        except BizError:
            raise
        except Exception as exc:
            raise self._wrap(exc, "删除文档失败，请稍后重试") from exc

    # ------------------------------------------------------------------ #
    # 查询 / 统计
    # ------------------------------------------------------------------ #
    def query(
        self,
        query_embedding: Sequence[float],
        n_results: int = 5,
        where: Optional[Dict[str, Any]] = None,
    ) -> List[Dict[str, Any]]:
        """向量检索：返回 [{chunk_id, content, metadata, score}]，score = 1 - 余弦距离"""
        try:
            result = self.collection.query(
                query_embeddings=[list(query_embedding)],
                n_results=max(1, int(n_results)),
                where=where,
                include=["metadatas", "documents", "distances"],
            )
        except Exception as exc:
            raise self._wrap(exc, "检索知识库失败，请稍后重试") from exc

        ids = (result.get("ids") or [[]])[0]
        documents = (result.get("documents") or [[]])[0]
        metadatas = (result.get("metadatas") or [[]])[0]
        distances = (result.get("distances") or [[]])[0]

        hits: List[Dict[str, Any]] = []
        for chunk_id, content, metadata, distance in zip(ids, documents, metadatas, distances):
            hits.append(
                {
                    "chunk_id": chunk_id,
                    "content": content or "",
                    "metadata": dict(metadata or {}),
                    "score": round(1.0 - float(distance), 4),
                }
            )
        return hits

    def get_by_doc(self, doc_id: str, limit: int = 1000) -> List[Dict[str, Any]]:
        """读取某文档的切片（列表/调试用）"""
        try:
            data = self.collection.get(where={"doc_id": doc_id}, limit=limit, include=["metadatas", "documents"])
        except Exception as exc:
            raise self._wrap(exc, "读取知识库失败，请稍后重试") from exc
        return [
            {"chunk_id": cid, "content": doc, "metadata": dict(meta or {})}
            for cid, doc, meta in zip(data.get("ids", []), data.get("documents", []), data.get("metadatas", []))
        ]

    def count(self) -> int:
        """切片总数（健康检查与台账对账）"""
        try:
            return int(self.collection.count())
        except BizError:
            raise
        except Exception as exc:
            raise self._wrap(exc, "读取知识库统计失败，请稍后重试") from exc

    def is_empty(self) -> bool:
        """知识库是否为空（/api/ask 空库兜底判断用，FR-QA-04）"""
        return self.count() == 0

    def reset(self) -> None:
        """清空集合（scripts/build_kb.py --rebuild 用，架构 6.6 重建策略）"""
        try:
            _ = self.collection  # 确保 client/collection 已初始化
            self._client.delete_collection(self.collection_name)
            self._collection = self._client.get_or_create_collection(
                name=self.collection_name,
                metadata={"hnsw:space": "cosine"},
            )
        except Exception as exc:
            raise self._wrap(exc, "重建知识库失败，请稍后重试") from exc


#: 全局默认实例（业务代码 from app.knowledge.store import vector_store）
vector_store = VectorStore()
