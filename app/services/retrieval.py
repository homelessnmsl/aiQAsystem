"""检索服务（架构设计 6.8；接口文档 2.6；W2-04）

供 DEV 的 ``/api/ask`` 直接调用：

    from app.services.retrieval import retrieve, build_context, build_citations

    chunks = retrieve(question)                 # 召回 → 阈值过滤 →（重排）→ Top-K
    if not chunks:                              # 走 not_found 兜底（不调用 LLM）
        ...
    context = build_context(chunks)             # "[1] 来源：..." 编号上下文，注入 Prompt
    citations = build_citations(chunks)         # 接口文档 2.6 citations 结构（程序生成，ADR-06）
"""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Sequence

from ..core.config import settings
from ..core.errors import CODE_INVALID_QUESTION, BizError
from ..knowledge.metadata import format_location
from ..knowledge.store import VectorStore, vector_store
from .embedding import EmbeddingProvider, get_embedding_provider

logger = logging.getLogger(__name__)


@dataclass
class RetrievedChunk:
    """一条召回结果（含引用展示所需字段）"""

    rank: int
    chunk_id: str
    doc_id: str
    source_file: str
    location: str
    content: str
    score: float
    rerank_score: Optional[float] = None
    metadata: Dict[str, Any] = field(default_factory=dict)


def retrieve(
    question: str,
    *,
    top_k: Optional[int] = None,
    score_threshold: Optional[float] = None,
    doc_ids: Optional[Sequence[str]] = None,
    use_rerank: Optional[bool] = None,
    provider: Optional[EmbeddingProvider] = None,
    store: Optional[VectorStore] = None,
    retrieve_k: Optional[int] = None,
) -> List[RetrievedChunk]:
    """两阶段检索（第2周先跑通第一阶段，第3周启用 Rerank）

    参数说明（与接口文档 2.6 /api/ask 请求字段一一对应）：
    - top_k：最终返回条数，默认 TOP_K=5；
    - score_threshold：相似度阈值，默认 SCORE_THRESHOLD=0.35（ADR-08）；
    - doc_ids：限定文档范围（预留）；
    - use_rerank：是否启用重排，默认取 RERANK_ENABLED（第3周到货前自动跳过并告警）。
    """
    text = (question or "").strip()
    if not text:
        raise BizError(CODE_INVALID_QUESTION, "问题不能为空")

    provider = provider or get_embedding_provider()
    store = store or vector_store
    started = time.perf_counter()

    where = {"doc_id": {"$in": list(doc_ids)}} if doc_ids else None
    hits = store.query(
        provider.embed_query(text),
        n_results=int(retrieve_k or settings.RETRIEVE_K),
        where=where,
    )

    threshold = settings.SCORE_THRESHOLD if score_threshold is None else float(score_threshold)
    hits = [hit for hit in hits if float(hit.get("score", 0.0)) >= threshold]

    wants_rerank = settings.RERANK_ENABLED if use_rerank is None else bool(use_rerank)
    if wants_rerank and hits:
        hits = _try_rerank(text, hits)

    limit = max(1, int(top_k or settings.TOP_K))
    results = [_to_retrieved(index + 1, hit) for index, hit in enumerate(hits[:limit])]

    logger.info(
        "检索完成：q=%r 命中 %d/%d 条，耗时 %dms（threshold=%.2f, rerank=%s）",
        text[:30],
        len(results),
        len(hits),
        int((time.perf_counter() - started) * 1000),
        threshold,
        wants_rerank,
    )
    return results


def knowledge_is_empty(store: Optional[VectorStore] = None) -> bool:
    """知识库是否为空：/api/ask 返回 2001 兜底用（FR-QA-04、接口文档 2.6）"""
    return (store or vector_store).is_empty()


def build_context(chunks: Sequence[RetrievedChunk], max_chars: Optional[int] = None) -> str:
    """编号上下文（架构 6.8 格式），按 MAX_CONTEXT_TOKENS 粗略预算（1 token ≈ 1.5 汉字）"""
    budget = max_chars or int(settings.MAX_CONTEXT_TOKENS * 1.5)
    lines: List[str] = []
    used = 0
    for chunk in chunks:
        block = f"[{chunk.rank}] 来源：{chunk.source_file}（{chunk.location}）\n{chunk.content}"
        if lines and used + len(block) > budget:
            break
        lines.append(block)
        used += len(block)
    return "\n".join(lines)


def build_citations(chunks: Sequence[RetrievedChunk]) -> List[Dict[str, Any]]:
    """接口文档 2.6 的 citations 结构（由程序依据元数据生成，防止模型伪造来源，ADR-06）"""
    return [
        {
            "index": chunk.rank,
            "doc_id": chunk.doc_id,
            "source_file": chunk.source_file,
            "location": chunk.location,
            "snippet": chunk.content[:200],
            "score": chunk.score,
            "rerank_score": chunk.rerank_score,
            "chunk_id": chunk.chunk_id,
        }
        for chunk in chunks
    ]


# --------------------------------------------------------------------------- #
# 内部工具
# --------------------------------------------------------------------------- #
def _try_rerank(question: str, hits: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """第3周 Rerank 钩子：模块未就绪时告警并跳过，不影响主链路"""
    try:
        from .reranker import rerank  # type: ignore  # 第3周（W3）AD 交付
    except ImportError:
        logger.warning("RERANK_ENABLED=true 但 app/services/reranker.py 尚未交付（第3周），本次跳过重排")
        return hits
    return rerank(question, hits)


def _to_retrieved(rank: int, hit: Dict[str, Any]) -> RetrievedChunk:
    """向量库命中 → RetrievedChunk（位置文本走架构 6.5 规则）"""
    metadata = hit.get("metadata") or {}
    return RetrievedChunk(
        rank=rank,
        chunk_id=str(hit.get("chunk_id", "")),
        doc_id=str(metadata.get("doc_id", "")),
        source_file=str(metadata.get("filename", "未知文件")),
        location=format_location(metadata),
        content=str(hit.get("content", "")),
        score=float(hit.get("score", 0.0)),
        rerank_score=hit.get("rerank_score"),
        metadata=dict(metadata),
    )
