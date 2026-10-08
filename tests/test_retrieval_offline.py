"""W2-04 检索服务离线测试（假 Embedding：不联网、不下载模型）

覆盖：召回排序 / 阈值过滤 / 引用结构 / 上下文格式 / 重排开关缺省行为。
"""
from pathlib import Path

import pytest

from app.core.errors import CODE_INVALID_QUESTION, BizError
from app.knowledge.loaders.base import Block, ParsedDocument
from app.knowledge.splitter import split_document
from app.knowledge.store import VectorStore
from app.services.retrieval import build_citations, build_context, retrieve

#: 假向量的语义维度：命中关键词为 1，否则 0；最后一位为常量偏置（避免零向量）
KEYWORDS = ["年假", "报销", "食堂"]


class FakeEmbedding:
    """确定性关键词向量（dim=4），用于离线验证检索链路"""

    model_name = "fake-embedding"
    dim = len(KEYWORDS) + 1

    def _vector(self, text: str) -> list[float]:
        values = [1.0 if keyword in text else 0.0 for keyword in KEYWORDS]
        values.append(0.1)
        return values

    def embed_documents(self, texts):
        return [self._vector(text) for text in texts]

    def embed_query(self, text: str):
        return self._vector(text)


@pytest.fixture()
def provider() -> FakeEmbedding:
    return FakeEmbedding()


@pytest.fixture()
def store(tmp_path: Path) -> VectorStore:
    return VectorStore(path=tmp_path / "chroma", collection="test_kb")


def _add(store: VectorStore, provider: FakeEmbedding, filename: str, page_no: int, text: str, doc_id: str) -> None:
    """把一段文本切片入库（模拟 ingest_file 的解析→切片→向量化→写入）"""
    doc = ParsedDocument(filename=filename, file_type="pdf", blocks=[Block(text=text, page_no=page_no)])
    chunks = split_document(doc, doc_id)
    store.add_chunks(chunks, provider.embed_documents([c.content for c in chunks]))


def test_retrieve_returns_best_match_with_citation(store: VectorStore, provider: FakeEmbedding):
    """问题命中正确文档，且引用位置/上下文格式符合接口文档 2.6"""
    _add(store, provider, "01_员工手册.pdf", 3, "年假：入职满 1 年不满 10 年每年 5 天年假。", "doc_20261008_000001")
    _add(store, provider, "03_报销制度与费用标准.xlsx", 2, "报销：出差住宿标准每晚上限 500 元。", "doc_20261008_000002")

    chunks = retrieve("年假有多少天？", provider=provider, store=store, top_k=2, score_threshold=0.5, retrieve_k=10)

    assert chunks, "应召回年假相关切片"
    top = chunks[0]
    assert top.source_file == "01_员工手册.pdf"
    assert top.location == "第 3 页"
    assert top.doc_id == "doc_20261008_000001"

    context = build_context(chunks)
    assert context.startswith("[1] 来源：01_员工手册.pdf")
    assert "年假" in context

    citations = build_citations(chunks)
    assert citations[0]["index"] == 1
    assert citations[0]["location"] == "第 3 页"
    assert {"doc_id", "source_file", "location", "snippet", "score", "rerank_score", "chunk_id"} <= set(citations[0])


def test_threshold_filters_unrelated_question(store: VectorStore, provider: FakeEmbedding):
    """问题与知识库无关时返回空（DEV 据此走 not_found 兜底，FR-QA-04）"""
    _add(store, provider, "01_员工手册.pdf", 3, "年假：每年 5 天。", "doc_20261008_000003")

    chunks = retrieve("公司食堂几点开饭？", provider=provider, store=store, score_threshold=0.5)
    assert chunks == []


def test_empty_question_raises_biz_error(store: VectorStore, provider: FakeEmbedding):
    """空问题 → 1004（接口文档 1.4，FR-QA-07）"""
    with pytest.raises(BizError) as excinfo:
        retrieve("   ", provider=provider, store=store)
    assert excinfo.value.code == CODE_INVALID_QUESTION


def test_rerank_flag_is_safe_before_week3(store: VectorStore, provider: FakeEmbedding):
    """第3周模块未就绪时 use_rerank=True 自动跳过，不影响主链路（架构 6.8）"""
    _add(store, provider, "01_员工手册.pdf", 3, "年假：每年 5 天。", "doc_20261008_000004")
    chunks = retrieve("年假", provider=provider, store=store, use_rerank=True, score_threshold=0.5)
    assert chunks, "跳过重排后仍应有召回结果"
