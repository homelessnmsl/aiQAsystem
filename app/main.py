"""FastAPI 应用入口（W1-11 提交的占位骨架，DEV 在 W1-13 扩展）。

TODO（DEV 第1周，按顺序完成）：
1. 读取 app/core/config.py 的 settings（pydantic-settings 加载 .env）；
2. 注册统一响应与全局异常处理器（app/core/response.py、app/core/errors.py，错误码见 docs/接口文档.md 1.4）；
3. 注册路由：/api/chat（第1周）、/api/health；第2周补 /api/upload、/api/documents、/api/ask；
4. 启动时创建 data/ 目录并初始化 SQLite 表（架构设计 10.3）。

运行：python -m uvicorn app.main:app --reload --port 8000
契约：docs/接口文档.md（字段以此为准，先改文档再改代码）。
"""

from fastapi import FastAPI

app = FastAPI(
    title="企业知识库智能问答系统 API",
    description="aiQAsystem · 智231 小组 · 接口契约见 docs/接口文档.md",
    version="0.1.0",
)


@app.get("/", tags=["health"], summary="服务存活探针（占位）")
async def root() -> dict:
    """返回服务基本信息；正式健康检查为 GET /api/health（接口文档 2.1）。"""
    return {
        "code": 0,
        "message": "success",
        "data": {"service": "aiQAsystem", "version": "0.1.0"},
    }
