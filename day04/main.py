"""第4天课程代码：流式输出（SSE）+ Streamlit 前端

课程内容：
- SSE 流式接口 /api/chat/stream：data: {"content": "...", "done": false} 逐块返回，最后 [DONE]
- 前端 Streamlit（frontend/streamlit_app.py）：类 ChatGPT 界面，逐字显示回复
- Agent 的 stream_run：先判断工具 → 执行工具 → 流式生成回复

启动后端（仓库根目录）：
    uvicorn day04.main:app --reload --port 8004
启动前端（另开一个终端，仓库根目录）：
    streamlit run day04/frontend/streamlit_app.py
"""
import json
import os
from pathlib import Path

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel, Field

from .core.agent_executor import AgentExecutor
from .core.conversation import ConversationManager
from .prompts.system_prompts import SYSTEM_PROMPT, WELCOME_MESSAGE
from .services.llm import BaseLLM, DeepSeekAdapter
from .tools.tools import TOOLS_MAP, TOOLS_SCHEMA

BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR / ".env")

app = FastAPI(title="智能客服对话机器人", description="第4天：流式输出（SSE）+ Streamlit", version="4.0.0")

DEEPSEEK_API_KEY = os.getenv("DEEPSEEK_API_KEY")
DEEPSEEK_MODEL = os.getenv("LLM_MODEL") or os.getenv("DEEPSEEK_MODEL", "deepseek-chat")
BASE_URL = os.getenv("DEEPSEEK_BASE_URL") or os.getenv("BASE_URL", "https://api.deepseek.com/v1")
MAX_HISTORY = int(os.getenv("MAX_HISTORY", "3"))

if not DEEPSEEK_API_KEY:
    print("[警告] 未检测到 DEEPSEEK_API_KEY，/api/chat 暂不可用（请配置 .env）")
    llm: BaseLLM | None = None
else:
    llm = DeepSeekAdapter(api_key=DEEPSEEK_API_KEY, model=DEEPSEEK_MODEL, base_url=BASE_URL)
    print(f"[OK] DeepSeek API 配置成功（模型：{DEEPSEEK_MODEL}）")

conversation = ConversationManager(max_history=MAX_HISTORY)
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
    temperature: float = Field(0.7, ge=0, le=2, description="温度参数，0~2")


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


@app.get("/")
def root():
    return success_response({"message": "智能客服系统运行中（第4天：流式输出版）"})


@app.get("/api/health")
def health():
    return success_response({"status": "ok", "llm_ready": llm is not None, "tools": list(TOOLS_MAP.keys())})


@app.get("/api/welcome")
def welcome():
    return success_response({"message": WELCOME_MESSAGE})


@app.post("/api/chat")
def chat(request: ChatRequest):
    """同步对话（第3天）：一次性返回完整回复"""
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


@app.post("/api/chat/stream")
def chat_stream(request: ChatRequest):
    """
    流式对话（SSE）：逐块返回，前端可"逐字"显示

    data: {"content": "片段", "done": false}
    data: {"content": "[DONE]", "done": true}
    """
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
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@app.post("/api/chat/reset")
def reset_chat(session_id: str = "default"):
    conversation.clear_session(session_id)
    return success_response({"session_id": session_id}, message="会话历史记录已重置")
