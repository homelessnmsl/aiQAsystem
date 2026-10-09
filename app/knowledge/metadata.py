"""doc_id 规则、文件名安全处理与引用位置格式化（架构设计 6.5；接口文档 1.5；W2-02/03）

- new_doc_id：doc_{yyyymmdd}_{6位}（接口文档 1.5 ID 规则）；
- safe_filename：上传文件名的路径穿越防护（NFR-S-02）；
- format_location：citations[].location 的中文位置文本（架构 6.5 优先级表）。
"""
from __future__ import annotations

import re
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Optional

from ..core.logging import CST, random_id_suffix

#: Windows/Unix 文件名非法字符（含控制字符）
_ILLEGAL_CHARS = re.compile(r'[\\/:*?"<>|\r\n\t\x00-\x1f]')


def new_doc_id(when: Optional[datetime] = None) -> str:
    """生成文档 ID：doc_20261008_3f9a1c（接口文档 1.5）"""
    moment = when or datetime.now(CST)
    return f"doc_{moment:%Y%m%d}_{random_id_suffix()}"


def chunk_id_of(doc_id: str, chunk_index: int) -> str:
    """切片 ID 规则：{doc_id}:{chunk_index}（架构设计 6.6）"""
    return f"{doc_id}:{chunk_index}"


def safe_filename(name: str) -> str:
    """上传文件名安全处理：去目录部分、去非法字符、限长 100（NFR-S-02）"""
    base = Path(str(name).replace("\\", "/")).name
    base = _ILLEGAL_CHARS.sub("_", base).strip().strip(".")
    return (base or "unnamed")[:100]


def format_location(metadata: Dict[str, Any]) -> str:
    """引用位置文本（架构设计 6.5 优先级：工作表 > 页码 > 章节 > 行号 > 兜底）"""
    sheet = metadata.get("sheet_name")
    page = metadata.get("page_no")
    section = metadata.get("section")
    row_start = metadata.get("row_start")
    row_end = metadata.get("row_end")

    if sheet:
        if row_start and row_end and row_start != row_end:
            return f"工作表「{sheet}」第 {row_start}~{row_end} 行"
        if row_start:
            return f"工作表「{sheet}」第 {row_start} 行"
        return f"工作表「{sheet}」"
    if page:
        return f"第 {page} 页"
    if section:
        section_end = metadata.get("section_end")
        if section_end and section_end != section:
            return f"章节「{section}」~「{section_end}」"
        return f"章节「{section}」"
    if row_start and row_end and row_start != row_end:
        return f"第 {row_start}~{row_end} 行"
    if row_start:
        return f"第 {row_start} 行"
    index = metadata.get("chunk_index")
    return f"第 {int(index) + 1} 段" if isinstance(index, int) else "原文片段"
