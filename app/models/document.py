"""API-04 文档列表模型（接口文档 2.4 / 第3章对照表）"""
from typing import List

from pydantic import BaseModel


class DocumentItem(BaseModel):
    """文档台账一行（与 SQLite documents 表、Chroma 实际数据保持一致）"""

    doc_id: str
    filename: str
    file_type: str
    size_bytes: int
    chunk_count: int
    upload_time: str
    status: str  # processing / success / failed / deleted


class PageData(BaseModel):
    """分页数据（接口文档 1.2：所有列表接口统一）"""

    total: int
    page: int
    page_size: int
    items: List[DocumentItem]
