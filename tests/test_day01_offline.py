"""day01 课程代码离线测试（不调用真实 DeepSeek API）

运行（仓库根目录）：
    python -m pytest tests/test_day01_offline.py
"""
import pytest
from fastapi.testclient import TestClient

import day01.main as day01_main
from fakes import CourseLLM


@pytest.fixture()
def client():
    return TestClient(day01_main.app, raise_server_exceptions=False)


@pytest.fixture()
def fake_llm(monkeypatch):
    fake = CourseLLM(reply="您好，这是离线测试回复。")
    monkeypatch.setattr(day01_main, "llm", fake)
    return fake


# ============ 基础路由（练习1 / 练习2） ============
def test_root(client):
    resp = client.get("/")
    body = resp.json()
    assert resp.status_code == 200
    assert body["code"] == 0
    assert body["data"]["message"] == "智能客服系统运行中"


def test_hello(client):
    body = client.get("/hello/张三").json()
    assert body["code"] == 0
    assert body["data"]["message"] == "你好，张三！"


def test_get_user_ok(client):
    body = client.get("/user/42").json()
    assert body["code"] == 0
    assert body["data"]["user_id"] == 42


def test_get_user_invalid(client):
    resp = client.get("/user/0")
    assert resp.status_code == 400
    assert resp.json()["code"] == 400
    assert "用户ID" in resp.json()["message"]


def test_get_user_not_found(client):
    resp = client.get("/user/101")
    assert resp.status_code == 404
    assert resp.json()["code"] == 404


def test_get_user_type_error(client):
    resp = client.get("/user/abc")
    assert resp.status_code == 400
    assert resp.json()["code"] == 400
    assert resp.json()["message"] == "请求参数校验失败"


def test_products(client):
    body = client.get("/products", params={"category": "手机", "page": 2}).json()
    assert body["data"] == {"category": "手机", "page": 2, "items": []}


def test_chat_query(client):
    body = client.get("/chat", params={"q": "你好"}).json()
    assert body["data"]["question"] == "你好"
    assert body["data"]["page"] == 1


# ============ 请求体相关（练习3 / 练习5） ============
def test_echo(client):
    body = client.post("/echo", json={"message": "你好"}).json()
    assert body["data"]["reply"] == "你说的是：你好"


def test_api_echo(client):
    body = client.post("/api/echo", json={"message": "hi"}).json()
    assert body["data"]["echo"] == "你说了：hi"


def test_say_default_name(client):
    body = client.post("/api/say", json={"content": "你好"}).json()
    assert body["data"]["reply"] == "匿名说：你好"


def test_say_custom_name(client):
    body = client.post("/api/say", json={"content": "你好", "user_name": "张三"}).json()
    assert body["data"]["reply"] == "张三说：你好"


# ============ 作业1：用户注册接口 ============
def test_register_ok(client):
    resp = client.post("/api/register", json={
        "username": "zhangsan", "password": "123456", "email": "test@qq.com",
    })
    body = resp.json()
    assert resp.status_code == 200 and body["code"] == 0
    assert body["data"] == {"user_id": 1, "username": "zhangsan"}


def test_register_bad_email(client):
    resp = client.post("/api/register", json={
        "username": "zhangsan", "password": "123456", "email": "test",
    })
    assert resp.status_code == 400
    assert resp.json()["code"] == 400


def test_register_short_username(client):
    resp = client.post("/api/register", json={
        "username": "ab", "password": "123456", "email": "test@qq.com",
    })
    assert resp.status_code == 400
    assert resp.json()["code"] == 400


# ============ 作业2：获取用户信息接口 ============
def test_user_info_ok(client):
    body = client.get("/api/user/1").json()
    assert body["code"] == 0
    assert body["data"]["id"] == 1
    assert body["data"]["email"] == "user1@test.com"


def test_user_info_invalid(client):
    resp = client.get("/api/user/0")
    assert resp.status_code == 400
    assert resp.json() == {"code": 400, "message": "用户ID无效", "data": None}


# ============ 练习7 + 作业3：/api/chat ============
def test_chat_success(client, fake_llm):
    resp = client.post("/api/chat", json={"message": "你好", "session_id": "s1"})
    body = resp.json()
    assert resp.status_code == 200 and body["code"] == 0
    assert body["data"]["reply"] == "您好，这是离线测试回复。"
    assert body["data"]["session_id"] == "s1"
    # 校验发给模型的消息结构
    sent = fake_llm.calls[0]["messages"]
    assert sent[0]["role"] == "system"
    assert sent[-1] == {"role": "user", "content": "你好"}


def test_chat_empty_message(client, fake_llm):
    resp = client.post("/api/chat", json={"message": ""})
    assert resp.status_code == 400
    assert resp.json()["code"] == 400
    assert resp.json()["message"] == "消息内容不能为空"


def test_chat_temperature_out_of_range(client, fake_llm):
    resp = client.post("/api/chat", json={"message": "你好", "temperature": 2.5})
    assert resp.status_code == 400
    assert resp.json()["message"] == "temperature参数必须在0-2之间"


def test_chat_without_llm(client, monkeypatch):
    monkeypatch.setattr(day01_main, "llm", None)
    resp = client.post("/api/chat", json={"message": "你好"})
    assert resp.status_code == 500
    assert "大模型未初始化" in resp.json()["message"]
