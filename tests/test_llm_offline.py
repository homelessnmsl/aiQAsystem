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


def _response(
    content: str = "你好",
    model: str = "deepseek-chat",
    *,
    finish_reason: str = "stop",
    reasoning: str | None = None,
):
    """构造一个 OpenAI 风格的响应对象（可选携带推理模型的 reasoning_content）"""
    message = SimpleNamespace(content=content, tool_calls=None)
    if reasoning is not None:
        message.reasoning_content = reasoning  # 模拟 deepseek-v4-pro 的思维链字段
    usage = SimpleNamespace(prompt_tokens=1, completion_tokens=2, total_tokens=3)
    choice = SimpleNamespace(message=message, finish_reason=finish_reason)
    return SimpleNamespace(choices=[choice], model=model, usage=usage)


def _delta_chunk(content: str | None = None, reasoning: str | None = None):
    """构造一个流式分片（delta 携带正文或思维链）"""
    delta = SimpleNamespace(content=content, reasoning_content=reasoning)
    return SimpleNamespace(choices=[SimpleNamespace(delta=delta)])


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


# ============ 推理模型（reasoning_content）兼容 ============
def test_chat_with_reasoning_content(monkeypatch):
    """推理模型返回 reasoning_content：只取正文，思维链不外泄"""
    client, _ = _make_client(
        [_response("收到", reasoning="我们需要回答两个字：收到。")],
        monkeypatch=monkeypatch,
    )
    result = client.chat([{"role": "user", "content": "请只回复两个字：收到"}])
    assert result.content == "收到"


def test_chat_reasoning_consumed_budget(monkeypatch):
    """思维链耗尽 max_tokens：content 为空且 finish_reason=length → 3004，提示被截断"""
    client, _ = _make_client(
        [_response("", finish_reason="length", reasoning="我们需要回答用户中文问题……")],
        monkeypatch=monkeypatch,
    )
    with pytest.raises(BizError) as exc_info:
        client.chat([{"role": "user", "content": "问题"}])
    assert exc_info.value.code == CODE_LLM_BAD_RESPONSE
    assert "截断" in exc_info.value.message


def test_stream_chat_skips_reasoning(monkeypatch):
    """流式：思维链分片全部跳过，只下发正文"""
    chunks = [
        _delta_chunk(reasoning="先想一下…"),
        _delta_chunk(reasoning="继续想…"),
        _delta_chunk(content="您"),
        _delta_chunk(content="好"),
    ]
    client, _ = _make_client([chunks], monkeypatch=monkeypatch)
    assert list(client.stream_chat([{"role": "user", "content": "hi"}])) == ["您", "好"]


def test_stream_chat_only_reasoning_raises(monkeypatch):
    """流式：整条流只有思维链（预算被耗尽）→ 抛 3004，而不是产出空回答"""
    chunks = [_delta_chunk(reasoning="想了很多"), _delta_chunk(reasoning="还是没写完")]
    client, _ = _make_client([chunks], monkeypatch=monkeypatch)
    with pytest.raises(BizError) as exc_info:
        list(client.stream_chat([{"role": "user", "content": "hi"}]))
    assert exc_info.value.code == CODE_LLM_BAD_RESPONSE
