"""第3天课程代码：Function Calling 工具调用

课程内容：
- 工具定义 JSON Schema（tools/tools.py）：query_order / get_product_info / check_delivery / transfer_to_human
- Agent 执行器（core/agent_executor.py）：调用模型 → 判断工具 → 执行工具 → 再调用模型生成回复
- /api/chat 返回最终回复与工具调用记录（tool_calls，便于演示与排查）

启动（仓库根目录）：
    uvicorn day03.main:app --reload --port 8003
接口文档：
    http://127.0.0.1:8003/docs
"""
import os
from pathlib import Path

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from .core.agent_executor import AgentExecutor
from .core.conversation import ConversationManager
from .prompts.system_prompts import SYSTEM_PROMPT, WELCOME_MESSAGE
from .services.llm import BaseLLM, DeepSeekAdapter
from .tools.tools import TOOLS_MAP, TOOLS_SCHEMA

BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR / ".env")

app = FastAPI(title="智能客服对话机器人", description="第3天：Function Calling 工具调用", version="3.0.0")

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
    return success_response({"message": "智能客服系统运行中（第3天：Function Calling 版）"})


@app.get("/api/health")
def health():
    return success_response({"status": "ok", "llm_ready": llm is not None, "tools": list(TOOLS_MAP.keys())})


@app.get("/api/welcome")
def welcome():
    return success_response({"message": WELCOME_MESSAGE})


@app.post("/api/chat")
def chat(request: ChatRequest):
    """对话接口：支持多轮对话 + 自动调用工具"""
    if llm is None:
        raise HTTPException(status_code=500, detail="大模型未初始化，请检查 API Key 配置")

    try:
        result = agent.run(
            session_id=request.session_id,
            user_message=request.message,
            temperature=request.temperature,
        )
        return success_response(data=result)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"对话服务异常: {str(e)}")


@app.post("/api/chat/reset")
def reset_chat(session_id: str = "default"):
    conversation.clear_session(session_id)
    return success_response({"session_id": session_id}, message="会话历史记录已重置")
