"""API-04 文档列表 / API-05 删除文档（接口文档 2.4 / 2.5；W2-06 / W3-06）

- GET    /api/documents              文档台账列表（数据源 SQLite，对账见健康检查）
- DELETE /api/documents/{doc_id}     删除文档及其全部向量与原始文件（架构 6.11 顺序）
"""
import logging
import shutil
from typing import Optional

from fastapi import APIRouter, Query

from ..core.config import settings
from ..core.errors import CODE_NOT_FOUND, CODE_VALIDATION_FAILED, BizError
from ..core.response import ApiResponse
from ..knowledge.store import vector_store
from ..models.document import DocumentItem, PageData
from ..services.repository import get_repository

logger = logging.getLogger(__name__)

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


@router.delete("/documents/{doc_id}")
async def delete_document(doc_id: str) -> dict:
    """删除文档及其全部向量与原始文件（FR-KB-05 / US-10；接口文档 2.5）

    - 台账不存在或已删除 → 1005（重复删除安全，无副作用）；
    - 执行顺序（架构 6.11）：删向量 → 删原始文件 → 更新台账；
    - 台账保留记录并置 status=deleted，便于审计与对账。
    """
    repository = get_repository()
    document = repository.get_document(doc_id)
    if not document or document.get("status") == "deleted":
        raise BizError(CODE_NOT_FOUND, "文档不存在或已被删除")

    # 1) 删向量（失败抛 2003；此时台账不变，可安全重试）
    deleted_chunks = vector_store.delete_by_doc(doc_id)

    # 2) 删原始文件目录（data/uploads/{doc_id}/；不存在或失败不影响主流程）
    _remove_upload_dir(doc_id)

    # 3) 台账置 deleted（保留记录便于审计）
    repository.set_document_status(doc_id, "deleted")

    logger.info("文档删除完成：%s（%d 个切片）", doc_id, deleted_chunks)
    return ApiResponse.ok({"doc_id": doc_id, "deleted_chunks": deleted_chunks})


def _remove_upload_dir(doc_id: str) -> None:
    """删除上传目录 data/uploads/{doc_id}/（防目录穿越：仅允许上传根目录内的子目录）"""
    upload_root = settings.upload_dir.resolve()
    target = (upload_root / doc_id).resolve()
    if upload_root not in target.parents:
        logger.warning("跳过异常上传目录：%s", target)
        return
    shutil.rmtree(target, ignore_errors=True)
