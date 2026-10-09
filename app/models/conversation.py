"""API-08~11 会话与反馈模型（接口文档 2.7~2.10 / 第3章对照表）"""
from typing import List, Literal, Optional

from pydantic import BaseModel, Field

from .ask import Citation


class ConversationItem(BaseModel):
    """会话列表一行（接口文档 2.8）"""

    session_id: str
    title: Optional[str] = None
    message_count: int = 0
    created_at: str
    updated_at: str


class ConversationPage(BaseModel):
    """会话列表分页（接口文档 1.2 分页约定）"""

    total: int
    page: int
    page_size: int
    items: List[ConversationItem]


class MessageItem(BaseModel):
    """会话详情中的一条消息（接口文档 2.9）"""

    message_id: str
    role: str  # user / assistant
    content: str
    citations: Optional[List[Citation]] = None
    trace_id: Optional[str] = None
    created_at: str


class ConversationDetail(BaseModel):
    """会话详情（接口文档 2.9；含引用，供页面回显恢复）"""

    session_id: str
    title: Optional[str] = None
    messages: List[MessageItem]


class FeedbackRequest(BaseModel):
    """POST /api/feedback 请求体（接口文档 2.7）"""

    message_id: str = Field(..., min_length=1, max_length=64, description="来自 /api/ask 的消息 ID")
    session_id: str = Field(..., min_length=1, max_length=64, description="会话 ID")
    rating: Literal["up", "down"] = Field(..., description="up=点赞 / down=点踩")
    comment: Optional[str] = Field(None, max_length=200, description="点踩原因，≤200 字")


class FeedbackData(BaseModel):
    """POST /api/feedback 响应 data"""

    feedback_id: str
    created_at: str
