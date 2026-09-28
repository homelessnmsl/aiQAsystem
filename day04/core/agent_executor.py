"""Agent 执行器（第4天：新增 stream_run 流式执行）

先判断是否需要工具 → 执行工具 → 流式返回最终回复。
"""
import json
from typing import Any, Dict, Iterator, List

from ..services.llm import BaseLLM
from .conversation import ConversationManager


class AgentExecutor:
    """Agent 执行器：编排对话流程与工具调用（同步 + 流式）"""

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

    # ========== 同步执行（第3天） ==========
    def run(self, session_id: str, user_message: str, temperature: float = 0.7, max_tool_rounds: int = 5) -> Dict[str, Any]:
        """执行一轮完整对话，返回 {"reply", "tool_calls", "session_id"}"""
        self.conversation_manager.add_message(session_id, "user", user_message)
        history = self.conversation_manager.get_or_create_session(session_id)
        messages = [{"role": "system", "content": self.system_prompt}, *history]

        tool_calls_log: List[Dict[str, Any]] = []
        for _ in range(max_tool_rounds):
            response = self.llm.chat_with_tools(messages=messages, tools=self.tools_schema, temperature=temperature)
            message = response.choices[0].message

            if message.tool_calls:
                messages.append(message)
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

    # ========== 流式执行（第4天新增） ==========
    def stream_run(self, session_id: str, user_message: str, temperature: float = 0.7) -> Iterator[str]:
        """流式执行：先判断工具 → 执行工具 → 逐块返回最终回复"""
        self.conversation_manager.add_message(session_id, "user", user_message)
        history = self.conversation_manager.get_or_create_session(session_id)
        messages = [{"role": "system", "content": self.system_prompt}, *history]

        # 1. 先判断是否需要工具（一次非流式调用，拿到 tool_calls）
        response = self.llm.chat_with_tools(messages=messages, tools=self.tools_schema, temperature=temperature)
        message = response.choices[0].message

        # 2. 如有工具调用，先执行并回填结果
        if message.tool_calls:
            messages.append(message)
            for tool_call in message.tool_calls:
                tool_name = tool_call.function.name
                tool_args = tool_call.function.arguments
                print(f"[工具调用] {tool_name}({tool_args})")
                tool_result = self._execute_tool(tool_name, tool_args)
                messages.append({"role": "tool", "tool_call_id": tool_call.id, "content": str(tool_result)})

        # 3. 流式输出最终回复（一边拼接完整回复，一边把块吐给前端）
        full_reply = ""
        for chunk in self.llm.stream_chat(messages, temperature=temperature):
            full_reply += chunk
            yield chunk

        # 4. 保存完整回复到历史
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
