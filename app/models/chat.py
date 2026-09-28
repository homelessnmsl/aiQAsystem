"""API-02 基础对话模型（接口文档 2.2；第 3 章对照表）

字段逐字对齐 docs/接口文档.md：ChatRequest / ChatResponse / Usage。
"""
from pydantic import BaseModel, Field


class ChatRequest(BaseModel):
    """POST /api/chat 请求体（字段契约见接口文档 2.2）"""

    message: str = Field(..., min_length=1, max_length=2000, description="用户输入（1~2000字）")
    session_id: str | None = Field(None, max_length=64, description="会话ID；不传则自动新建")
    system_prompt: str | None = Field(None, max_length=4000, description="覆盖默认系统提示词（调试用）")
    temperature: float = Field(0.7, ge=0, le=2, description="温度参数，0~2")
    max_tokens: int = Field(1024, ge=1, le=4096, description="最大生成 token 数，1~4096")
    stream: bool = Field(False, description="true 时以 SSE 流式返回（可选，见接口文档 2.11）")


class Usage(BaseModel):
    """Token 用量（对齐接口文档 Usage 模型）"""

    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0


class ChatResponse(BaseModel):
    """POST /api/chat 响应 data 部分（接口文档 2.2）"""

    trace_id: str
    session_id: str
    reply: str
    model: str
    usage: Usage
    latency_ms: int
    created_at: str
