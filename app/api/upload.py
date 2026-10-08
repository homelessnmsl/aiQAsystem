"""API-03 上传并建库 POST /api/upload（接口文档 2.3；W2-05）

单文件流程：白名单/大小校验 → 落盘 data/uploads/{doc_id}/ → 解析 → 切片 → 向量化 → 入 Chroma
→ 更新 SQLite 台账（先 processing，成功后 success；失败记 failed）。

请求级错误（1002/1003）整体拒绝；文件级错误逐条返回（status=failed + error_code=2002），
全部失败时整体返回 2002（HTTP 422），data.items 仍逐条列出（接口文档 2.3）。
"""
from __future__ import annotations

import logging
import time
from pathlib import Path
from typing import List, Optional, Tuple

from fastapi import APIRouter, File, Form, UploadFile

from ..core.config import settings
from ..core.errors import (
    CODE_FILE_TOO_LARGE,
    CODE_FILE_TYPE_UNSUPPORTED,
    CODE_INTERNAL_ERROR,
    CODE_PARSE_FAILED,
    BizError,
)
from ..core.logging import now_iso
from ..core.response import ApiResponse
from ..knowledge.loaders.registry import SUPPORTED_EXTENSIONS
from ..knowledge.metadata import new_doc_id, safe_filename
from ..models.upload import UploadItem, UploadResult
from ..services.ingestion import IngestResult, ingest_file
from ..services.repository import get_repository

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api", tags=["documents"])

#: 扩展名 → file_type（接口文档 1.5 枚举：pdf/docx/xlsx/txt/md）
FILE_TYPES = {".pdf": "pdf", ".docx": "docx", ".xlsx": "xlsx", ".txt": "txt", ".md": "md"}


def _ext_of(name: str) -> str:
    """取小写扩展名（含点）"""
    return Path(name or "").suffix.lower()


@router.post("/upload")
async def upload_documents(
    files: Optional[List[UploadFile]] = File(
        None, description="1~5 个文件；白名单 pdf/docx/xlsx/txt/md；单个 ≤ 20MB"
    ),
    overwrite: bool = Form(False, description="同名覆盖（第3周启用 FR-DOC-05，先接受参数不生效）"),
) -> dict:
    """上传文档并构建知识库（逐文件处理，失败隔离 NFR-R-01）"""
    # ---------- 请求级校验（整体拒绝，接口文档 2.3） ----------
    file_list = [item for item in (files or []) if item and item.filename]
    if not file_list:
        raise BizError(CODE_FILE_TOO_LARGE, "请选择要上传的文件（单次 1~5 个，单个 ≤ 20MB）")
    if len(file_list) > settings.MAX_FILES_PER_UPLOAD:
        raise BizError(CODE_FILE_TOO_LARGE, f"单次最多上传 {settings.MAX_FILES_PER_UPLOAD} 个文件")

    for item in file_list:
        ext = _ext_of(item.filename)
        if ext not in FILE_TYPES or ext not in SUPPORTED_EXTENSIONS:
            raise BizError(
                CODE_FILE_TYPE_UNSUPPORTED,
                "不支持的文件类型：仅支持 PDF、Word(.docx)、Excel(.xlsx)、TXT、Markdown",
            )

    max_bytes = settings.MAX_FILE_SIZE_MB * 1024 * 1024
    payloads: List[Tuple[UploadFile, bytes]] = []
    for item in file_list:
        data = await item.read()
        if len(data) > max_bytes:
            raise BizError(
                CODE_FILE_TOO_LARGE,
                f"《{safe_filename(item.filename)}》超过 {settings.MAX_FILE_SIZE_MB}MB 限制，请压缩后重试",
            )
        payloads.append((item, data))

    # ---------- 逐文件处理（失败隔离） ----------
    repository = get_repository()
    upload_time = now_iso()
    items: List[UploadItem] = []
    succeeded = 0
    failed = 0

    for item, data in payloads:
        filename = safe_filename(item.filename)
        file_type = FILE_TYPES[_ext_of(filename)]
        doc_id = new_doc_id()
        item_started = time.perf_counter()

        try:
            # 1) 落盘：data/uploads/{doc_id}/原始文件名（架构 7.1）
            target_dir = settings.upload_dir / doc_id
            target_dir.mkdir(parents=True, exist_ok=True)
            saved_path = target_dir / filename
            saved_path.write_bytes(data)

            # 2) 台账先记 processing（写入顺序：切片入库成功后再置 success，架构 6.6）
            repository.upsert_document(
                doc_id=doc_id, filename=filename, file_type=file_type, size_bytes=len(data),
                upload_time=upload_time, chunk_count=0, status="processing",
            )

            # 3) 解析 → 切片 → 向量化 → 入 Chroma（失败抛 BizError：1002/2002/2003）
            result: IngestResult = ingest_file(saved_path, doc_id=doc_id)

            # 4) 更新台账为 success
            repository.upsert_document(
                doc_id=doc_id, filename=result.filename, file_type=result.file_type,
                size_bytes=len(data), upload_time=result.created_at or upload_time,
                chunk_count=result.chunk_count, status="success",
            )
            items.append(UploadItem(
                doc_id=doc_id, filename=result.filename, file_type=result.file_type,
                size_bytes=len(data), status="success", chunk_count=result.chunk_count,
                elapsed_ms=int((time.perf_counter() - item_started) * 1000),
            ))
            succeeded += 1
        except BizError as exc:
            repository.upsert_document(
                doc_id=doc_id, filename=filename, file_type=file_type, size_bytes=len(data),
                upload_time=upload_time, chunk_count=0, status="failed",
            )
            items.append(UploadItem(
                doc_id=None, filename=filename, file_type=file_type, size_bytes=len(data),
                status="failed", chunk_count=0,
                elapsed_ms=int((time.perf_counter() - item_started) * 1000),
                error_code=exc.code, error_message=exc.message,
            ))
            failed += 1
            logger.warning("上传失败：%s → [%s] %s", filename, exc.code, exc.message)
        except Exception as exc:  # noqa: BLE001 - 单个文件失败不影响批量
            logger.exception("上传异常：%s → %s", filename, exc)
            repository.upsert_document(
                doc_id=doc_id, filename=filename, file_type=file_type, size_bytes=len(data),
                upload_time=upload_time, chunk_count=0, status="failed",
            )
            items.append(UploadItem(
                doc_id=None, filename=filename, file_type=file_type, size_bytes=len(data),
                status="failed", chunk_count=0,
                elapsed_ms=int((time.perf_counter() - item_started) * 1000),
                error_code=CODE_INTERNAL_ERROR, error_message="处理失败：服务器内部错误",
            ))
            failed += 1

    result_payload = UploadResult(total=len(items), succeeded=succeeded, failed=failed, items=items)

    # 全部失败 → 整体 2002（HTTP 422），items 仍逐条列出（接口文档 2.3）
    if failed == len(items):
        raise BizError(CODE_PARSE_FAILED, "上传失败：全部文件均未成功入库", result_payload.model_dump())

    message = (
        f"上传完成：成功 {succeeded} 个" if failed == 0
        else f"上传完成：成功 {succeeded} 个，失败 {failed} 个"
    )
    return ApiResponse.ok(result_payload.model_dump(), message=message)
