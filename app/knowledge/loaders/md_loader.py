"""Markdown 解析器（标准库；架构设计 6.3；W2-02）

- 按 `#` 标题层级维护章节路径（section），正文按段落/列表聚合；
- 保留代码块完整性（不与正文混切）；
- 记录行号范围，供引用定位退化使用。
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import List

from .base import BaseLoader, Block, ParsedDocument

_HEADING = re.compile(r"^(#{1,6})\s+(.*\S)\s*$")

#: Markdown 表格分隔行，如 | :--- | :--- |
_TABLE_SEPARATOR = re.compile(r"^\s*\|[\s:\-|]+\|\s*$")


def render_markdown_tables(text: str) -> str:
    """把 Markdown 表格渲染为自然语言行（D2-01 修复，W3-02）

    - 丢弃分隔行与管道符干扰（``| :--- | :--- |``）；
    - 两列表格 → 「键：值」逐行渲染（与 Excel 解析风格一致，实测相似度最高）；
    - 多列表格 → 单元格用「；」连接，保留表头行。
    """
    rendered: List[str] = []
    for line in text.splitlines():
        if _TABLE_SEPARATOR.match(line):
            continue
        if line.strip().startswith("|") and "|" in line:
            cells = [cell.strip() for cell in line.strip().strip("|").split("|")]
            cells = [cell for cell in cells if cell]
            if len(cells) == 2:
                rendered.append(f"{cells[0]}：{cells[1]}")
            elif cells:
                rendered.append("；".join(cells))
            continue
        rendered.append(line)
    return "\n".join(rendered)


class MarkdownLoader(BaseLoader):
    """Markdown → 段落/列表/代码块 Block（section 为标题路径）"""

    file_type = "md"
    extensions = (".md", ".markdown")

    def parse(self, path: Path) -> ParsedDocument:
        text = path.read_text(encoding="utf-8", errors="replace")
        doc = ParsedDocument(filename=path.name, file_type=self.file_type)

        heading_stack: List[str] = []
        lines = text.splitlines()
        buffer: List[str] = []
        block_type = "text"
        start_line = 1
        in_code = False

        def flush(end_line: int) -> None:
            nonlocal buffer, start_line, block_type
            raw = "\n".join(buffer).strip()
            if raw:
                is_table = block_type == "table" or any(
                    line.strip().startswith("|") for line in raw.splitlines()
                )
                content = render_markdown_tables(raw) if is_table else raw
                if content.strip():
                    doc.blocks.append(
                        Block(
                            text=content,
                            section=" > ".join(heading_stack) or None,
                            row_start=start_line,
                            row_end=end_line,
                            block_type="table" if is_table else block_type,
                        )
                    )
            buffer = []

        for line_no, line in enumerate(lines, start=1):
            stripped = line.strip()

            if stripped.startswith("```"):
                if in_code:
                    buffer.append(line)
                    flush(line_no)
                    in_code = False
                else:
                    if buffer:
                        flush(line_no - 1)
                    in_code = True
                    block_type = "text"
                    buffer = [line]
                    start_line = line_no
                continue

            if in_code:
                buffer.append(line)
                continue

            match = _HEADING.match(line)
            if match:
                if buffer:
                    flush(line_no - 1)
                level = len(match.group(1))
                heading_stack = heading_stack[: level - 1]
                heading_stack.append(match.group(2).strip())
                continue

            if not stripped:
                if buffer:
                    flush(line_no - 1)
                continue

            if not buffer:
                start_line = line_no
                if stripped.startswith("|"):
                    block_type = "table"
                else:
                    block_type = "list" if re.match(r"^([-*+]|\d+\.)\s+", stripped) else "text"
            buffer.append(line)

        if buffer:
            flush(len(lines))

        if not doc.blocks:
            doc.warnings.append("文件内容为空")
        return doc
