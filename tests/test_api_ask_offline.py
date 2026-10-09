"""POST /api/ask 离线测试（stub 检索与 LLM，不发起真实调用）"""
import json

import pytest
from fastapi.testclient import TestClient

import app.main as app_main
from app.services.repository import Repository
from app.services.retrieval import RetrievedChunk
from fakes import FakeLLM, ScriptedChatLLM


@pytest.fixture()
def client():
    return TestClient(app_main.app, raise_server_exceptions=False)


@pytest.fixture()
def temp_repo(tmp_path, monkeypatch):
    repo = Repository(path=tmp_path / "app.db")
    monkeypatch.setattr("app.services.rag.get_repository", lambda: repo)
    return repo


def _chunk(rank=1, score=0.72, content="年假：入职满 1 年不满 10 年的员工，每年享有 5 天年假。",
           location="第 3 页", source="01_员工手册.pdf", doc_id="doc_1"):
    return RetrievedChunk(
        rank=rank, chunk_id=f"{doc_id}:{rank - 1}", doc_id=doc_id, source_file=source,
        location=location, content=content, score=score,
    )


def _patch_retrieval(monkeypatch, raw, effective):
    def fake_retrieve(question, *, top_k=None, score_threshold=None, doc_ids=None, use_rerank=None,
                      provider=None, store=None, retrieve_k=None):
        return list(raw), list(effective)

    monkeypatch.setattr("app.services.rag.retrieve_with_raw", fake_retrieve)
    monkeypatch.setattr("app.services.rag.knowledge_is_empty", lambda store=None: False)


def _patch_llm(monkeypatch, reply="根据《员工手册》，满 1 年不满 10 年每年 5 天年假 [1]。"):
    fake = FakeLLM(reply=reply)
    monkeypatch.setattr("app.services.rag.get_llm_client", lambda: fake)
    monkeypatch.setattr(app_main.settings, "DEEPSEEK_API_KEY", "sk-test-offline")
    return fake


def test_ask_answered(client, temp_repo, monkeypatch):
    good = _chunk(rank=1, score=0.72)
    low = _chunk(rank=2, score=0.30, doc_id="doc_9", source="10_公司简介.md", location="章节「2 组织架构」")
    _patch_retrieval(monkeypatch, raw=[good, low], effective=[good])
    fake_llm = _patch_llm(monkeypatch)

    resp = client.post("/api/ask", json={"question": "公司年假有多少天？"})
    body = resp.json()
    assert resp.status_code == 200 and body["code"] == 0
    data = body["data"]

    assert data["trace_id"].startswith("tr_") and data["session_id"].startswith("conv_")
    assert data["message_id"].startswith("msg_")
    assert data["question"] == "公司年假有多少天？"
    assert data["answer_type"] == "answered"
    assert data["rewritten_question"] is None

    assert data["citations"][0]["index"] == 1
    assert data["citations"][0]["source_file"] == "01_员工手册.pdf"
    assert data["citations"][0]["location"] == "第 3 页"
    assert data["citations"][0]["chunk_id"] == "doc_1:0"
    assert data["retrieved"][0]["rank"] == 1 and len(data["retrieved"]) == 2

    assert data["model"] == "deepseek-chat"
    assert data["usage"]["total_tokens"] == 20
    assert set(data["latency_ms"]) == {"total", "retrieval", "rerank", "generation"}
    assert data["created_at"].endswith("+08:00")

    # Prompt：PE 模板渲染（system + user），且已包含检索片段与问题
    sent = fake_llm.calls[0]["messages"]
    assert sent[0]["role"] == "system"
    assert "检索片段" in sent[1]["content"] and "公司年假有多少天？" in sent[1]["content"]
    assert "[1] 来源：01_员工手册.pdf" in sent[1]["content"]
    assert "${" not in sent[1]["content"]

    # 落库：user + assistant 两条消息，assistant 含 citations JSON
    messages = temp_repo.list_messages(data["session_id"])
    assert [m["role"] for m in messages] == ["user", "assistant"]
    citations = json.loads(messages[1]["citations"])
    assert citations[0]["index"] == 1 and messages[1]["trace_id"] == data["trace_id"]


def test_ask_not_found(client, temp_repo, monkeypatch):
    low = _chunk(rank=1, score=0.28, doc_id="doc_9", source="10_公司简介.md", location="章节「2 组织架构」")
    _patch_retrieval(monkeypatch, raw=[low], effective=[])
    fake_llm = _patch_llm(monkeypatch)

    resp = client.post("/api/ask", json={"question": "公司食堂几点开饭？"})
    body = resp.json()
    assert resp.status_code == 200 and body["code"] == 0
    data = body["data"]
    assert data["answer_type"] == "not_found"
    assert data["citations"] == []
    assert data["retrieved"][0]["score"] == 0.28  # 明细仍返回（PE 统计需要）
    assert "未在企业知识库中找到相关依据" in data["answer"]
    assert data["model"] is None and data["usage"] is None
    assert data["latency_ms"]["generation"] == 0
    assert fake_llm.calls == []  # not_found 不调用 LLM


