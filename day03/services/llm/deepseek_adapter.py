"""DeepSeek 适配器（第3天：新增 chat_with_tools 实现）"""
import os

from openai import OpenAI

from .base import BaseLLM

DEFAULT_BASE_URL = "https://api.deepseek.com/v1"


class DeepSeekAdapter(BaseLLM):
    """DeepSeek 大模型适配器"""

    def __init__(self, api_key: str, model: str = "deepseek-chat", base_url: str | None = None):
        self.model = model
        self.client = OpenAI(
            api_key=api_key,
            base_url=base_url or os.getenv("BASE_URL", DEFAULT_BASE_URL),
        )

    def chat(self, messages: list, stream: bool = False, **kwargs):
        """同步对话接口"""
        return self.client.chat.completions.create(
            model=self.model,
            messages=messages,
            stream=stream,
            **kwargs,
        )

    def chat_with_tools(self, messages: list, tools: list, **kwargs):
        """带工具调用的对话接口：模型会返回 tool_calls（需要执行的工具）"""
        return self.client.chat.completions.create(
            model=self.model,
            messages=messages,
            tools=tools,
            **kwargs,
        )
