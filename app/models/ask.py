"""API-06 RAG 问答模型（接口文档 2.6 / 第3章对照表）"""
from typing import List, Optional

from pydantic import BaseModel, Field

from .chat import Usage


class AskRequest(BaseModel):
    """POST /api/ask 请求体（字段契约见接口文档 2.6）"""

    question: str = Field(..., min_length=1, max_length=500, description="用户问题（1~500字）")
    session_id: Optional[str] = Field(None, max_length=64, description="会话ID；不传自动新建")
    top_k: Optional[int] = Field(None, ge=1, le=10, description="返回条数（1~10），默认取配置")
    score_threshold: Optional[float] = Field(None, ge=0, le=1, description="相似度阈值（0~1），默认取配置")
    use_rerank: Optional[bool] = Field(None, description="是否启用重排（第3周 A/B 对比用）")
    stream: bool = Field(False, description="true 时走 SSE（第3周交付，见接口文档 2.11）")


class Citation(BaseModel):
    """引用条目（由程序依据 chunk 元数据生成，ADR-06）"""

    index: int
    doc_id: str
    source_file: str
    location: str
    snippet: str
    score: float
    rerank_score: Optional[float] = None
    chunk_id: str


class RetrievedItem(BaseModel):
    """检索明细条目（供 PE 统计 M-01；rank 为原始召回排名）"""

    rank: int
    chunk_id: str
    doc_id: str
    source_file: str
    location: str
    snippet: str
    score: float
    rerank_score: Optional[float] = None


class Latency(BaseModel):
    """分段耗时（毫秒）"""

    total: int
    retrieval: int
    rerank: int = 0
    generation: int = 0


class AskResponse(BaseModel):
    """POST /api/ask 响应 data 部分（接口文档 2.6）"""

    trace_id: str
    session_id: str
    message_id: str
    question: str
    rewritten_question: Optional[str] = None
    answer: str
    answer_type: str  # answered / not_found / clarify
    citations: List[Citation]
    retrieved: List[RetrievedItem]
    model: Optional[str] = None
    usage: Optional[Usage] = None
    latency_ms: Latency
    created_at: str
