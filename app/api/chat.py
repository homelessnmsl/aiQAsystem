"""API-02 基础对话 POST /api/chat（接口文档 2.2；W1-14）

- 直连 DeepSeek 的多轮对话，不检索知识库；
- session_id 传入则带最近 10 轮历史（内存版，第2周转 SQLite），不传自动新建；
- stream=true 时走 SSE（事件格式对齐接口文档 2.11：delta* → done / error）。
"""
import json
import logging
import time
from typing import Any, AsyncIterator, Dict, List

from fastapi import APIRouter
from fastapi.responses import StreamingResponse

from ..core.config import BASE_DIR, settings
from ..core.errors import CODE_LLM_NO_KEY, BizError
from ..core.logging import new_trace_id, now_iso, set_trace_id
from ..core.response import ApiResponse
from ..models.chat import ChatRequest, ChatResponse, Usage
from ..services.conversation import conversation_store
from ..services.llm import get_llm_client

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api", tags=["chat"])

#: PE 交付的系统提示词（W1-15，prompts/system_chat.md)；缺失时使用内置兜底
SYSTEM_PROMPT_FILE = BASE_DIR / "prompts" / "system_chat.md"
FALLBACK_SYSTEM_PROMPT = (
    "你是企业知识库智能问答系统的客服助手「小答」，用简体中文礼貌简洁地回答，"
    "不编造具体制度条款与数字；与公司业务无关的问题礼貌拒答。"
)


def load_system_prompt() -> str:
    """读取 PE 的系统提示词文件；读不到时返回内置兜底（保证可离线运行）"""
    try:
        text = SYSTEM_PROMPT_FILE.read_text(encoding="utf-8").strip()
        if text:
            return text
    except OSError:
        pass
    return FALLBACK_SYSTEM_PROMPT


def _build_messages(request: ChatRequest, session_id: str) -> List[Dict[str, str]]:
    """组装 messages：system + 历史 + 本轮输入（接口文档 2.2）"""
    system_prompt = request.system_prompt or load_system_prompt()
    return [
        {"role": "system", "content": system_prompt},
        *conversation_store.history(session_id),
        {"role": "user", "content": request.message},
    ]


@router.post("/chat")
async def chat(request: ChatRequest):
    """基础对话：默认同步返回；stream=true 时以 SSE 流式返回"""
    trace_id = set_trace_id(new_trace_id())
    started = time.perf_counter()

    if not settings.llm_configured:
        raise BizError(CODE_LLM_NO_KEY, "服务未配置模型密钥，请联系管理员")

    session_id = conversation_store.ensure(request.session_id)
    messages = _build_messages(request, session_id)

    if request.stream:
        return StreamingResponse(
            _sse_stream(messages, session_id, request, started),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    result = get_llm_client().chat(
        messages,
        temperature=request.temperature,
        max_tokens=request.max_tokens,
    )
    conversation_store.append(session_id, "user", request.message)
    conversation_store.append(session_id, "assistant", result.content)

    latency_ms = int((time.perf_counter() - started) * 1000)
    logger.info("chat 完成：trace=%s session=%s latency=%sms", trace_id, session_id, latency_ms)
    return ApiResponse.ok(
        ChatResponse(
            trace_id=trace_id,
            session_id=session_id,
            reply=result.content,
            model=result.model,
            usage=Usage(**vars(result.usage)),
            latency_ms=latency_ms,
            created_at=now_iso(),
        ).model_dump()
    )


async def _sse_stream(
    messages: List[Dict[str, str]],
    session_id: str,
    request: ChatRequest,
    started: float,
) -> AsyncIterator[str]:
    """SSE 事件流：delta* → done；异常时 error 收尾（接口文档 2.11 事件格式）"""
    full_reply = ""
    try:
        for chunk in get_llm_client().stream_chat(
            messages,
            temperature=request.temperature,
            max_tokens=request.max_tokens,
        ):
            full_reply += chunk
            yield f"data: {json.dumps({'type': 'delta', 'content': chunk}, ensure_ascii=False)}\n\n"
    except BizError as exc:
        yield f"data: {json.dumps({'type': 'error', 'code': exc.code, 'message': exc.message}, ensure_ascii=False)}\n\n"
        return

    conversation_store.append(session_id, "user", request.message)
    conversation_store.append(session_id, "assistant", full_reply)
    latency_ms = int((time.perf_counter() - started) * 1000)
    done: Dict[str, Any] = {"type": "done", "latency_ms": latency_ms, "usage": None}
    yield f"data: {json.dumps(done, ensure_ascii=False)}\n\n"
