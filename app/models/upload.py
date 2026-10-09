"""API-03 上传并建库模型（接口文档 2.3 / 第3章对照表）"""
from typing import List, Optional

from pydantic import BaseModel


class UploadItem(BaseModel):
    """单个文件的处理结果（items[]）"""

    doc_id: Optional[str] = None
    filename: str
    file_type: str
    size_bytes: int
    status: str  # success / failed / skipped（重复且未覆盖，第3周启用）
    chunk_count: int = 0
    elapsed_ms: int = 0
    error_code: Optional[int] = None
    error_message: Optional[str] = None


class UploadResult(BaseModel):
    """上传接口 data 结构：本次上传统计 + 逐文件明细"""

    total: int
    succeeded: int
    failed: int
    items: List[UploadItem]
