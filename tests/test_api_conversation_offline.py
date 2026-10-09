"""会话与反馈接口离线测试（接口文档 2.7~2.10；独立 SQLite 台账）"""
import json

import pytest
from fastapi.testclient import TestClient

import app.main as app_main
from app.services.conversation import conversation_store
from app.services.repository import Repository

_CITATION = {
    "index": 1,
    "doc_id": "doc_1",
    "source_file": "01_员工手册.pdf",
    "location": "第 3 页",
    "snippet": "……5 天年假……",
    "score": 0.7231,
    "rerank_score": None,
    "chunk_id": "doc_1:0",
}


@pytest.fixture()
def client():
    return TestClient(app_main.app, raise_server_exceptions=False)


@pytest.fixture()
def temp_repo(tmp_path, monkeypatch):
    repo = Repository(path=tmp_path / "app.db")
    monkeypatch.setattr("app.api.conversation.get_repository", lambda: repo)
    return repo


def _seed(repo: Repository):
    repo.ensure_conversation("conv_1", title="公司年假有多少天？")
    repo.add_message(message_id="msg_u1", session_id="conv_1", role="user", content="公司年假有多少天？",
                     trace_id="tr_1", created_at="2026-10-08T20:15:00+08:00")
    repo.add_message(message_id="msg_a1", session_id="conv_1", role="assistant", content="每年 5 天 [1]。",
                     citations=json.dumps([_CITATION], ensure_ascii=False), trace_id="tr_1", latency_ms=900,
                     created_at="2026-10-08T20:15:05+08:00")
    repo.ensure_conversation("conv_2", title="公司食堂几点开饭？")
    repo.add_message(message_id="msg_u2", session_id="conv_2", role="user", content="公司食堂几点开饭？",
                     created_at="2026-10-08T21:00:00+08:00")


def test_list_conversations(client, temp_repo):
    _seed(temp_repo)
    body = client.get("/api/conversations").json()
    assert body["code"] == 0
    data = body["data"]
    assert data["total"] == 2 and data["page"] == 1 and data["page_size"] == 20
    by_id = {item["session_id"]: item for item in data["items"]}
    assert by_id["conv_1"]["message_count"] == 2
    assert by_id["conv_2"]["message_count"] == 1
    for key in ("session_id", "title", "message_count", "created_at", "updated_at"):
        assert key in by_id["conv_1"]

    filtered = client.get("/api/conversations", params={"keyword": "年假"}).json()["data"]
    assert filtered["total"] == 1 and filtered["items"][0]["session_id"] == "conv_1"
    assert client.get("/api/conversations", params={"keyword": "不存在"}).json()["data"]["total"] == 0


def test_conversation_detail(client, temp_repo):
    _seed(temp_repo)
    body = client.get("/api/conversations/conv_1").json()
    assert body["code"] == 0
    data = body["data"]
    assert data["session_id"] == "conv_1" and data["title"] == "公司年假有多少天？"
    assert [message["role"] for message in data["messages"]] == ["user", "assistant"]

    user_message, assistant_message = data["messages"]
    assert user_message["trace_id"] is None and user_message["citations"] is None
    assert assistant_message["trace_id"] == "tr_1"
    assert assistant_message["citations"][0]["index"] == 1
    assert assistant_message["citations"][0]["source_file"] == "01_员工手册.pdf"
    assert assistant_message["created_at"] == "2026-10-08T20:15:05+08:00"


def test_conversation_detail_unknown(client, temp_repo):
    resp = client.get("/api/conversations/conv_missing")
    assert resp.status_code == 404
    assert resp.json()["code"] == 1005
    assert "会话不存在" in resp.json()["message"]


def test_clear_conversation(client, temp_repo):
    _seed(temp_repo)
    conversation_store.append("conv_1", "user", "旧上下文")  # 模拟进程内上下文

    resp = client.delete("/api/conversations/conv_1")
    body = resp.json()
    assert body["code"] == 0
    assert body["data"] == {"session_id": "conv_1", "deleted_messages": 2}
    assert temp_repo.list_messages("conv_1") == []
    assert conversation_store.history("conv_1") == []  # 内存上下文同步清空

    detail = client.get("/api/conversations/conv_1").json()["data"]
    assert detail["messages"] == []  # 会话行保留，消息为空

    # 幂等：再次清空返回 0
    assert client.delete("/api/conversations/conv_1").json()["data"]["deleted_messages"] == 0


def test_feedback_ok(client, temp_repo):
    _seed(temp_repo)
    resp = client.post("/api/feedback", json={
        "message_id": "msg_a1", "session_id": "conv_1", "rating": "down", "comment": "没有给出天数",
    })
    body = resp.json()
    assert resp.status_code == 200 and body["code"] == 0
    assert body["message"] == "感谢反馈"
    assert body["data"]["feedback_id"].startswith("fb_")
    assert body["data"]["created_at"].endswith("+08:00")

    count = temp_repo._conn.execute("SELECT COUNT(*) FROM feedback").fetchone()[0]
    assert count == 1
    row = temp_repo._conn.execute("SELECT * FROM feedback").fetchone()
    assert row["rating"] == "down" and row["comment"] == "没有给出天数"


def test_feedback_invalid(client, temp_repo):
    _seed(temp_repo)
    resp = client.post("/api/feedback", json={
        "message_id": "msg_a1", "session_id": "conv_1", "rating": "meh",
    })
    assert resp.status_code == 400 and resp.json()["code"] == 1001
    assert resp.json()["data"]["errors"][0]["reason"] == "rating 只能为 up / down"

    resp = client.post("/api/feedback", json={
        "message_id": "msg_a1", "session_id": "conv_1", "rating": "up", "comment": "长" * 201,
    })
    assert resp.status_code == 400 and resp.json()["code"] == 1001

    resp = client.post("/api/feedback", json={
        "message_id": "msg_missing", "session_id": "conv_1", "rating": "up",
    })
    assert resp.status_code == 404 and resp.json()["code"] == 1005
    assert "消息不存在" in resp.json()["message"]

    resp = client.post("/api/feedback", json={"session_id": "conv_1", "rating": "up"})
    assert resp.status_code == 400 and resp.json()["code"] == 1001
