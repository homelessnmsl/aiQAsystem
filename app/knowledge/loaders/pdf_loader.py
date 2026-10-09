"""PDF 解析器（pypdf；架构设计 6.3；W2-02）

- 逐页提取文本，保留页码作为引用定位（FR-CIT-02）；
- 页眉/页脚启发式去除：同页首尾各 2 行、在 ≥60% 页面重复且长度 ≤60 字 → 视为噪声；
- 扫描版（无文本层）不报错中断，写入 warnings 由上层转成用户提示。
"""
from __future__ import annotations

from collections import Counter
from pathlib import Path

from pypdf import PdfReader

from .base import BaseLoader, Block, ParsedDocument


class PdfLoader(BaseLoader):
    """PDF → 逐页 Block（page_no 从 1 开始）"""

    file_type = "pdf"
    extensions = (".pdf",)

    _NOISE_RATIO = 0.6      # 跨页重复阈值
    _NOISE_MAX_LEN = 60     # 页眉页脚一般较短

    def parse(self, path: Path) -> ParsedDocument:
        reader = PdfReader(str(path))
        doc = ParsedDocument(filename=path.name, file_type=self.file_type)

        pages: list[list[str]] = []
        for page in reader.pages:
            raw = page.extract_text() or ""
            pages.append([line.strip() for line in raw.splitlines()])

        noise = self._detect_noise(pages)

        for page_no, lines in enumerate(pages, start=1):
            text = "\n".join(line for line in lines if line and line not in noise)
            if text.strip():
                doc.blocks.append(Block(text=text, page_no=page_no))

        if not doc.blocks:
            doc.warnings.append("未提取到文本：可能是扫描版 PDF（暂不支持 OCR 识别）")
        return doc

    def _detect_noise(self, pages: list[list[str]]) -> set[str]:
        """检测跨页重复的页眉/页脚文本（页数 < 3 时不处理）"""
        if len(pages) < 3:
            return set()
        counter: Counter[str] = Counter()
        for lines in pages:
            candidates = {line for line in (lines[:2] + lines[-2:]) if line}
            counter.update(candidates)
        threshold = max(2, int(len(pages) * self._NOISE_RATIO))
        return {
            line
            for line, count in counter.items()
            if count >= threshold and len(line) <= self._NOISE_MAX_LEN
        }
