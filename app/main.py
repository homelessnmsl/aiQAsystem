"""FastAPI 应用入口：create_app()、路由注册、异常处理器挂载（架构 4.1；W1-13）

运行（仓库根目录）：python -m uvicorn app.main:app --reload --port 8000
接口文档：http://127.0.0.1:8000/docs
契约：docs/接口文档.md（字段以此为准，先改文档再改代码）。
"""
import uvicorn
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .api import ask, chat, documents, health, upload
from .core.config import settings
from .core.errors import register_exception_handlers
from .core.logging import setup_logging
from .core.response import ApiResponse


def create_app() -> FastAPI:
    """创建并组装 FastAPI 应用（配置 → 日志 → 中间件 → 异常处理器 → 路由）"""
    setup_logging(settings.LOG_LEVEL)

    app = FastAPI(
        title="企业知识库智能问答系统 API",
        description="aiQAsystem · 智231 小组 · 接口契约见 docs/接口文档.md",
        version=settings.APP_VERSION,
    )

    # 前端（Streamlit）跨域访问
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    register_exception_handlers(app)

    # 路由注册（第2周：/api/upload、/api/documents、/api/ask）
    app.include_router(health.router)
    app.include_router(chat.router)
    app.include_router(upload.router)
    app.include_router(documents.router)
    app.include_router(ask.router)

    @app.get("/", tags=["health"], summary="服务存活探针")
    async def root() -> dict:
        """返回服务基本信息；正式健康检查为 GET /api/health（接口文档 2.1）。"""
        return ApiResponse.ok({"service": "aiQAsystem", "version": settings.APP_VERSION})

    # 启动自检（不阻止启动：SM-04 约定未配 Key 时调用 /api/chat 返回 3003）
    for warning in settings.validate_warnings():
        print(f"[警告] {warning}")

    return app


app = create_app()


if __name__ == "__main__":
    uvicorn.run(app, host=settings.API_HOST, port=settings.API_PORT)
