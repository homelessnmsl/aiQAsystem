"""API-04 文档列表 GET /api/documents（接口文档 2.4；W2-06）

数据源：SQLite documents 台账（与 Chroma 的一致性由健康检查对账，架构 6.6）。
"""
from typing import Optional

from fastapi import APIRouter, Query

from ..core.errors import CODE_VALIDATION_FAILED, BizError
from ..core.response import ApiResponse
from ..models.document import DocumentItem, PageData
from ..services.repository import get_repository

router = APIRouter(prefix="/api", tags=["documents"])

ALLOWED_FILE_TYPES = {"pdf", "docx", "xlsx", "txt", "md"}
ALLOWED_STATUS = {"success", "failed", "all"}


@router.get("/documents")
async def list_documents(
    page: int = Query(1, ge=1, description="页码，≥1"),
    page_size: int = Query(20, ge=1, le=100, description="每页条数，1~100"),
    keyword: Optional[str] = Query(None, description="按文件名模糊匹配"),
    file_type: Optional[str] = Query(None, description="按格式过滤：pdf/docx/xlsx/txt/md"),
    status: str = Query("success", description="success / failed / all"),
) -> dict:
    """知识库文档列表（知识库管理页表格数据，FR-KB-04 / US-11）"""
    if file_type is not None and file_type not in ALLOWED_FILE_TYPES:
        raise BizError(CODE_VALIDATION_FAILED, "file_type 取值不合法（pdf/docx/xlsx/txt/md）")
    if status not in ALLOWED_STATUS:
        raise BizError(CODE_VALIDATION_FAILED, "status 取值必须为 success / failed / all")

    total, rows = get_repository().list_documents(
        page=page, page_size=page_size, keyword=keyword, file_type=file_type, status=status
    )
    items = [
        DocumentItem(**{key: row[key] for key in DocumentItem.model_fields}).model_dump()
        for row in rows
    ]
    return ApiResponse.ok(PageData(total=total, page=page, page_size=page_size, items=items).model_dump())
