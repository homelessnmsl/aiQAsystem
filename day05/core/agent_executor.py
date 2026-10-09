"""Agent 执行器（第3~4天内容整合：Function Calling + 流式输出）"""
import json
from typing import Any, Dict, Iterator, List

from ..services.llm import BaseLLM
from .conversation import ConversationManager


def _sanitize_assistant_message(message) -> dict:
    """把模型返回的助手消息清洗为可安全回传的规范字典。

    推理模型（如 deepseek-v4-pro）会在 message 上附带 reasoning_content（思维链）等私有字段，
    原样回传既浪费 token 也可能不被接口接受；这里只保留 role / content / tool_calls。
    """
    return {
        "role": "assistant",
        "content": message.content or "",
        "tool_calls": [
            {
                "id": tool_call.id,
                "type": "function",
                "function": {
                    "name": tool_call.function.name,
                    "arguments": tool_call.function.arguments,
                },
            }
            for tool_call in (message.tool_calls or [])
        ],
    }


class AgentExecutor:
    """Agent 执行器：编排"调用模型 → 判断工具 → 执行工具 → 生成回复"的完整循环"""

    def __init__(
        self,
        llm: BaseLLM,
        conversation_manager: ConversationManager,
        tools_schema: List[Dict],
        tools_map: Dict[str, Any],
        system_prompt: str,
    ):
        self.llm = llm
        self.conversation_manager = conversation_manager
        self.tools_schema = tools_schema
        self.tools_map = tools_map
        self.system_prompt = system_prompt

    def run(self, session_id: str, user_message: str, temperature: float = 0.7, max_tool_rounds: int = 5) -> Dict[str, Any]:
        """同步执行一轮完整对话 → {"reply", "tool_calls", "session_id"}"""
        self.conversation_manager.add_message(session_id, "user", user_message)
        history = self.conversation_manager.get_or_create_session(session_id)
        messages = [{"role": "system", "content": self.system_prompt}, *history]

        tool_calls_log: List[Dict[str, Any]] = []
        for _ in range(max_tool_rounds):
            response = self.llm.chat_with_tools(messages=messages, tools=self.tools_schema, temperature=temperature)
            message = response.choices[0].message

            if message.tool_calls:
                messages.append(_sanitize_assistant_message(message))
                for tool_call in message.tool_calls:
                    tool_name = tool_call.function.name
                    tool_args = tool_call.function.arguments
                    tool_result = self._execute_tool(tool_name, tool_args)
                    messages.append({"role": "tool", "tool_call_id": tool_call.id, "content": str(tool_result)})
                    tool_calls_log.append({"tool": tool_name, "args": tool_args, "result": tool_result})
            else:
                reply = message.content
                self.conversation_manager.add_message(session_id, "assistant", reply)
                return {"reply": reply, "tool_calls": tool_calls_log, "session_id": session_id}

        reply = "抱歉，处理您的请求时出现了超时，请稍后重试。"
        self.conversation_manager.add_message(session_id, "assistant", reply)
        return {"reply": reply, "tool_calls": tool_calls_log, "session_id": session_id}

    def stream_run(self, session_id: str, user_message: str, temperature: float = 0.7) -> Iterator[str]:
        """流式执行：先判断工具 → 执行工具 → 逐块返回最终回复"""
        self.conversation_manager.add_message(session_id, "user", user_message)
        history = self.conversation_manager.get_or_create_session(session_id)
        messages = [{"role": "system", "content": self.system_prompt}, *history]

        response = self.llm.chat_with_tools(messages=messages, tools=self.tools_schema, temperature=temperature)
        message = response.choices[0].message

        if message.tool_calls:
            messages.append(_sanitize_assistant_message(message))
            for tool_call in message.tool_calls:
                tool_name = tool_call.function.name
                tool_args = tool_call.function.arguments
                print(f"[工具调用] {tool_name}({tool_args})")
                tool_result = self._execute_tool(tool_name, tool_args)
                messages.append({"role": "tool", "tool_call_id": tool_call.id, "content": str(tool_result)})

        full_reply = ""
        for chunk in self.llm.stream_chat(messages, temperature=temperature):
            full_reply += chunk
            yield chunk
        self.conversation_manager.add_message(session_id, "assistant", full_reply)

    def _execute_tool(self, tool_name: str, args_str: str) -> Any:
        """执行工具函数（参数解析、异常兜底）"""
        tool_func = self.tools_map.get(tool_name)
        if not tool_func:
            return {"error": f"未知工具: {tool_name}"}
        try:
            return tool_func(**json.loads(args_str))
        except json.JSONDecodeError as e:
            return {"error": f"参数解析失败: {str(e)}"}
        except TypeError as e:
            return {"error": f"参数不匹配: {str(e)}"}
        except Exception as e:
            return {"error": f"工具执行异常: {str(e)}"}
