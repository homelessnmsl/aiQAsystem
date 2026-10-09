"""统一解析数据结构与解析器基类（架构设计 6.2；W2-02）

约定：
- Block 是最小结构单元，必须携带可溯源位置（页码 / 工作表+行号 / 章节 / 行号）；
- ParsedDocument.blocks 保持文档顺序；
- 解析器只负责「文件 → Block 列表」，不关心切片长度（切片交给 splitter，架构 6.1）。
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional


@dataclass
class Block:
    """文档结构块（架构设计 6.2）"""

    text: str
    page_no: Optional[int] = None      # PDF/Word：页码（1 起）
    sheet_name: Optional[str] = None   # Excel：工作表名
    row_start: Optional[int] = None    # Excel/TXT：起始行号（1 起）
    row_end: Optional[int] = None      # Excel/TXT：结束行号
    section: Optional[str] = None      # Word/Markdown：标题路径（如 "3.2 报销标准"）
    block_type: str = "text"           # text | table | heading | list

    def __post_init__(self) -> None:
        """统一清理文本首尾空白（全角空格一并处理）"""
        self.text = (self.text or "").strip().strip("\u3000")


@dataclass
class ParsedDocument:
    """一次解析的完整结果（filename 为原始文件名）"""

    filename: str
    file_type: str                     # pdf|docx|xlsx|txt|md
    blocks: List[Block] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)

    @property
    def char_count(self) -> int:
        """全部块文本的字数合计（入库摘要用）"""
        return sum(len(block.text) for block in self.blocks)


class BaseLoader(ABC):
    """解析器基类：子类实现 parse()；异常由 registry 统一翻译为业务错误码"""

    file_type: str = ""
    extensions: tuple[str, ...] = ()

    @abstractmethod
    def parse(self, path: Path) -> ParsedDocument:
        """解析文件为 ParsedDocument（不抛业务异常，交给 registry 包装）"""
        raise NotImplementedError
