"""DeepSeek 适配器（第1周汇总版）"""
import os
from typing import Iterator

from openai import OpenAI

from .base import BaseLLM

DEFAULT_BASE_URL = "https://api.deepseek.com/v1"


class DeepSeekAdapter(BaseLLM):
    """DeepSeek 大模型适配器：同步 / 工具调用 / 流式 三种能力"""

    def __init__(self, api_key: str, model: str = "deepseek-chat", base_url: str | None = None):
        self.model = model
        self.client = OpenAI(
            api_key=api_key,
            base_url=base_url or os.getenv("BASE_URL", DEFAULT_BASE_URL),
        )

    def chat(self, messages: list, stream: bool = False, **kwargs):
        """同步对话接口"""
        return self.client.chat.completions.create(model=self.model, messages=messages, stream=stream, **kwargs)

    def chat_with_tools(self, messages: list, tools: list, **kwargs):
        """带工具调用的对话接口"""
        return self.client.chat.completions.create(model=self.model, messages=messages, tools=tools, **kwargs)

    def stream_chat(self, messages: list, **kwargs) -> Iterator[str]:
        """流式对话：逐块产出内容片段"""
        response = self.client.chat.completions.create(model=self.model, messages=messages, stream=True, **kwargs)
        for chunk in response:
            if chunk.choices and chunk.choices[0].delta.content:
                yield chunk.choices[0].delta.content
