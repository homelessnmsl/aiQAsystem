"""第2天课程代码：多轮对话 + System Prompt

课程内容：
- 对话历史管理 ConversationManager（core/conversation.py）：多 Session 隔离、按轮数截断
- System Prompt 设计（prompts/system_prompts.py）：角色、风格、服务范围、禁止行为
- /api/chat 支持多轮：同一 session_id 自动携带历史上下文（"我叫小明" → "我叫什么？"）
- /api/chat/reset：重置会话历史

启动（仓库根目录）：
    uvicorn day02.main:app --reload --port 8002
接口文档：
    http://127.0.0.1:8002/docs
"""
import os
from pathlib import Path

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from .core.conversation import ConversationManager
from .prompts.system_prompts import SYSTEM_PROMPT, WELCOME_MESSAGE
from .services.llm import BaseLLM, DeepSeekAdapter

# ---------- 加载环境变量（仓库根目录 .env；兼容团队变量名 LLM_MODEL / DEEPSEEK_BASE_URL） ----------
BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR / ".env")

app = FastAPI(
    title="智能客服对话机器人",
    description="第2天：多轮对话 + System Prompt",
    version="2.0.0",
)

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

# ---------- 对话历史管理器（多轮对话的关键） ----------
conversation = ConversationManager(max_history=MAX_HISTORY)


# ---------- 请求模型 ----------
class ChatRequest(BaseModel):
    message: str = Field(..., min_length=1, max_length=1000, description="用户消息")
    session_id: str = Field("default", max_length=64, description="会话ID（相同ID共享上下文）")
    temperature: float = Field(0.7, ge=0, le=2, description="温度参数，0~2")


# ---------- 统一响应格式 ----------
def success_response(data=None, message="success"):
    return {"code": 0, "message": message, "data": data}


def error_response(code: int, message: str, data=None):
    return {"code": code, "message": message, "data": data}


# ---------- 异常处理 ----------
@app.exception_handler(RequestValidationError)
def validation_handler(request: Request, exc: RequestValidationError):
    errors = [{"field": ".".join(str(x) for x in e["loc"]), "msg": e["msg"]} for e in exc.errors()]
    return JSONResponse(status_code=400, content=error_response(400, "请求参数校验失败", errors))


@app.exception_handler(HTTPException)
def http_handler(request: Request, exc: HTTPException):
    return JSONResponse(status_code=exc.status_code, content=error_response(exc.status_code, str(exc.detail)))


# ---------- 路由 ----------
@app.get("/")
def root():
    return success_response({"message": "智能客服系统运行中（第2天：多轮对话版）"})


@app.get("/api/health")
def health():
    return success_response({"status": "ok", "llm_ready": llm is not None})


@app.get("/api/welcome")
def welcome():
    return success_response({"message": WELCOME_MESSAGE})


@app.post("/api/chat")
def chat(request: ChatRequest):
    """多轮对话：自动携带该 session_id 的历史（最近 MAX_HISTORY 轮）"""
    if llm is None:
        raise HTTPException(status_code=500, detail="大模型未初始化，请检查 API Key 配置")

    # 1. 组装消息：system + 历史 + 本轮输入
    history = conversation.get_history(request.session_id)
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        *history,
        {"role": "user", "content": request.message},
    ]

    # 2. 调用大模型
    try:
        response = llm.chat(messages=messages, temperature=request.temperature)
        reply = response.choices[0].message.content
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"对话服务异常: {str(e)}")

    # 3. 保存本轮对话到历史（下一轮自动带上）
    conversation.add_message(request.session_id, "user", request.message)
    conversation.add_message(request.session_id, "assistant", reply)

    return success_response({
        "reply": reply,
        "session_id": request.session_id,
        "history_length": conversation.get_history_length(request.session_id),
    })


@app.post("/api/chat/reset")
def reset_chat(session_id: str = "default"):
    """重置指定会话的历史记录"""
    conversation.clear_session(session_id)
    return success_response({"session_id": session_id}, message="会话历史记录已重置")
