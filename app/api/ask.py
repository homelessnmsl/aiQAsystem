"""API-06 RAG 问答 POST /api/ask（接口文档 2.6 / 2.11；W2-07 / W3-07）

API 层只做参数校验与响应封装；主链路在 services/rag.py（分层规范 4.3）。
流式（stream=true）：准备阶段失败按统一 JSON 错误返回；生成阶段下发 SSE 事件
retrieval → delta* → done / error（接口文档 2.11，事件本身不走统一响应包裹）。
"""
import json
from typing import Iterator

from fastapi import APIRouter
from fastapi.responses import StreamingResponse

from ..core.errors import CODE_INVALID_QUESTION, BizError
from ..core.logging import new_trace_id, set_trace_id
from ..core.response import ApiResponse
from ..models.ask import AskRequest, AskResponse, Citation, Latency, RetrievedItem
from ..models.chat import Usage
from ..services.conversation import conversation_store
from ..services.rag import StreamPrep, answer_question, prepare_stream, stream_events

router = APIRouter(prefix="/api", tags=["ask"])


@router.post("/ask")
async def ask(request: AskRequest):
    """基于知识库回答问题，返回答案 + 引用 + 检索明细（UC-03/UC-10 核心接口）"""
    trace_id = set_trace_id(new_trace_id())

    question = request.question.strip()
    if not question:
        raise BizError(CODE_INVALID_QUESTION, "问题不能为空")

    session_id = conversation_store.ensure(request.session_id)

    if request.stream:
        # 流式问答（接口文档 2.11）：准备完成后进入 SSE；准备阶段异常按统一 JSON 返回
        prep = prepare_stream(
            question=question,
            session_id=session_id,
            trace_id=trace_id,
            top_k=request.top_k,
            score_threshold=request.score_threshold,
            use_rerank=request.use_rerank,
        )
        return StreamingResponse(
            _sse_events(prep),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    result = answer_question(
        question=question,
        session_id=session_id,
        trace_id=trace_id,
        top_k=request.top_k,
        score_threshold=request.score_threshold,
        use_rerank=request.use_rerank,
    )

    data = AskResponse(
        trace_id=result.trace_id,
        session_id=result.session_id,
        message_id=result.message_id,
        question=result.question,
        rewritten_question=result.rewritten_question,
        answer=result.answer,
        answer_type=result.answer_type,
        citations=[Citation(**item) for item in result.citations],
        retrieved=[RetrievedItem(**item) for item in result.retrieved],
        model=result.model,
        usage=Usage(**result.usage) if result.usage else None,
        latency_ms=Latency(**result.latency_ms),
        created_at=result.created_at,
    )
    return ApiResponse.ok(data.model_dump())


def _sse_events(prep: StreamPrep) -> Iterator[str]:
    """事件字典 → SSE 文本（text/event-stream；同步生成器由 Starlette 在线程池迭代）"""
    for event in stream_events(prep):
        yield f"data: {json.dumps(event, ensure_ascii=False)}\n\n"
