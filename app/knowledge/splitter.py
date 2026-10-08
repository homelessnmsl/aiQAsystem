"""结构化切片（架构设计 6.4；W2-03）

输入 ``ParsedDocument``，输出可直接写入 Chroma 的 ``Chunk`` 列表：
1. 结构优先：按「结构段」聚合 Block（同页 / 同工作表 / 同章节）；
2. 长度兜底：段文本超过 CHUNK_SIZE 时用 RecursiveCharacterTextSplitter
   （中文友好分隔符：段落 → 换行 → 句号 → 逗号 → 硬切）并保留 CHUNK_OVERLAP 重叠；
3. 过短合并：< MIN_CHUNK_CHARS 的块优先与相邻块合并；
4. Excel：按 EXCEL_ROWS_PER_CHUNK 行分组，行文本自描述（「列名: 值」）天然带表头；
5. 元数据：doc_id / filename / file_type / chunk_index / 页码或工作表或章节或行号 /
   char_count / embedding_model / created_at（架构 6.5，Chroma 仅支持 str/int/float/bool）。
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Sequence, Tuple

from langchain_text_splitters import RecursiveCharacterTextSplitter

from ..core.config import settings
from ..core.logging import now_iso
from .loaders.base import Block, ParsedDocument
from .metadata import chunk_id_of

logger = logging.getLogger(__name__)

#: 中文友好的递归分隔符（越靠前优先级越高）
SEPARATORS: Sequence[str] = ["\n\n", "\n", "。", "！", "？", "；", "，", " ", ""]


@dataclass
class Chunk:
    """写入向量库的最小单位（content 与 Chroma 兼容 metadata）"""

    chunk_id: str
    content: str
    metadata: Dict[str, Any]


# --------------------------------------------------------------------------- #
# 分组
# --------------------------------------------------------------------------- #
def _structural_key(block: Block, file_type: str) -> Tuple:
    """结构段标识：Excel 按工作表，其余按 页码 + 章节"""
    if file_type == "xlsx":
        return (block.sheet_name,)
    return (block.page_no, block.section)


def _group_blocks(parsed: ParsedDocument) -> List[List[Block]]:
    """把 Block 列表切成「结构段」：结构变化、长度达到上限或 Excel 行数上限即断开"""
    groups: List[List[Block]] = []
    current: List[Block] = []

    for block in parsed.blocks:
        if current:
            same_key = _structural_key(block, parsed.file_type) == _structural_key(current[0], parsed.file_type)
            long_enough = sum(len(b.text) for b in current) >= settings.CHUNK_SIZE
            excel_full = parsed.file_type == "xlsx" and len(current) >= settings.EXCEL_ROWS_PER_CHUNK
            if (not same_key) or long_enough or excel_full:
                groups.append(current)
                current = []
        current.append(block)

    if current:
        groups.append(current)
    return groups


# --------------------------------------------------------------------------- #
# 切分与偏移映射
# --------------------------------------------------------------------------- #
def _build_splitter() -> RecursiveCharacterTextSplitter:
    """按 .env 参数构建切片器（CHUNK_SIZE / CHUNK_OVERLAP）"""
    return RecursiveCharacterTextSplitter(
        chunk_size=settings.CHUNK_SIZE,
        chunk_overlap=settings.CHUNK_OVERLAP,
        separators=list(SEPARATORS),
        keep_separator=True,
    )


def _piece_offsets(text: str, pieces: Sequence[str]) -> List[Tuple[str, int]]:
    """把切分结果映射回原文起始偏移（用于把 chunk 关联到 Block 位置）"""
    result: List[Tuple[str, int]] = []
    cursor = 0
    for piece in pieces:
        index = text.find(piece, cursor)
        if index < 0:
            index = text.find(piece)
        if index < 0:
            index = cursor
        result.append((piece, index))
        cursor = index + 1
    return result


def _cover_blocks(piece_start: int, piece_end: int, blocks: Sequence[Block], starts: Sequence[int]) -> List[Block]:
    """找出与片段字符区间重叠的 Block（用于提取页码/工作表/章节/行号）"""
    covered: List[Block] = []
    for block, start in zip(blocks, starts):
        end = start + len(block.text)
        if end <= piece_start:
            continue
        if start >= piece_end:
            break
        covered.append(block)
    if not covered and blocks:
        covered = [blocks[0]]
    return covered


def _position_meta(covered: Sequence[Block]) -> Dict[str, Any]:
    """从覆盖的 Block 中提炼位置元数据（架构 6.5）"""
    if not covered:
        return {}
    first = covered[0]
    meta: Dict[str, Any] = {}
    if first.page_no is not None:
        meta["page_no"] = int(first.page_no)
    if first.sheet_name:
        meta["sheet_name"] = str(first.sheet_name)
    if first.section:
        meta["section"] = str(first.section)
    row_starts = [b.row_start for b in covered if b.row_start is not None]
    row_ends = [b.row_end for b in covered if b.row_end is not None]
    if row_starts:
        meta["row_start"] = int(min(row_starts))
    if row_ends:
        meta["row_end"] = int(max(row_ends))
    return meta


# --------------------------------------------------------------------------- #
# 主流程
# --------------------------------------------------------------------------- #
def split_document(parsed: ParsedDocument, doc_id: str, created_at: Optional[str] = None) -> List[Chunk]:
    """把解析结果切成 Chunk 列表（doc_id 由调用方生成，保证批内唯一）"""
    created = created_at or now_iso()
    splitter = _build_splitter()
    raw_chunks: List[Chunk] = []

    for group in _group_blocks(parsed):
        text = "\n".join(block.text for block in group)
        starts: List[int] = []
        position = 0
        for block in group:
            starts.append(position)
            position += len(block.text) + 1  # +1 为 join 的换行符

        max_single = settings.CHUNK_SIZE + settings.CHUNK_OVERLAP
        if len(text) <= max_single:
            pieces: List[Tuple[str, int]] = [(text, 0)]
        else:
            pieces = _piece_offsets(text, splitter.split_text(text))

        for piece, offset in pieces:
            piece = piece.strip()
            if not piece:
                continue
            covered = _cover_blocks(offset, offset + len(piece), group, starts)
            metadata: Dict[str, Any] = {
                "doc_id": doc_id,
                "filename": parsed.filename,
                "file_type": parsed.file_type,
                "chunk_index": len(raw_chunks),
                "char_count": len(piece),
                "embedding_model": settings.EMBEDDING_MODEL,
                "created_at": created,
            }
            metadata.update(_position_meta(covered))
            raw_chunks.append(Chunk(chunk_id=chunk_id_of(doc_id, len(raw_chunks)), content=piece, metadata=metadata))

    chunks = _merge_short_chunks(raw_chunks)
    logger.info(
        "切片完成：%s（%s）→ %d 个 chunk，平均 %d 字",
        parsed.filename,
        parsed.file_type,
        len(chunks),
        (sum(len(c.content) for c in chunks) // len(chunks)) if chunks else 0,
    )
    return chunks


def _row_span(metadata: Dict[str, Any]) -> Optional[int]:
    """元数据中的行数跨度（无行号信息时返回 None）"""
    start = metadata.get("row_start")
    end = metadata.get("row_end")
    if start is None or end is None:
        return None
    return int(end) - int(start) + 1


def _merge_short_chunks(chunks: List[Chunk]) -> List[Chunk]:
    """短块合并：向 300~600 字目标靠拢，并重新编号 chunk_index / chunk_id

    合并约束（架构 6.4）：
    - 同一页码 / 同一工作表（不跨页、不跨表，保证引用位置可信）；
    - 允许跨章节聚合（FAQ/制度类文档小节很短，聚合后检索单元更完整），
      跨章节时记录 ``section_end``，引用位置显示为「章节 A ~ 章节 B」；
    - 合并后总长度 ≤ CHUNK_SIZE；Excel 合并后行数 ≤ EXCEL_ROWS_PER_CHUNK。
    """
    merge_target = max(settings.MIN_CHUNK_CHARS, settings.CHUNK_MERGE_TARGET)
    merged: List[Chunk] = []
    for chunk in chunks:
        if merged:
            previous = merged[-1]
            same_page = previous.metadata.get("page_no") == chunk.metadata.get("page_no")
            same_sheet = previous.metadata.get("sheet_name") == chunk.metadata.get("sheet_name")
            combined_length = len(previous.content) + len(chunk.content)
            previous_span = _row_span(previous.metadata)
            current_span = _row_span(chunk.metadata)
            rows_ok = (
                previous_span + current_span <= settings.EXCEL_ROWS_PER_CHUNK
                if previous_span is not None and current_span is not None
                else True
            )
            if (
                len(previous.content) < merge_target
                and same_page
                and same_sheet
                and combined_length <= settings.CHUNK_SIZE
                and rows_ok
            ):
                previous.content = f"{previous.content}\n{chunk.content}"
                previous.metadata["char_count"] = len(previous.content)
                if previous_span is not None and current_span is not None:
                    previous.metadata["row_end"] = chunk.metadata.get("row_end")
                new_section = chunk.metadata.get("section")
                if new_section and new_section != previous.metadata.get("section"):
                    previous.metadata["section_end"] = new_section
                continue
        merged.append(chunk)
    for index, chunk in enumerate(merged):
        chunk.metadata["chunk_index"] = index
        chunk.chunk_id = chunk_id_of(str(chunk.metadata["doc_id"]), index)
    return merged
