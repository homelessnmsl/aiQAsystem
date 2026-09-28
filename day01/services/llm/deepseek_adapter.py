"""DeepSeek 适配器（第1天 7.2.2）

DeepSeek API 完全兼容 OpenAI SDK 格式，因此直接基于 openai 包实现。
"""
import os

from openai import OpenAI

from .base import BaseLLM

DEFAULT_BASE_URL = "https://api.deepseek.com/v1"


class DeepSeekAdapter(BaseLLM):
    """DeepSeek 大模型适配器：把 DeepSeek 接入到 BaseLLM 规范"""

    def __init__(self, api_key: str, model: str = "deepseek-chat", base_url: str | None = None):
        self.model = model
        self.client = OpenAI(
            api_key=api_key,
            base_url=base_url or os.getenv("BASE_URL", DEFAULT_BASE_URL),
        )

    def chat(self, messages: list, stream: bool = False, **kwargs):
        """
        同步对话接口

        Args:
            messages: 对话消息列表 [{"role": "user", "content": "你好"}]
            stream: 是否流式输出
            **kwargs: 其他参数（temperature 等）

        Returns:
            模型响应对象（response.choices[0].message.content 即回复内容）
        """
        response = self.client.chat.completions.create(
            model=self.model,
            messages=messages,
            stream=stream,
            **kwargs,
        )
        return response
