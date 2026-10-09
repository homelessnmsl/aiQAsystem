"""W2-03 切片单测：长度 / 重叠 / 元数据（架构设计 6.4 / 6.5）"""
from pathlib import Path

from app.core.config import settings
from app.knowledge.loaders.base import Block, ParsedDocument
from app.knowledge.loaders.registry import load_document
from app.knowledge.splitter import split_document

SAMPLES = Path(__file__).resolve().parent / "sample_docs"


def _long_document() -> ParsedDocument:
    """构造 1200+ 字的连续文本（单 Block），用于验证长文切分与重叠"""
    sentences = "".join(f"第{i}条规定：员工每年享有{i % 20 + 1}天年假。" for i in range(1, 80))
    return ParsedDocument(filename="长文.txt", file_type="txt", blocks=[Block(text=sentences, row_start=1, row_end=1)])


def test_long_text_is_split_with_overlap():
    """长文本应切成多块，且相邻块存在重叠（CHUNK_OVERLAP=80）"""
    chunks = split_document(_long_document(), "doc_test_000001")
    assert len(chunks) >= 2
    for chunk in chunks:
        assert len(chunk.content) <= settings.CHUNK_SIZE + 100
    tail = chunks[0].content[-30:]
    assert tail in chunks[1].content, "相邻切片未保留重叠内容"


def test_metadata_fields_complete_and_no_none():
    """元数据字段齐全且不含 None（Chroma 仅支持 str/int/float/bool）"""
    doc = load_document(SAMPLES / "01_员工手册.pdf")
    chunks = split_document(doc, "doc_test_000002")
    assert chunks
    for chunk in chunks:
        metadata = chunk.metadata
        for key in (
            "doc_id",
            "filename",
            "file_type",
            "chunk_index",
            "char_count",
            "embedding_model",
            "created_at",
        ):
            assert key in metadata, f"缺少元数据字段 {key}"
        assert all(value is not None for value in metadata.values())
        assert chunk.chunk_id == f"doc_test_000002:{metadata['chunk_index']}"
        assert metadata["filename"] == "01_员工手册.pdf"
        assert metadata["char_count"] == len(chunk.content)


def test_xlsx_chunks_respect_row_limit():
    """Excel 切片行数不超过 EXCEL_ROWS_PER_CHUNK，且保留工作表与行号（ADR-07）"""
    doc = load_document(SAMPLES / "03_报销制度与费用标准.xlsx")
    chunks = split_document(doc, "doc_test_000003")
    assert chunks
    for chunk in chunks:
        metadata = chunk.metadata
        assert metadata.get("sheet_name")
        if metadata.get("row_start") is not None and metadata.get("row_end") is not None:
            span = metadata["row_end"] - metadata["row_start"] + 1
            assert span <= settings.EXCEL_ROWS_PER_CHUNK


def test_short_blocks_are_merged():
    """过短段落应与相邻块合并（避免半句话入库）"""
    blocks = [
        Block(text="年假：", row_start=1, row_end=1),
        Block(text="入职满 1 年每年 5 天，满 10 年 10 天，满 20 年 15 天。", row_start=2, row_end=2),
    ]
    doc = ParsedDocument(filename="短段落.txt", file_type="txt", blocks=blocks)
    chunks = split_document(doc, "doc_test_000004")
    assert len(chunks) == 1
    assert "年假" in chunks[0].content and "15 天" in chunks[0].content