def test_ask_citations_only_referenced(client, temp_repo, monkeypatch):
    """citations 只包含答案里实际引用的 [n]（架构 6.9）"""
    first = _chunk(rank=1, score=0.72)
    second = _chunk(rank=2, score=0.68, doc_id="doc_2", source="08_考勤与假期管理规定.txt", location="第 12~18 行")
    third = _chunk(rank=3, score=0.60, doc_id="doc_3", source="05_常见问题FAQ.md", location="章节「4. 如何申请 VPN 权限？」")
    _patch_retrieval(monkeypatch, raw=[first, second, third], effective=[first, second, third])
    _patch_llm(monkeypatch, reply="年假为 5 天 [1]，转正后按比例折算 [2]。")

    body = client.post("/api/ask", json={"question": "年假多少天？"}).json()
    data = body["data"]
    assert data["answer_type"] == "answered"
    assert [c["index"] for c in data["citations"]] == [1, 2]
    assert data["citations"][1]["source_file"] == "08_考勤与假期管理规定.txt"
    assert len(data["retrieved"]) == 3  # 明细仍返回原始 Top-K


def test_ask_downgrade_when_no_citation_marks(client, temp_repo, monkeypatch):
    """模型未用任何 [n] → 降级 not_found，model/usage 为 null（架构 6.9 / 接口文档 2.6）"""
    good = _chunk(rank=1, score=0.72)
    _patch_retrieval(monkeypatch, raw=[good], effective=[good])
    _patch_llm(monkeypatch, reply="年假大概是五天吧，具体可以问 HR。")

    body = client.post("/api/ask", json={"question": "年假多少天？"}).json()
    data = body["data"]
    assert data["answer_type"] == "not_found"
    assert data["answer"] == "抱歉，未在企业知识库中找到相关依据。您可以换个说法提问，或联系管理员补充相关文档。"
    assert data["citations"] == []
    assert data["model"] is None and data["usage"] is None


def test_ask_kb_empty(client, temp_repo, monkeypatch):
    monkeypatch.setattr("app.services.rag.knowledge_is_empty", lambda store=None: True)
    resp = client.post("/api/ask", json={"question": "年假多少天？"})
    assert resp.status_code == 409
    assert resp.json()["code"] == 2001
    assert "知识库为空" in resp.json()["message"]


def test_ask_empty_question(client, temp_repo, monkeypatch):
    _patch_retrieval(monkeypatch, raw=[], effective=[])
    resp = client.post("/api/ask", json={"question": ""})
    assert resp.status_code == 400
    body = resp.json()
    assert body["code"] == 1004
    assert body["message"] == "问题不能为空"
    assert body["data"]["errors"][0]["field"] == "question"


def test_ask_question_too_long(client, temp_repo, monkeypatch):
    _patch_retrieval(monkeypatch, raw=[], effective=[])
    resp = client.post("/api/ask", json={"question": "问" * 600})
    assert resp.status_code == 400
    assert resp.json()["code"] == 1004
    assert "500 字" in resp.json()["message"]


def test_ask_invalid_params(client, temp_repo, monkeypatch):
    resp = client.post("/api/ask", json={"question": "年假？", "top_k": 99})
    assert resp.status_code == 400 and resp.json()["code"] == 1001
    assert resp.json()["data"]["errors"][0]["field"] == "top_k"
    resp = client.post("/api/ask", json={"question": "年假？", "score_threshold": 2})
    assert resp.status_code == 400 and resp.json()["data"]["errors"][0]["field"] == "score_threshold"


def test_ask_stream_not_supported(client, temp_repo, monkeypatch):
    resp = client.post("/api/ask", json={"question": "年假？", "stream": True})
    assert resp.status_code == 400
    assert resp.json()["code"] == 1001
    assert "第3周" in resp.json()["message"]


def test_ask_strips_out_of_range_marks(client, temp_repo, monkeypatch):
    good = _chunk(rank=1, score=0.72)
    _patch_retrieval(monkeypatch, raw=[good], effective=[good])
    _patch_llm(monkeypatch, reply="年假 5 天 [1]，详情见 [3] 号文件。")
    body = client.post("/api/ask", json={"question": "年假多少天？"}).json()
    assert body["data"]["answer"] == "年假 5 天 [1]，详情见  号文件。"


