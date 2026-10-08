"""Excel(.xlsx) 解析器（openpyxl；架构设计 6.3 / ADR-07；W2-02）

- 逐工作表读取，首行作为表头，数据行转「列名: 值」文本（行文本自描述，切片天然带表头）；
- data_only=True 读取公式缓存值（未计算过的公式返回 None 并跳过）；
- 引用定位：工作表名 + 行号（ADR-07 决策：v1 到工作表+行号，不到单元格）。
"""
from __future__ import annotations

from pathlib import Path
from typing import Any, List

from openpyxl import load_workbook

from .base import BaseLoader, Block, ParsedDocument


class XlsxLoader(BaseLoader):
    """Excel → 逐行 Block（sheet_name + 行号定位）"""

    file_type = "xlsx"
    extensions = (".xlsx",)

    def parse(self, path: Path) -> ParsedDocument:
        doc = ParsedDocument(filename=path.name, file_type=self.file_type)
        workbook = load_workbook(filename=str(path), read_only=True, data_only=True)
        try:
            for sheet in workbook.worksheets:
                rows: List[tuple[Any, ...]] = list(sheet.iter_rows(values_only=True))
                if not rows:
                    continue
                header = [
                    self._cell_text(value) or f"列{index + 1}"
                    for index, value in enumerate(rows[0])
                ]
                for row_index, row in enumerate(rows[1:], start=2):
                    pairs = []
                    for col_index, value in enumerate(row):
                        cell_text = self._cell_text(value)
                        if not cell_text:
                            continue
                        name = header[col_index] if col_index < len(header) else f"列{col_index + 1}"
                        pairs.append(f"{name}: {cell_text}")
                    if not pairs:
                        continue
                    doc.blocks.append(
                        Block(
                            text="；".join(pairs),
                            sheet_name=sheet.title,
                            row_start=row_index,
                            row_end=row_index,
                            block_type="table",
                        )
                    )
        finally:
            workbook.close()

        if not doc.blocks:
            doc.warnings.append("工作簿中没有可用的数据行")
        return doc

    @staticmethod
    def _cell_text(value: Any) -> str:
        """单元格值转文本（None → 空串；浮点整数去掉小数点尾巴）"""
        if value is None:
            return ""
        if isinstance(value, float) and value.is_integer():
            return str(int(value))
        return str(value).strip()
