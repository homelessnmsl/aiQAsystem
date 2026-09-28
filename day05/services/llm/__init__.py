"""day05 大模型服务包：对外暴露 BaseLLM 与 DeepSeekAdapter"""
from .base import BaseLLM
from .deepseek_adapter import DeepSeekAdapter

__all__ = ["BaseLLM", "DeepSeekAdapter"]
