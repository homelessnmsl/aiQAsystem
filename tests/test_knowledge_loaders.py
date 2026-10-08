"""W2-02 解析器验收测试（M-06：10 份样例文档解析成功率 100%）

离线测试：不联网、不加载向量模型。
"""
from pathlib import Path

import pytest

from app.core.errors import (
    CODE_FILE_TYPE_UNSUPPORTED,
    CODE_PARSE_FAILED,
    BizError,
)
from app.knowledge.loaders.registry import SUPPORTED_EXTENSIONS, load_document

SAMPLES = Path(__file__).resolve().parent / "sample_docs"


def _sample_files() -> list[Path]:
    """tests/sample_docs 下所有白名单格式文件（RA W1-08 交付）"""
    return sorted(
        path
        for path in SAMPLES.iterdir()
        if path.is_file() and path.suffix.lower() in SUPPORTED_EXTENSIONS
    )


def test_sample_docs_exist():
    """样例数据必须齐备（覆盖 5 种格式）"""
    files = _sample_files()
    assert len(files) >= 10, f"样例文档不足：{len(files)}"
    assert {p.suffix.lower() for p in files} >= {".pdf", ".docx", ".xlsx", ".txt", ".md"}


@pytest.mark.parametrize("path", _sample_files(), ids=lambda p: p.name)
def test_parse_sample_document(path: Path):
    """每份样例都能解析出非空 Block，且块文本非空（M-06）"""
    doc = load_document(path)
    assert doc.blocks, f"{path.name} 未解析出内容"
    assert all(block.text.strip() for block in doc.blocks)


def test_pdf_has_page_numbers():
    """PDF 解析结果必须带页码（FR-CIT-02）"""
    doc = load_document(SAMPLES / "01_员工手册.pdf")
    assert doc.blocks
    assert all(block.page_no for block in doc.blocks)


def test_xlsx_has_sheet_and_rows():
    """Excel 解析结果必须带工作表名与行号（ADR-07）"""
    doc = load_document(SAMPLES / "03_报销制度与费用标准.xlsx")
    assert doc.blocks
    assert all(block.sheet_name for block in doc.blocks)
    assert all(block.row_start for block in doc.blocks)


def test_txt_has_line_numbers():
    """TXT 解析结果必须带行号"""
    doc = load_document(SAMPLES / "04_IT运维安全规范.txt")
    assert doc.blocks
    assert all(block.row_start for block in doc.blocks)


def test_markdown_has_sections():
    """Markdown 解析结果应带章节路径（section）"""
    doc = load_document(SAMPLES / "05_常见问题FAQ.md")
    assert any(block.section for block in doc.blocks)


def test_unsupported_extension_rejected():
    """白名单外的扩展名 → 1002（FR-SEC-03）"""
    with pytest.raises(BizError) as excinfo:
        load_document(SAMPLES / "runner.exe")
    assert excinfo.value.code == CODE_FILE_TYPE_UNSUPPORTED


def test_broken_pdf_raises_parse_error(tmp_path: Path):
    """损坏 PDF → 2002 中文错误，不影响服务（FR-DOC-04）"""
    broken = tmp_path / "broken.pdf"
    broken.write_bytes(b"%PDF-1.4 not a real pdf content")
    with pytest.raises(BizError) as excinfo:
        load_document(broken)
    assert excinfo.value.code == CODE_PARSE_FAILED
    assert "broken.pdf" in excinfo.value.message
