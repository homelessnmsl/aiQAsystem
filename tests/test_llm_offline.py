"""DeepSeekClient 错误码映射测试（对齐接口文档 1.4；不发起真实网络请求）

运行（仓库根目录）：
    python -m pytest tests/test_llm_offline.py
"""
from types import SimpleNamespace

import httpx
import pytest
from openai import APIStatusError, APITimeoutError, RateLimitError

from app.core.errors import (
    CODE_LLM_BAD_RESPONSE,
    CODE_LLM_NO_KEY,
    CODE_LLM_RATE_LIMIT,
    CODE_LLM_TIMEOUT,
    BizError,
)
from app.services.llm import DeepSeekClient


def _response(content: str = "你好", model: str = "deepseek-chat"):
    """构造一个 OpenAI 风格的响应对象"""
    message = SimpleNamespace(content=content, tool_calls=None)
    usage = SimpleNamespace(prompt_tokens=1, completion_tokens=2, total_tokens=3)
    return SimpleNamespace(choices=[SimpleNamespace(message=message)], model=model, usage=usage)


class _FakeCompletions:
    def __init__(self, effects):
        self._effects = list(effects)
        self.calls = 0

    def create(self, **kwargs):
        self.calls += 1
        effect = self._effects.pop(0)
        if isinstance(effect, Exception):
            raise effect
        return effect


def _make_client(effects, max_retries: int = 1, monkeypatch=None):
    """组装 DeepSeekClient，并把 OpenAI 调用替换为脚本化的假实现"""
    if monkeypatch is not None:
        monkeypatch.setattr("app.services.llm.time.sleep", lambda _seconds: None)
    client = DeepSeekClient(
        api_key="sk-test-offline",
        base_url="https://api.deepseek.com",
        model="deepseek-chat",
        max_retries=max_retries,
    )
    completions = _FakeCompletions(effects)
    client.client = SimpleNamespace(chat=SimpleNamespace(completions=completions))
    return client, completions


def _request():
    return httpx.Request("POST", "https://api.deepseek.com/chat/completions")


def test_chat_success(monkeypatch):
    client, completions = _make_client([_response("你好呀")], monkeypatch=monkeypatch)
    result = client.chat([{"role": "user", "content": "你好"}])
    assert result.content == "你好呀"
    assert result.model == "deepseek-chat"
    assert result.usage.total_tokens == 3
    assert completions.calls == 1


def test_chat_timeout_retry_then_success(monkeypatch):
    """超时重试 1 次后成功（NFR-R-02）"""
    effects = [APITimeoutError(request=_request()), _response("重试成功")]
    client, completions = _make_client(effects, max_retries=1, monkeypatch=monkeypatch)
    result = client.chat([{"role": "user", "content": "你好"}])
    assert result.content == "重试成功"
    assert completions.calls == 2


def test_chat_timeout_exhausted(monkeypatch):
    """连续超时 → BizError(3001)"""
    effects = [APITimeoutError(request=_request()), APITimeoutError(request=_request())]
    client, _ = _make_client(effects, max_retries=1, monkeypatch=monkeypatch)
    with pytest.raises(BizError) as exc_info:
        client.chat([{"role": "user", "content": "你好"}])
    assert exc_info.value.code == CODE_LLM_TIMEOUT


def test_chat_rate_limit(monkeypatch):
    response_429 = httpx.Response(429, request=_request())
    effects = [RateLimitError("rate limited", response=response_429, body=None)]
    client, _ = _make_client(effects, monkeypatch=monkeypatch)
    with pytest.raises(BizError) as exc_info:
        client.chat([{"role": "user", "content": "你好"}])
    assert exc_info.value.code == CODE_LLM_RATE_LIMIT


def test_chat_invalid_key(monkeypatch):
    response_401 = httpx.Response(401, request=_request())
    effects = [APIStatusError("unauthorized", response=response_401, body=None)]
    client, _ = _make_client(effects, monkeypatch=monkeypatch)
    with pytest.raises(BizError) as exc_info:
        client.chat([{"role": "user", "content": "你好"}])
    assert exc_info.value.code == CODE_LLM_NO_KEY


def test_chat_empty_content(monkeypatch):
    client, _ = _make_client([_response("")], monkeypatch=monkeypatch)
    with pytest.raises(BizError) as exc_info:
        client.chat([{"role": "user", "content": "你好"}])
    assert exc_info.value.code == CODE_LLM_BAD_RESPONSE


def test_client_without_key():
    with pytest.raises(BizError) as exc_info:
        DeepSeekClient(api_key="")
    assert exc_info.value.code == CODE_LLM_NO_KEY
