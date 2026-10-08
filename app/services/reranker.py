"""Rerank 重排序适配器（架构设计 6.8 / ADR-05；W3 AD 任务）

- 默认本地 ``BAAI/bge-reranker-base``（CrossEncoder，CPU 可跑、断网可用）；
- ``rerank(question, hits)``：对向量召回候选精排，返回**新列表**（新增 ``rerank_score``）并按分数降序；
- 可用性优先：模型未就绪/推理失败时**不抛异常**，告警后原样返回，保证 /api/ask 主链路可用；
- 由 ``app/services/retrieval.py::_try_rerank`` 懒加载调用（模块缺失时自动跳过）。
"""
from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional, Sequence

from ..core.config import settings

logger = logging.getLogger(__name__)

#: 进程内单例；加载失败后不再重试（避免每次请求都走异常路径）
_MODEL: Any = None
_LOAD_FAILED = False


def _load_model() -> Any:
    """懒加载 CrossEncoder（首次约 1~3s）；失败返回 None 并记录一次告警"""
    global _MODEL, _LOAD_FAILED
    if _MODEL is not None or _LOAD_FAILED:
        return _MODEL
    try:
        from sentence_transformers import CrossEncoder

        logger.info("加载 Rerank 模型：%s（device=%s）", settings.RERANK_MODEL, settings.EMBEDDING_DEVICE)
        _MODEL = CrossEncoder(settings.RERANK_MODEL, device=settings.EMBEDDING_DEVICE)
    except Exception as exc:
        _LOAD_FAILED = True
        logger.warning("Rerank 模型加载失败，后续跳过重排：%s", exc)
        return None
    return _MODEL


def _flatten_score(value: Any) -> float:
    """CrossEncoder 输出可能是标量或 (1,) 数组，统一转 float"""
    try:
        return float(value)
    except (TypeError, ValueError):
        try:
            return float(value[0])
        except Exception:
            return 0.0


def rerank(
    question: str,
    hits: Sequence[Dict[str, Any]],
    top_k: Optional[int] = None,
    model: Any = None,
) -> List[Dict[str, Any]]:
    """对候选切片重排序（不修改入参；失败时保留向量排序）

    :param model: 仅供离线测试注入（需提供 ``predict([[query, passage], ...]) -> list[float]``）
    """
    items = list(hits)
    scorer = model or _load_model()
    if scorer is None or not items:
        return items

    pairs = [[question, str(item.get("content", ""))] for item in items]
    try:
        scores = scorer.predict(pairs)
    except Exception as exc:
        logger.warning("Rerank 推理失败，保留向量排序：%s", exc)
        return items

    ranked: List[Dict[str, Any]] = []
    for item, score in zip(items, scores):
        enriched = dict(item)
        enriched["rerank_score"] = round(_flatten_score(score), 4)
        ranked.append(enriched)
    ranked.sort(key=lambda entry: entry["rerank_score"], reverse=True)
    return ranked[: int(top_k)] if top_k else ranked
