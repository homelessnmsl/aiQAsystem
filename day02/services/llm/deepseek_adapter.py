"""DeepSeek 适配器（复习第1天 7.2.2）"""
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
        """同步对话接口（response.choices[0].message.content 即回复内容）"""
        return self.client.chat.completions.create(
            model=self.model,
            messages=messages,
            stream=stream,
            **kwargs,
        )
