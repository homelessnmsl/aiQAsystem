"""大模型抽象基类（第1天 7.2.1）

抽象基类定义了统一的接口规范，所有具体模型适配器都必须遵守。
业务代码只依赖 BaseLLM，不关心底层用的是 DeepSeek、通义千问还是其它模型。
"""
from abc import ABC, abstractmethod


class BaseLLM(ABC):
    """大模型抽象基类"""

    @abstractmethod
    def chat(self, messages: list, stream: bool = False, **kwargs):
        """
        同步对话接口

        Args:
            messages: 对话消息列表 [{"role": "user", "content": "你好"}]
            stream: 是否流式输出（第4天课程使用）
            **kwargs: 其他参数（temperature 等）

        Returns:
            模型响应对象
        """
        pass
