"""离线测试用的假对象（不发起真实网络请求）

- FakeLLM：app 骨架用（chat 返回 LLMResult，stream_chat 逐字产出）
- FakeResponse / FakeToolCall / ScriptedLLM：课程代码 day03~day05 的 Agent 测试用
"""
from types import SimpleNamespace
from typing import Iterator


class FakeLLM:
    """app 骨架用假模型：chat 返回 LLMResult，stream_chat 逐字产出"""

    def __init__(self, reply: str = "您好，我是离线测试助手。"):
        from app.services.llm import LLMResult, UsageInfo  # 延迟导入，避免循环依赖

        self.reply = reply
        self.calls = []
        self._LLMResult = LLMResult
        self._UsageInfo = UsageInfo

    def chat(self, messages, temperature=None, max_tokens=None, **kwargs):
        self.calls.append({
            "method": "chat",
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
        })
        return self._LLMResult(
            content=self.reply,
            model="deepseek-chat",
            usage=self._UsageInfo(prompt_tokens=12, completion_tokens=8, total_tokens=20),
        )

    def stream_chat(self, messages, temperature=None, max_tokens=None, **kwargs) -> Iterator[str]:
        self.calls.append({"method": "stream_chat", "messages": messages})
        for ch in self.reply:
            yield ch


# ============================================================
# 课程代码（day03~day05）Agent 测试用
# ============================================================
class FakeMessage:
    """模拟 choices[0].message"""

    def __init__(self, content: str = "", tool_calls=None):
        self.content = content
        self.tool_calls = tool_calls


class FakeChoice:
    def __init__(self, message: FakeMessage):
        self.message = message


class FakeResponse:
    """模拟 OpenAI/DeepSeek 响应对象：response.choices[0].message"""

    def __init__(self, content: str = "", tool_calls=None):
        self.choices = [FakeChoice(FakeMessage(content, tool_calls))]


class FakeToolCall:
    """模拟模型返回的工具调用请求"""

    def __init__(self, name: str, arguments: str, call_id: str = "call_001"):
        self.id = call_id
        self.function = SimpleNamespace(name=name, arguments=arguments)


class CourseLLM:
    """课程代码（day01~day05）用假模型：返回 FakeResponse（choices[0].message.content）"""

    def __init__(self, reply: str = "您好，这是离线测试回复。"):
        self.reply = reply
        self.calls = []

    def chat(self, messages, stream=False, **kwargs):
        self.calls.append({"method": "chat", "messages": messages, "kwargs": kwargs})
        return FakeResponse(content=self.reply)

    def chat_with_tools(self, messages, tools=None, **kwargs):
        self.calls.append({"method": "chat_with_tools", "messages": messages, "tools": tools, "kwargs": kwargs})
        return FakeResponse(content=self.reply)

    def stream_chat(self, messages, **kwargs):
        for ch in self.reply:
            yield ch


class ScriptedChatLLM(FakeLLM):
    """按脚本依次回复的假模型（多轮改写场景：改写与生成共用一个客户端）

    脚本元素为字符串（正常回复）或 Exception 实例（抛出）。
    """

    def __init__(self, replies):
        super().__init__()
        self.replies = list(replies)

    def chat(self, messages, temperature=None, max_tokens=None, **kwargs):
        self.calls.append({
            "method": "chat",
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
        })
        reply = self.replies.pop(0) if self.replies else "（脚本已用尽）"
        if isinstance(reply, Exception):
            raise reply
        return self._LLMResult(content=reply, model="deepseek-chat", usage=self._UsageInfo(1, 2, 3))


class ScriptedLLM:
    """按脚本依次返回响应的假模型（用于 Function Calling 链路测试）"""

    def __init__(self, responses):
        self._responses = list(responses)
        self.reply = "这是离线测试回复。"
        self.chat_with_tools_calls = []
        self.stream_chat_calls = []

    def chat_with_tools(self, messages, tools=None, **kwargs):
        self.chat_with_tools_calls.append({"messages": list(messages), "tools": tools, "kwargs": kwargs})
        if self._responses:
            return self._responses.pop(0)
        return FakeResponse(content="(脚本已用尽)")

    def stream_chat(self, messages, **kwargs):
        self.stream_chat_calls.append({"messages": list(messages), "kwargs": kwargs})
        for ch in self.reply:
            yield ch
