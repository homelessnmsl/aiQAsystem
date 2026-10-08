"""TXT 解析器（chardet 识别编码；架构设计 6.3；W2-02）

- 自动识别 UTF-8 / GBK / UTF-8-SIG：chardet 置信度低时按候选顺序尝试；
- 按空行分段（段落），保留 1 起的行号范围作为引用定位（FR-CIT-02）。
"""
from __future__ import annotations

from pathlib import Path
from typing import List, Optional, Tuple

import chardet

from .base import BaseLoader, Block, ParsedDocument

#: 候选编码（覆盖中文环境常见情况）
CANDIDATES = ("utf-8", "gbk", "utf-8-sig")


class TxtLoader(BaseLoader):
    """纯文本 → 段落 Block（row_start/row_end 为文件行号）"""

    file_type = "txt"
    extensions = (".txt",)

    def parse(self, path: Path) -> ParsedDocument:
        doc = ParsedDocument(filename=path.name, file_type=self.file_type)
        text, encoding = self._read_text(path)
        if encoding is None:
            doc.warnings.append("编码无法识别（已尝试 UTF-8/GBK/UTF-8-SIG）")
            return doc

        lines = text.splitlines()
        buffer: List[str] = []
        start: Optional[int] = None

        for line_no, raw_line in enumerate(lines, start=1):
            stripped = raw_line.strip()
            if stripped:
                if start is None:
                    start = line_no
                buffer.append(stripped)
            elif buffer:
                self._flush(doc, buffer, start, line_no - 1)
                buffer, start = [], None
        if buffer:
            self._flush(doc, buffer, start, len(lines))

        if not doc.blocks:
            doc.warnings.append("文件内容为空")
        return doc

    @staticmethod
    def _flush(doc: ParsedDocument, buffer: List[str], start: Optional[int], end: int) -> None:
        """把一段连续非空行写成一个 Block"""
        doc.blocks.append(
            Block(
                text="\n".join(buffer),
                row_start=start,
                row_end=end if end >= (start or 0) else start,
            )
        )

    @staticmethod
    def _read_text(path: Path) -> Tuple[str, Optional[str]]:
        """读取文本并返回 (内容, 实际编码)；全部失败返回 ("", None)"""
        raw = path.read_bytes()
        for candidate in CANDIDATES:
            try:
                return raw.decode(candidate), candidate
            except UnicodeDecodeError:
                continue
        detected = chardet.detect(raw).get("encoding") if raw else None
        if detected:
            try:
                return raw.decode(detected), detected
            except (UnicodeDecodeError, LookupError):
                pass
        return "", None
