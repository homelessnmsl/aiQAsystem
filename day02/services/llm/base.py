"""大模型抽象基类（复习第1天 7.2.1）"""
from abc import ABC, abstractmethod


class BaseLLM(ABC):
    """大模型抽象基类：统一接口规范，业务代码只依赖本接口"""

    @abstractmethod
    def chat(self, messages: list, stream: bool = False, **kwargs):
        """同步对话接口：返回模型响应对象"""
        pass
