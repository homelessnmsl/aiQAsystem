"""第5天课程代码：配置集中管理 + 项目整合（第1周课程收官）

整合清单：
- 配置集中管理（config.py）：LLM / 服务器 / 对话配置统一从 .env 读取，不再散落 os.getenv
- 第2天：多轮对话（core/conversation.py）
- 第3天：Function Calling（tools/ + core/agent_executor.py）
- 第4天：流式输出 SSE（/api/chat/stream）+ Streamlit 前端
- 工程化：CORS、/health、/api/welcome、统一响应与异常处理

启动（仓库根目录）：
    uvicorn day05.main:app --reload --port 8005
    （或 python -m day05.main）
前端（另开终端，仓库根目录）：
    streamlit run day05/frontend/streamlit_app.py
"""
import json

import uvicorn
from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel, Field

from .config import config
from .core.agent_executor import AgentExecutor
from .core.conversation import ConversationManager
from .prompts.system_prompts import SYSTEM_PROMPT, WELCOME_MESSAGE
from .services.llm import BaseLLM, DeepSeekAdapter
from .tools.tools import TOOLS_MAP, TOOLS_SCHEMA

app = FastAPI(
    title="智能客服系统",
    description="第5天：配置集中管理 + 项目整合（多轮对话 / 工具调用 / 流式输出）",
    version="5.0.0",
)

# ---------- CORS（允许前端跨域访问） ----------
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ---------- 初始化大模型（第5天：配置从 config.py 统一读取） ----------
if config.validate():
    llm: BaseLLM | None = DeepSeekAdapter(
        api_key=config.DEEPSEEK_API_KEY,
        model=config.DEEPSEEK_MODEL,
        base_url=config.BASE_URL,
    )
    print(f"[OK] DeepSeek API 配置成功（模型：{config.DEEPSEEK_MODEL}）")
else:
    llm = None

# ---------- 对话管理器 + Agent ----------
conversation = ConversationManager(max_history=config.MAX_HISTORY)
agent = AgentExecutor(
    llm=llm,
    conversation_manager=conversation,
    tools_schema=TOOLS_SCHEMA,
    tools_map=TOOLS_MAP,
    system_prompt=SYSTEM_PROMPT,
)


class ChatRequest(BaseModel):
    message: str = Field(..., min_length=1, max_length=1000, description="用户消息")
    session_id: str = Field("default", max_length=64, description="会话ID")
    temperature: float = Field(config.DEFAULT_TEMPERATURE, ge=0, le=2, description="温度参数，0~2")


def success_response(data=None, message="success"):
    return {"code": 0, "message": message, "data": data}


def error_response(code: int, message: str, data=None):
    return {"code": code, "message": message, "data": data}


@app.exception_handler(RequestValidationError)
def validation_handler(request: Request, exc: RequestValidationError):
    errors = [{"field": ".".join(str(x) for x in e["loc"]), "msg": e["msg"]} for e in exc.errors()]
    return JSONResponse(status_code=400, content=error_response(400, "请求参数校验失败", errors))


@app.exception_handler(HTTPException)
def http_handler(request: Request, exc: HTTPException):
    return JSONResponse(status_code=exc.status_code, content=error_response(exc.status_code, str(exc.detail)))


# ---------- 基础路由 ----------
@app.get("/")
def root():
    return success_response({"service": "智能客服系统", "version": "5.0.0", "status": "running"})


@app.get("/health")
def health():
    return success_response({
        "status": "healthy",
        "llm_ready": llm is not None,
        "active_sessions": conversation.get_session_count(),
    })


@app.get("/api/welcome")
def welcome():
    return success_response({"message": WELCOME_MESSAGE})


# ---------- 核心接口1：同步对话 ----------
@app.post("/api/chat")
def chat(request: ChatRequest):
    """同步对话：多轮对话 + 工具调用，一次性返回"""
    if llm is None:
        raise HTTPException(status_code=500, detail="大模型未初始化，请检查 API Key 配置")
    try:
        return success_response(data=agent.run(
            session_id=request.session_id,
            user_message=request.message,
            temperature=request.temperature,
        ))
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"对话服务异常: {str(e)}")


# ---------- 核心接口2：流式对话（SSE） ----------
@app.post("/api/chat/stream")
def chat_stream(request: ChatRequest):
    """流式对话：data: {"content": "片段", "done": false}，最后 [DONE]"""
    if llm is None:
        raise HTTPException(status_code=500, detail="大模型未初始化，请检查 API Key 配置")

    def generate():
        try:
            for chunk in agent.stream_run(
                session_id=request.session_id,
                user_message=request.message,
                temperature=request.temperature,
            ):
                payload = json.dumps({"content": chunk, "done": False}, ensure_ascii=False)
                yield f"data: {payload}\n\n"
            done_payload = json.dumps({"content": "[DONE]", "done": True}, ensure_ascii=False)
            yield f"data: {done_payload}\n\n"
        except Exception as e:
            payload = json.dumps({"content": f"[错误] 流式对话异常: {str(e)}", "done": True}, ensure_ascii=False)
            yield f"data: {payload}\n\n"

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "Connection": "keep-alive", "X-Accel-Buffering": "no"},
    )


@app.post("/api/chat/reset")
def reset_chat(session_id: str = "default"):
    conversation.clear_session(session_id)
    return success_response({"session_id": session_id}, message="会话历史记录已重置")


if __name__ == "__main__":
    print(f"[启动] http://{config.HOST}:{config.PORT}")
    uvicorn.run(app, host=config.HOST, port=config.PORT)
