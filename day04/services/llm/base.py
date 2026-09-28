"""大模型抽象基类（第4天：新增 stream_chat 流式方法）"""
from abc import ABC, abstractmethod
from typing import Iterator


class BaseLLM(ABC):
    """大模型抽象基类：统一接口规范"""

    @abstractmethod
    def chat(self, messages: list, stream: bool = False, **kwargs):
        """同步对话接口"""
        pass

    @abstractmethod
    def chat_with_tools(self, messages: list, tools: list, **kwargs):
        """带工具调用的对话接口（Function Calling）"""
        pass

    @abstractmethod
    def stream_chat(self, messages: list, **kwargs) -> Iterator[str]:
        """流式对话接口：逐块返回内容片段"""
        pass
