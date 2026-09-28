"""Agent 执行器（第3天：Function Calling 核心）

编排"调用模型 → 判断工具 → 执行工具 → 生成回复"的完整循环。
"""
import json
from typing import Any, Dict, List

from ..services.llm import BaseLLM
from .conversation import ConversationManager


class AgentExecutor:
    """Agent 执行器：负责编排对话流程与工具调用"""

    def __init__(
        self,
        llm: BaseLLM,
        conversation_manager: ConversationManager,
        tools_schema: List[Dict],
        tools_map: Dict[str, Any],
        system_prompt: str,
    ):
        """
        Args:
            llm: 大模型适配器
            conversation_manager: 对话历史管理器
            tools_schema: 工具定义列表（告诉模型有哪些工具可用）
            tools_map: 工具名称 → 实际函数
            system_prompt: 系统提示词
        """
        self.llm = llm
        self.conversation_manager = conversation_manager
        self.tools_schema = tools_schema
        self.tools_map = tools_map
        self.system_prompt = system_prompt

    def run(
        self,
        session_id: str,
        user_message: str,
        temperature: float = 0.7,
        max_tool_rounds: int = 5,
    ) -> Dict[str, Any]:
        """
        执行一轮完整的 Agent 对话

        Returns:
            {"reply": 最终回复, "tool_calls": 工具调用记录, "session_id": 会话ID}
        """
        # 1. 保存用户消息
        self.conversation_manager.add_message(session_id, "user", user_message)

        # 2. 构造消息（system + 历史）
        history = self.conversation_manager.get_or_create_session(session_id)
        messages = [{"role": "system", "content": self.system_prompt}, *history]

        # 3. Agent 循环（最多 max_tool_rounds 轮，防止死循环）
        tool_calls_log: List[Dict[str, Any]] = []
        for _ in range(max_tool_rounds):
            response = self.llm.chat_with_tools(
                messages=messages,
                tools=self.tools_schema,
                temperature=temperature,
            )
            message = response.choices[0].message

            if message.tool_calls:
                messages.append(message)
                for tool_call in message.tool_calls:
                    tool_name = tool_call.function.name
                    tool_args = tool_call.function.arguments
                    tool_result = self._execute_tool(tool_name, tool_args)

                    messages.append({
                        "role": "tool",
                        "tool_call_id": tool_call.id,
                        "content": str(tool_result),
                    })
                    tool_calls_log.append({"tool": tool_name, "args": tool_args, "result": tool_result})
            else:
                reply = message.content
                self.conversation_manager.add_message(session_id, "assistant", reply)
                return {"reply": reply, "tool_calls": tool_calls_log, "session_id": session_id}

        reply = "抱歉，处理您的请求时出现了超时，请稍后重试。"
        self.conversation_manager.add_message(session_id, "assistant", reply)
        return {"reply": reply, "tool_calls": tool_calls_log, "session_id": session_id}

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
