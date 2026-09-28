"""大模型抽象基类（第3天：新增 chat_with_tools 方法）"""
from abc import ABC, abstractmethod


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
