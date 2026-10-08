"""Word(.docx) 解析器（python-docx；架构设计 6.3；W2-02）

- 按文档流顺序读取段落与表格（iter_block_items）；
- 用标题样式维护「章节路径」作为引用定位（docx 无稳定页码，架构 6.3 允许退化）；
- 表格逐行转「列名: 值」文本，行号使用表内序号。
"""
from __future__ import annotations

from pathlib import Path
from typing import Iterator, List, Union

from docx import Document
from docx.document import Document as DocxDocument
from docx.oxml.ns import qn
from docx.table import Table
from docx.text.paragraph import Paragraph

from .base import BaseLoader, Block, ParsedDocument


def _iter_block_items(parent) -> Iterator[Union[Paragraph, Table]]:
    """按文档顺序迭代段落与表格（python-docx 官方配方）"""
    if isinstance(parent, DocxDocument):
        parent_elm = parent.element.body
    else:  # 单元格
        parent_elm = parent._element
    for child in parent_elm.iterchildren():
        if child.tag == qn("w:p"):
            yield Paragraph(child, parent)
        elif child.tag == qn("w:tbl"):
            yield Table(child, parent)


def _heading_level(paragraph: Paragraph) -> int | None:
    """识别标题级别：支持英文 Heading N 与中文「标题 N」样式，非标题返回 None"""
    style_name = (paragraph.style.name or "").strip()
    for prefix in ("Heading ", "标题 "):
        if style_name.startswith(prefix):
            suffix = style_name[len(prefix):].strip()
            if suffix.isdigit():
                return int(suffix)
    return None


class DocxLoader(BaseLoader):
    """Word 文档 → 段落/表格 Block（section 为标题路径）"""

    file_type = "docx"
    extensions = (".docx",)

    def parse(self, path: Path) -> ParsedDocument:
        document = Document(str(path))
        doc = ParsedDocument(filename=path.name, file_type=self.file_type)

        heading_stack: List[str] = []          # 各级标题文本
        empty_paragraphs = 0

        for item in _iter_block_items(document):
            if isinstance(item, Paragraph):
                text = item.text.strip()
                if not text:
                    empty_paragraphs += 1
                    continue
                level = _heading_level(item)
                if level:
                    heading_stack = heading_stack[: level - 1]
                    heading_stack.append(text)
                    continue
                section = " > ".join(heading_stack) or None
                doc.blocks.append(Block(text=text, section=section))
            else:  # Table
                section = " > ".join(heading_stack) or None
                doc.blocks.extend(self._table_blocks(item, section))

        if not doc.blocks:
            doc.warnings.append("文档中没有可提取的文本或表格内容")
        return doc

    @staticmethod
    def _table_blocks(table: Table, section: str | None) -> List[Block]:
        """表格 → 逐行 Block（「列名: 值」，跳过整行为空的行）"""
        rows = [[cell.text.strip() for cell in row.cells] for row in table.rows]
        if not rows:
            return []
        header = [
            (name or f"列{i + 1}").replace("\n", " ")
            for i, name in enumerate(rows[0])
        ]
        blocks: List[Block] = []
        for row_index, row in enumerate(rows[1:], start=2):
            pairs = [
                f"{header[i] if i < len(header) else f'列{i + 1}'}: {value}"
                for i, value in enumerate(row)
                if value
            ]
            if not pairs:
                continue
            blocks.append(
                Block(
                    text="；".join(pairs),
                    section=section,
                    row_start=row_index,
                    row_end=row_index,
                    block_type="table",
                )
            )
        return blocks