def test_ask_citations_renumbered_continuous(client, temp_repo, monkeypatch):
    """D2-02 方案B：模型引用 [1][3]（不连续）→ 对外答案与 citations 重排为连续 [1][2]。"""
    c1 = _chunk(rank=1, score=0.72, doc_id="doc_1", source="01_员工手册.pdf", location="第 3 页",
                content="年假：满 1 年不满 10 年每年 5 天。")
    c2 = _chunk(rank=2, score=0.61, doc_id="doc_3", source="03_报销制度.xlsx", location="工作表「差旅标准」第 2~4 行",
                content="出差住宿标准：一线城市 400 元/晚。")
    c3 = _chunk(rank=3, score=0.55, doc_id="doc_3", source="03_报销制度.xlsx", location="工作表「差旅标准」第 5~8 行",
                content="出差餐补：100 元/天。")
    _patch_retrieval(monkeypatch, raw=[c1, c2, c3], effective=[c1, c2, c3])
    _patch_llm(monkeypatch, reply="年假每年 5 天 [1]；出差住宿一线城市 400 元/晚 [3]。")

    resp = client.post("/api/ask", json={"question": "年假和出差住宿标准各是多少？"})
    body = resp.json()
    data = body["data"]

    assert data["answer_type"] == "answered"
    # 答案编号连续化：[1][3] → [1][2]
    assert "[1]" in data["answer"] and "[2]" in data["answer"] and "[3]" not in data["answer"]
    # citations 同步重排：2 条、编号 1/2、溯源字段保留原值
    assert [c["index"] for c in data["citations"]] == [1, 2]
    assert data["citations"][0]["source_file"] == "01_员工手册.pdf"
    assert data["citations"][1]["chunk_id"] == "doc_3:2"
    assert data["citations"][1]["location"] == "工作表「差旅标准」第 5~8 行"
# ============ 多轮改写（架构 8.2 ①、FR-QA-05） ============
def test_multiturn_rewrite_applied(client, temp_repo, monkeypatch):
    """有历史时先改写问题，再用改写后的问题检索；无历史不改写"""
    from app.services.conversation import conversation_store

    good = _chunk(rank=1, score=0.72)
    seen = {}

    def fake_retrieve(question, **kwargs):
        seen["question"] = question
        return [good], [good]

    monkeypatch.setattr("app.services.rag.retrieve_with_raw", fake_retrieve)
    monkeypatch.setattr("app.services.rag.knowledge_is_empty", lambda store=None: False)
    scripted = ScriptedChatLLM([
        "试用期为 3 个月 [1]。",
        "转正后的年假天数是多少？",
        "转正后当年度年假按剩余天数折算 [1]。",
    ])
    monkeypatch.setattr("app.services.rag.get_llm_client", lambda: scripted)
    monkeypatch.setattr(app_main.settings, "DEEPSEEK_API_KEY", "sk-test-offline")

    session_id = "conv_pytest_multiturn"
    conversation_store.clear(session_id)

    first = client.post("/api/ask", json={"question": "试用期有多久？", "session_id": session_id}).json()
    assert first["data"]["answer_type"] == "answered"
    assert first["data"]["rewritten_question"] is None  # 无历史 → 不改写
    assert seen["question"] == "试用期有多久？"
    assert len(scripted.calls) == 1  # 只有生成调用

    second = client.post("/api/ask", json={"question": "那转正后呢？", "session_id": session_id}).json()
    assert second["data"]["rewritten_question"] == "转正后的年假天数是多少？"
    assert seen["question"] == "转正后的年假天数是多少？"  # 检索用的是改写后的问题
    assert len(scripted.calls) == 3  # 第一轮生成 + 第二轮改写 + 第二轮生成

    # 第二轮 Prompt 中携带历史（用户/助手 文本注入）
    second_prompt = scripted.calls[2]["messages"][1]["content"]
    assert "用户：试用期有多久？" in second_prompt
    assert "助手：试用期为 3 个月 [1]。" in second_prompt


def test_multiturn_rewrite_failure_falls_back(client, temp_repo, monkeypatch):
    """改写调用失败时降级为原文检索，主链路不受影响（异常兜底）"""
    from app.core.errors import CODE_LLM_TIMEOUT, BizError
    from app.services.conversation import conversation_store

    good = _chunk(rank=1, score=0.72)
    seen = {}

    def fake_retrieve(question, **kwargs):
        seen["question"] = question
        return [good], [good]

    monkeypatch.setattr("app.services.rag.retrieve_with_raw", fake_retrieve)
    monkeypatch.setattr("app.services.rag.knowledge_is_empty", lambda store=None: False)
    scripted = ScriptedChatLLM([
        "试用期为 3 个月 [1]。",
        BizError(CODE_LLM_TIMEOUT, "回答生成超时，请稍后重试"),
        "转正后年假按比例折算 [1]。",
    ])
    monkeypatch.setattr("app.services.rag.get_llm_client", lambda: scripted)
    monkeypatch.setattr(app_main.settings, "DEEPSEEK_API_KEY", "sk-test-offline")

    session_id = "conv_pytest_rewrite_fallback"
    conversation_store.clear(session_id)
    client.post("/api/ask", json={"question": "试用期有多久？", "session_id": session_id})

    second = client.post("/api/ask", json={"question": "那之后呢？", "session_id": session_id}).json()
    assert second["code"] == 0
    assert second["data"]["answer_type"] == "answered"
    assert second["data"]["rewritten_question"] is None  # 改写失败 → 未改写
    assert seen["question"] == "那之后呢？"  # 降级用原文检索
