"""API-06 RAG 问答 POST /api/ask（接口文档 2.6；W2-07）

API 层只做参数校验与响应封装；主链路在 services/rag.py（分层规范 4.3）。
"""
from fastapi import APIRouter

from ..core.errors import CODE_INVALID_QUESTION, CODE_VALIDATION_FAILED, BizError
from ..core.logging import new_trace_id, set_trace_id
from ..core.response import ApiResponse
from ..models.ask import AskRequest, AskResponse, Citation, Latency, RetrievedItem
from ..models.chat import Usage
from ..services.conversation import conversation_store
from ..services.rag import answer_question

router = APIRouter(prefix="/api", tags=["ask"])


@router.post("/ask")
async def ask(request: AskRequest) -> dict:
    """基于知识库回答问题，返回答案 + 引用 + 检索明细（UC-03/UC-10 核心接口）"""
    trace_id = set_trace_id(new_trace_id())

    if request.stream:
        # SSE 流式问答计划第3周交付（接口文档 2.11：第2周先实现非流式）
        raise BizError(CODE_VALIDATION_FAILED, "stream=true（SSE）计划第3周交付，请先使用非流式模式")

    question = request.question.strip()
    if not question:
        raise BizError(CODE_INVALID_QUESTION, "问题不能为空")

    session_id = conversation_store.ensure(request.session_id)

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
