"""LLM 服务：BaseLLM 抽象基类 + DeepSeekClient 实现（接口文档 2.2；架构 4.2；W1-14）

- 统一异常出口：超时 3001 / 限流 3002 / 未配置或无效密钥 3003 / 返回异常 3004（接口文档 1.4）；
- 超时 LLM_TIMEOUT_SECONDS、重试 LLM_MAX_RETRIES（NFR-R-02）；
- 日志中 Key 脱敏为 sk-****（NFR-S-01）。
"""
import logging
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Dict, Iterator, List

from openai import APIError, APIConnectionError, APIStatusError, APITimeoutError, OpenAI, RateLimitError

from ..core.config import settings
from ..core.errors import (
    CODE_LLM_BAD_RESPONSE,
    CODE_LLM_NO_KEY,
    CODE_LLM_RATE_LIMIT,
    CODE_LLM_TIMEOUT,
    BizError,
)
from ..core.logging import mask_key

logger = logging.getLogger(__name__)


@dataclass
class UsageInfo:
    """Token 用量（对齐接口文档 Usage 模型）"""

    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0


@dataclass
class LLMResult:
    """一次对话的完整结果"""

    content: str
    model: str
    usage: UsageInfo = field(default_factory=UsageInfo)


def _to_biz_error(exc: Exception) -> BizError:
    """把 OpenAI SDK 异常翻译成接口文档定义的 BizError（1.4 错误码）"""
    if isinstance(exc, (APITimeoutError, APIConnectionError)):
        return BizError(CODE_LLM_TIMEOUT, "回答生成超时，请稍后重试")
    if isinstance(exc, RateLimitError):
        return BizError(CODE_LLM_RATE_LIMIT, "模型服务繁忙，请稍后重试")
    if isinstance(exc, APIStatusError):
        if exc.status_code in (401, 403):
            return BizError(CODE_LLM_NO_KEY, "模型密钥无效或未授权，请检查 .env 配置")
        if exc.status_code in (402, 429):
            return BizError(CODE_LLM_RATE_LIMIT, "模型服务繁忙，请稍后重试")
    return BizError(CODE_LLM_BAD_RESPONSE, "回答生成异常，请重试")


class BaseLLM(ABC):
    """大模型抽象基类：业务代码只依赖本接口，便于第2~4周扩展多模型"""

    @abstractmethod
    def chat(self, messages: List[Dict[str, str]], **kwargs) -> LLMResult:
        """同步对话：返回 LLMResult（内容 / 模型名 / 用量）"""
        raise NotImplementedError

    @abstractmethod
    def stream_chat(self, messages: List[Dict[str, str]], **kwargs) -> Iterator[str]:
        """流式对话：逐块产出内容片段"""
        raise NotImplementedError


class DeepSeekClient(BaseLLM):
    """DeepSeek 实现（OpenAI 兼容协议；base_url 默认 https://api.deepseek.com）"""

    def __init__(
        self,
        api_key: str | None = None,
        base_url: str | None = None,
        model: str | None = None,
        timeout: int | None = None,
        max_retries: int | None = None,
    ):
        self.api_key = (api_key if api_key is not None else settings.DEEPSEEK_API_KEY) or ""
        if not self.api_key.strip():
            raise BizError(CODE_LLM_NO_KEY, "服务未配置模型密钥，请联系管理员")

        self.base_url = base_url or settings.DEEPSEEK_BASE_URL
        self.model = model or settings.LLM_MODEL
        self.timeout = timeout or settings.LLM_TIMEOUT_SECONDS
        self.max_retries = settings.LLM_MAX_RETRIES if max_retries is None else max_retries
        self.client = OpenAI(api_key=self.api_key, base_url=self.base_url, timeout=self.timeout)
        logger.info(
            "DeepSeekClient 初始化：base_url=%s model=%s key=%s",
            self.base_url,
            self.model,
            mask_key(self.api_key),
        )

    def _request_kwargs(self, temperature: float | None, max_tokens: int | None) -> Dict:
        """合并默认参数（温度/最大 token 数，架构 9.5）"""
        return {
            "temperature": settings.LLM_TEMPERATURE if temperature is None else temperature,
            "max_tokens": max_tokens or settings.LLM_MAX_TOKENS,
        }

    def chat(
        self,
        messages: List[Dict[str, str]],
        temperature: float | None = None,
        max_tokens: int | None = None,
        **kwargs,
    ) -> LLMResult:
        """同步对话（超时/连接错误自动重试 max_retries 次）"""
        response = None
        for attempt in range(self.max_retries + 1):
            try:
                response = self.client.chat.completions.create(
                    model=self.model,
                    messages=messages,
                    **self._request_kwargs(temperature, max_tokens),
                )
                break
            except (APITimeoutError, APIConnectionError) as exc:
                if attempt < self.max_retries:
                    logger.warning("LLM 调用失败（第 %s 次尝试），1 秒后重试：%s", attempt + 1, exc)
                    time.sleep(1)
                    continue
                raise _to_biz_error(exc) from exc
            except APIError as exc:
                raise _to_biz_error(exc) from exc

        content = (response.choices[0].message.content or "").strip()
        if not content:
            raise BizError(CODE_LLM_BAD_RESPONSE, "回答生成异常，请重试")

        usage = getattr(response, "usage", None)
        return LLMResult(
            content=content,
            model=getattr(response, "model", None) or self.model,
            usage=UsageInfo(
                prompt_tokens=getattr(usage, "prompt_tokens", 0) or 0,
                completion_tokens=getattr(usage, "completion_tokens", 0) or 0,
                total_tokens=getattr(usage, "total_tokens", 0) or 0,
            ),
        )

    def stream_chat(
        self,
        messages: List[Dict[str, str]],
        temperature: float | None = None,
        max_tokens: int | None = None,
        **kwargs,
    ) -> Iterator[str]:
        """流式对话：逐块产出内容片段（异常翻译规则同 chat）"""
        try:
            stream = self.client.chat.completions.create(
                model=self.model,
                messages=messages,
                stream=True,
                **self._request_kwargs(temperature, max_tokens),
            )
            for chunk in stream:
                delta = chunk.choices[0].delta if chunk.choices else None
                if delta and delta.content:
                    yield delta.content
        except APIError as exc:
            raise _to_biz_error(exc) from exc


#: 全局 LLM 客户端（懒加载单例；调用前先判断 settings.llm_configured）
_llm_client: DeepSeekClient | None = None


def get_llm_client() -> DeepSeekClient:
    """获取全局 LLM 客户端（单例懒加载）"""
    global _llm_client
    if _llm_client is None:
        _llm_client = DeepSeekClient()
    return _llm_client
