"""API-01 健康检查 GET /api/health（接口文档 2.1；第1周先行实现）

约定：本接口不抛异常；依赖异常时也返回 200 + status=degraded。
第1周仅 LLM 已接入；Embedding / 向量库 / SQLite 第2周起接入（先返回 unconfigured）。
"""
from fastapi import APIRouter

from ..core.config import settings
from ..core.logging import now_iso
from ..core.response import ApiResponse

router = APIRouter(prefix="/api", tags=["health"])


@router.get("/health")
async def health():
    """服务与依赖状态（演示前自检 / 运维排障，NFR-O-02）"""
    dependencies = {
        "llm": {
            "status": "ok" if settings.llm_configured else "unconfigured",
            "model": settings.LLM_MODEL,
        },
        "embedding": {"status": "unconfigured", "note": "第2周接入"},
        "vector_store": {"status": "unconfigured", "note": "第2周接入"},
        "sqlite": {"status": "unconfigured", "note": "第2周接入"},
    }
    overall = "degraded" if any(d.get("status") == "error" for d in dependencies.values()) else "ok"
    return ApiResponse.ok({
        "status": overall,
        "version": settings.APP_VERSION,
        "time": now_iso(),
        "dependencies": dependencies,
    })
