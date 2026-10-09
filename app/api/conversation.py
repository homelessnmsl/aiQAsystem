"""API-08~11 会话与反馈（接口文档 2.7~2.10；W3 DEV）

- GET    /api/conversations              会话列表（侧栏历史，FR-CONV-01）
- GET    /api/conversations/{session_id} 会话详情（含引用，供页面回显恢复）
- DELETE /api/conversations/{session_id} 清空会话消息（Q-01 决议：v1 仅支持清空当前会话）
- POST   /api/feedback                   点赞/点踩（UC-08、US-12）
"""
import json
import logging
from typing import Optional

from fastapi import APIRouter, Query

from ..core.errors import CODE_NOT_FOUND, BizError
from ..core.logging import now_iso
from ..core.response import ApiResponse
from ..models.ask import Citation
from ..models.conversation import (
    ConversationDetail,
    ConversationItem,
    ConversationPage,
    FeedbackData,
    FeedbackRequest,
    MessageItem,
)
from ..services.conversation import conversation_store, new_feedback_id
from ..services.repository import get_repository

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api", tags=["conversation"])


@router.get("/conversations")
async def list_conversations(
    page: int = Query(1, ge=1, description="页码，≥1"),
    page_size: int = Query(20, ge=1, le=100, description="每页条数，1~100"),
    keyword: Optional[str] = Query(None, description="按标题模糊匹配"),
) -> dict:
    """会话列表（问答页侧栏历史，接口文档 2.8）"""
    total, rows = get_repository().list_conversations(page=page, page_size=page_size, keyword=keyword)
    items = [
        ConversationItem(**{key: row[key] for key in ConversationItem.model_fields}).model_dump()
        for row in rows
    ]
    return ApiResponse.ok(ConversationPage(total=total, page=page, page_size=page_size, items=items).model_dump())


@router.get("/conversations/{session_id}")
async def get_conversation(session_id: str) -> dict:
    """会话详情：完整问答记录（含引用），供页面回显（接口文档 2.9）"""
    repository = get_repository()
    conversation = repository.get_conversation(session_id)
    if not conversation:
        raise BizError(CODE_NOT_FOUND, "会话不存在")

    messages = []
    for row in repository.list_messages(session_id):
        citations = None
        if row["role"] == "assistant" and row["citations"]:
            try:
                citations = [Citation(**item) for item in json.loads(row["citations"])]
            except (json.JSONDecodeError, TypeError, ValueError):
                logger.warning("消息 %s 的 citations 解析失败，按 null 返回", row["message_id"])
        messages.append(MessageItem(
            message_id=row["message_id"],
            role=row["role"],
            content=row["content"],
            citations=citations,
            trace_id=row["trace_id"] if row["role"] == "assistant" else None,
            created_at=row["created_at"],
        ))
    data = ConversationDetail(session_id=session_id, title=conversation["title"], messages=messages)
    return ApiResponse.ok(data.model_dump())


@router.delete("/conversations/{session_id}")
async def clear_conversation(session_id: str) -> dict:
    """清空指定会话的消息（保留会话行；幂等），并同步清空进程内上下文（接口文档 2.10）"""
    deleted = get_repository().clear_messages(session_id)
    conversation_store.clear(session_id)
    return ApiResponse.ok({"session_id": session_id, "deleted_messages": deleted})


@router.post("/feedback")
async def submit_feedback(request: FeedbackRequest) -> dict:
    """答案反馈：点赞/点踩（接口文档 2.7；message_id 不存在返回 1005）"""
    repository = get_repository()
    if not repository.get_message(request.message_id):
        raise BizError(CODE_NOT_FOUND, "消息不存在")

    feedback_id = new_feedback_id()
    created_at = now_iso()
    repository.add_feedback(
        feedback_id=feedback_id,
        message_id=request.message_id,
        session_id=request.session_id,
        rating=request.rating,
        comment=request.comment,
        created_at=created_at,
    )
    return ApiResponse.ok(
        FeedbackData(feedback_id=feedback_id, created_at=created_at).model_dump(),
        message="感谢反馈",
    )
