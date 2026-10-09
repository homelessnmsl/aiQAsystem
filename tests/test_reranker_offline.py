"""W3 Rerank 离线单测（假打分模型：不下载模型、不联网）"""
from app.services import reranker
from app.services.reranker import rerank


class FakeCrossEncoder:
    """按关键词命中打分，并记录调用参数"""

    def __init__(self, keyword: str = "年假"):
        self.keyword = keyword
        self.calls = []

    def predict(self, pairs):
        self.calls.append(list(pairs))
        return [1.0 if self.keyword in passage else 0.0 for _query, passage in pairs]


def _hits():
    return [
        {"chunk_id": "doc:0", "content": "公司食堂开放时间说明", "score": 0.62, "metadata": {}},
        {"chunk_id": "doc:1", "content": "年假标准：每年 5 天", "score": 0.58, "metadata": {}},
    ]


def test_rerank_reorders_and_adds_score():
    """重排后按 rerank 分数降序，并写入 rerank_score"""
    ranked = rerank("年假有多少天？", _hits(), model=FakeCrossEncoder("年假"))
    assert [item["chunk_id"] for item in ranked] == ["doc:1", "doc:0"]
    assert ranked[0]["rerank_score"] == 1.0
    assert ranked[1]["rerank_score"] == 0.0


def test_rerank_does_not_mutate_input():
    """不得修改入参（调用方可能还要用原始向量序）"""
    hits = _hits()
    snapshot = [dict(item) for item in hits]
    rerank("年假", hits, model=FakeCrossEncoder("年假"))
    assert hits == snapshot


def test_rerank_top_k_truncates():
    ranked = rerank("年假", _hits(), top_k=1, model=FakeCrossEncoder("年假"))
    assert len(ranked) == 1 and ranked[0]["chunk_id"] == "doc:1"


def test_rerank_graceful_when_model_missing(monkeypatch):
    """模型不可用时原样返回（保证 /api/ask 不受影响）"""
    monkeypatch.setattr(reranker, "_load_model", lambda: None)
    hits = _hits()
    assert rerank("年假", hits) == hits


def test_rerank_graceful_when_predict_fails():
    """推理异常时保留向量排序"""
    class Broken:
        def predict(self, pairs):
            raise RuntimeError("boom")

    ranked = rerank("年假", _hits(), model=Broken())
    assert [item["chunk_id"] for item in ranked] == ["doc:0", "doc:1"]
