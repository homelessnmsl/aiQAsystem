"""API-01 健康检查 GET /api/health（接口文档 2.1；W2 补真实依赖状态）

四项依赖：llm / embedding / vector_store / sqlite；本接口不抛异常，
依赖异常时也返回 200 + status=degraded；台账与向量库数量不一致同样置 degraded（架构 6.6）。
"""
import logging
from pathlib import Path

from fastapi import APIRouter

from ..core.config import settings
from ..core.errors import BizError
from ..core.logging import now_iso
from ..core.response import ApiResponse
from ..knowledge.store import vector_store
from ..services.repository import get_repository

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api", tags=["health"])


def _llm_status() -> dict:
    """LLM 状态：按密钥配置判断（不发起真实调用，避免每次健康检查花钱）"""
    return {
        "status": "ok" if settings.llm_configured else "unconfigured",
        "model": settings.LLM_MODEL,
    }


def _embedding_status() -> dict:
    """Embedding 轻量状态（不加载模型：首次加载约 10s，会拖慢健康检查）"""
    info = {"model": settings.EMBEDDING_MODEL, "dim": settings.EMBEDDING_DIM}
    if settings.EMBEDDING_PROVIDER == "local":
        model = settings.EMBEDDING_MODEL
        looks_like_path = model.startswith(".") or Path(model).is_absolute()
        if looks_like_path and not Path(model).exists():
            return {"status": "error", "message": "本地向量模型路径不存在", **info}
        return {"status": "ok", **info}
    key = settings.SILICONFLOW_API_KEY if settings.EMBEDDING_PROVIDER == "siliconflow" else settings.DASHSCOPE_API_KEY
    return {"status": "ok" if key else "unconfigured", **info}


def _vector_store_status() -> dict:
    """向量库状态：集合名 + 切片总数（SM-01）"""
    try:
        return {
            "status": "ok",
            "collection": vector_store.collection_name,
            "chunk_count": vector_store.count(),
        }
    except BizError as exc:
        return {"status": "error", "message": exc.message}
    except Exception as exc:  # noqa: BLE001 - 健康检查不抛异常
        logger.warning("向量库状态检查失败：%s", exc)
        return {"status": "error", "message": "向量库不可用"}


def _sqlite_status() -> dict:
    """台账状态：documents 行数（响应不返回服务器绝对路径，NFR-S-02）"""
    try:
        return {
            "status": "ok",
            "path": settings.SQLITE_PATH,
            "documents": get_repository().count_documents(),
        }
    except Exception as exc:  # noqa: BLE001 - 健康检查不抛异常
        logger.warning("SQLite 状态检查失败：%s", exc)
        return {"status": "error", "message": "台账不可用"}


@router.get("/health")
async def health() -> dict:
    """服务与依赖状态（演示前自检 / 运维排障，NFR-O-02）"""
    dependencies = {
        "llm": _llm_status(),
        "embedding": _embedding_status(),
        "vector_store": _vector_store_status(),
        "sqlite": _sqlite_status(),
    }
    degraded = any(dep.get("status") == "error" for dep in dependencies.values())

    # 一致性对账：SQLite 台账（账本） vs Chroma（索引），架构 6.6
    if dependencies["vector_store"].get("status") == "ok" and dependencies["sqlite"].get("status") == "ok":
        ledger_chunks = get_repository().sum_chunks()
        vector_chunks = dependencies["vector_store"].get("chunk_count", 0)
        if ledger_chunks != vector_chunks:
            degraded = True
            dependencies["sqlite"]["ledger_chunk_count"] = ledger_chunks
            logger.warning(
                "台账与向量库不一致：台账 %d 条切片 / 向量库 %d 条；"
                "如经脚本重建过向量库，请通过 /api/upload 重新入库或同步台账",
                ledger_chunks,
                vector_chunks,
            )

    return ApiResponse.ok({
        "status": "degraded" if degraded else "ok",
        "version": settings.APP_VERSION,
        "time": now_iso(),
        "dependencies": dependencies,
    })
