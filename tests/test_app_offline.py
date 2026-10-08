"""app 骨架离线测试：对齐 docs/接口文档.md（不调用真实 DeepSeek API）

运行（仓库根目录）：
    python -m pytest tests/test_app_offline.py
"""
import json

import pytest
from fastapi.testclient import TestClient

import app.main as app_main
from fakes import FakeLLM


@pytest.fixture()
def client():
    return TestClient(app_main.app, raise_server_exceptions=False)


@pytest.fixture()
def fake_llm(monkeypatch):
    """注入假模型：跳过密钥检查 + 替换 LLM 客户端"""
    fake = FakeLLM(reply="您好，我是离线测试助手。")
    monkeypatch.setattr(app_main.settings, "DEEPSEEK_API_KEY", "sk-test-offline")
    monkeypatch.setattr("app.api.chat.get_llm_client", lambda: fake)
    return fake


# ============ 基础路由（接口文档 1.2 / 2.1） ============
def test_root(client):
    body = client.get("/").json()
    assert body["code"] == 0
    assert body["data"]["service"] == "aiQAsystem"


def test_health(client):
    body = client.get("/api/health").json()
    assert body["code"] == 0
    data = body["data"]
    assert data["status"] in ("ok", "degraded")
    assert data["version"] == "0.1.0"
    assert data["time"].endswith("+08:00")
    deps = data["dependencies"]
    assert set(deps) == {"llm", "embedding", "vector_store", "sqlite"}
    assert deps["llm"]["status"] in ("ok", "unconfigured")
    assert deps["llm"]["model"] == "deepseek-chat"
    assert deps["embedding"]["status"] in ("ok", "error", "unconfigured")
    assert deps["vector_store"]["status"] in ("ok", "error")
    assert deps["sqlite"]["status"] in ("ok", "error")
    if deps["vector_store"]["status"] == "ok":
        assert isinstance(deps["vector_store"]["chunk_count"], int)
        assert deps["vector_store"]["collection"] == "enterprise_kb"


def test_404_unified(client):
    """未知路径也返回统一结构（接口文档 1.3）"""
    resp = client.get("/api/does-not-exist")
    assert resp.status_code == 404
    body = resp.json()
    assert body["code"] == 1005
    assert body["data"] is None


# ============ /api/chat 成功路径（接口文档 2.2 / SM-02） ============
def test_chat_success(client, fake_llm):
    resp = client.post("/api/chat", json={"message": "你好"})
    body = resp.json()
    assert resp.status_code == 200 and body["code"] == 0

    data = body["data"]
    assert data["reply"] == "您好，我是离线测试助手。"
    assert data["session_id"].startswith("conv_")
    assert data["trace_id"].startswith("tr_")
    assert data["model"] == "deepseek-chat"
    assert data["usage"] == {"prompt_tokens": 12, "completion_tokens": 8, "total_tokens": 20}
    assert isinstance(data["latency_ms"], int) and data["latency_ms"] >= 0
    assert data["created_at"].endswith("+08:00")

    # system 提示词已注入（PE 的 prompts/system_chat.md 或内置兜底）
    sent = fake_llm.calls[0]["messages"]
    assert sent[0]["role"] == "system" and sent[0]["content"]
    assert sent[-1] == {"role": "user", "content": "你好"}
    # 请求参数透传
    assert fake_llm.calls[0]["temperature"] == 0.7
    assert fake_llm.calls[0]["max_tokens"] == 1024


def test_chat_multi_turn(client, fake_llm):
    """多轮对话：同一 session_id 自动携带历史（接口文档 2.2）"""
    sid = "conv_pytest_multi_turn"
    client.post("/api/chat", json={"message": "我叫小明", "session_id": sid})
    client.post("/api/chat", json={"message": "我叫什么？", "session_id": sid})

    sent = fake_llm.calls[-1]["messages"]
    contents = [m["content"] for m in sent if isinstance(m, dict)]
    assert "我叫小明" in contents
    assert "您好，我是离线测试助手。" in contents  # 上一轮助手回复也在上下文里


def test_chat_auto_session(client, fake_llm):
    """不传 session_id 时自动新建会话，且响应返回新会话 ID"""
    body = client.post("/api/chat", json={"message": "你好"}).json()
    assert body["data"]["session_id"].startswith("conv_")


# ============ /api/chat 校验与错误（接口文档 1.4 / SM-03 / SM-04） ============
def test_chat_missing_message(client):
    resp = client.post("/api/chat", json={})
    assert resp.status_code == 400
    body = resp.json()
    assert body["code"] == 1001
    assert body["message"] == "参数校验失败"
    assert body["data"]["errors"][0]["field"] == "message"
    assert body["data"]["errors"][0]["reason"] == "消息不能为空"


def test_chat_empty_message(client):
    resp = client.post("/api/chat", json={"message": ""})
    assert resp.status_code == 400
    assert resp.json()["data"]["errors"][0]["field"] == "message"


def test_chat_temperature_out_of_range(client):
    resp = client.post("/api/chat", json={"message": "你好", "temperature": 2.5})
    assert resp.status_code == 400
    assert resp.json()["code"] == 1001
    assert resp.json()["data"]["errors"][0]["field"] == "temperature"


def test_chat_max_tokens_out_of_range(client):
    resp = client.post("/api/chat", json={"message": "你好", "max_tokens": 5000})
    assert resp.status_code == 400
    assert resp.json()["data"]["errors"][0]["field"] == "max_tokens"


def test_chat_without_key(client, monkeypatch):
    """.env 未配置 Key 时返回 3003（SM-04），不泄露 Traceback"""
    monkeypatch.setattr(app_main.settings, "DEEPSEEK_API_KEY", "")
    resp = client.post("/api/chat", json={"message": "你好"})
    assert resp.status_code == 500
    body = resp.json()
    assert body["code"] == 3003
    assert "密钥" in body["message"]
    assert "Traceback" not in resp.text


# ============ /api/chat 流式（接口文档 2.11 事件格式） ============
def test_chat_stream(client, fake_llm):
    resp = client.post("/api/chat", json={"message": "你好", "stream": True})
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("text/event-stream")

    contents, done = [], None
    for line in resp.text.splitlines():
        if line.startswith("data: "):
            event = json.loads(line[6:])
            if event["type"] == "delta":
                contents.append(event["content"])
            elif event["type"] == "done":
                done = event
    assert "".join(contents) == "您好，我是离线测试助手。"
    assert done is not None and isinstance(done["latency_ms"], int)
