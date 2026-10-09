"""解析器注册表：扩展名 → 解析器（架构设计 6.3；W2-02）

唯一入口 ``load_document(path)``：
- 不支持的扩展名 → BizError(1002)，HTTP 415（接口文档 1.4，FR-SEC-03 白名单）；
- 解析异常或空结果 → BizError(2002)，HTTP 422，附中文原因（FR-DOC-04）。
"""
from __future__ import annotations

import logging
from pathlib import Path

from ...core.errors import (
    CODE_FILE_TYPE_UNSUPPORTED,
    CODE_PARSE_FAILED,
    BizError,
)
from .base import BaseLoader, ParsedDocument
from .docx_loader import DocxLoader
from .md_loader import MarkdownLoader
from .pdf_loader import PdfLoader
from .txt_loader import TxtLoader
from .xlsx_loader import XlsxLoader

logger = logging.getLogger(__name__)

#: 白名单实例（扩展名 → 解析器）
_LOADERS: dict[str, BaseLoader] = {}
for _loader in (PdfLoader(), DocxLoader(), XlsxLoader(), TxtLoader(), MarkdownLoader()):
    for _extension in _loader.extensions:
        _LOADERS[_extension] = _loader

#: 支持的扩展名（上传校验用，FR-DOC-01）
SUPPORTED_EXTENSIONS: tuple[str, ...] = tuple(sorted(_LOADERS))


def loader_for(filename: str) -> BaseLoader:
    """按文件名选择解析器；不支持时抛 1002（中文提示列出白名单）"""
    extension = Path(filename).suffix.lower()
    loader = _LOADERS.get(extension)
    if loader is None:
        supported = "、".join(SUPPORTED_EXTENSIONS)
        raise BizError(
            CODE_FILE_TYPE_UNSUPPORTED,
            f"不支持的文件类型：仅支持 {supported}",
        )
    return loader


def load_document(path: str | Path) -> ParsedDocument:
    """解析文件为 ParsedDocument；失败抛 BizError（2002），单文件失败不影响批量流程"""
    file_path = Path(path)
    loader = loader_for(file_path.name)
    try:
        parsed = loader.parse(file_path)
    except BizError:
        raise
    except Exception as exc:  # 解析库异常统一翻译（NFR-R-01）
        logger.exception("解析失败：%s", file_path.name)
        raise BizError(
            CODE_PARSE_FAILED,
            f"《{file_path.name}》解析失败：文件可能已损坏或格式不正确",
        ) from exc

    if not parsed.blocks:
        reason = parsed.warnings[0] if parsed.warnings else "未提取到有效内容"
        raise BizError(CODE_PARSE_FAILED, f"《{file_path.name}》解析失败：{reason}")
    return parsed
