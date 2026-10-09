"""工具函数与 Agent 执行器离线测试（课程代码 day05；无需 API Key）

运行（仓库根目录）：
    python -m pytest tests/test_tools_offline.py
"""
from day05.core.agent_executor import AgentExecutor
from day05.core.conversation import ConversationManager
from day05.tools.tools import (
    TOOLS_MAP,
    TOOLS_SCHEMA,
    check_delivery,
    get_product_info,
    query_order,
    transfer_to_human,
)
from fakes import FakeResponse, FakeToolCall, ScriptedLLM


def test_tools_schema_and_map():
    assert set(TOOLS_MAP) == {"query_order", "get_product_info", "check_delivery", "transfer_to_human"}
    assert len(TOOLS_SCHEMA) == 4
    for tool in TOOLS_SCHEMA:
        assert tool["type"] == "function"
        assert "name" in tool["function"]
        assert "parameters" in tool["function"]


def test_query_order():
    assert query_order("ord001")["status"] == "已发货"
    assert query_order("ORD999")["success"] is False


def test_get_product_info_fuzzy():
    assert get_product_info("iphone 15 pro")["price"] == 7999
    assert get_product_info("小米 14")["name"] == "小米 14"
    assert get_product_info("没有这个产品")["success"] is False


def test_check_delivery():
    assert check_delivery("ORD002")["carrier"] == "圆通"
    assert check_delivery("ORD999")["success"] is False


def test_transfer_to_human():
    assert "转接" in transfer_to_human("technical")["message"]
    assert transfer_to_human("unknown")["agent_type"] == "unknown"


def test_conversation_manager_limit():
    cm = ConversationManager(max_history=2)
    for i in range(1, 4):
        cm.add_message("s1", "user", f"u{i}")
        cm.add_message("s1", "assistant", f"a{i}")
    # max_history=2 → 只保留最近 2 轮（4 条）
    assert cm.get_history_length("s1") == 4
    assert cm.get_history("s1")[0]["content"] == "u2"
    cm.clear_session("s1")
    assert cm.get_history_length("s1") == 0
    assert cm.get_session_count() == 1


def test_agent_execute_tool():
    ex = AgentExecutor(
        llm=None,
        conversation_manager=ConversationManager(),
        tools_schema=TOOLS_SCHEMA,
        tools_map=TOOLS_MAP,
        system_prompt="x",
    )
    assert ex._execute_tool("query_order", '{"order_id": "ORD003"}')["status"] == "已完成"
    assert "error" in ex._execute_tool("query_order", "{bad json}")
    assert "error" in ex._execute_tool("不存在的工具", "{}")
    assert "error" in ex._execute_tool("query_order", '{"wrong_arg": 1}')


def test_agent_run_with_tool_call():
    first_round = FakeResponse(tool_calls=[FakeToolCall("query_order", '{"order_id": "ORD001"}')])
    first_round.choices[0].message.reasoning_content = "用户要查订单，先调用 query_order。"  # 模拟 v4-pro 思维链
    scripted = ScriptedLLM([
        first_round,
        FakeResponse(content="订单ORD001已发货 ✅"),
    ])
    cm = ConversationManager(max_history=3)
    ex = AgentExecutor(
        llm=scripted,
        conversation_manager=cm,
        tools_schema=TOOLS_SCHEMA,
        tools_map=TOOLS_MAP,
        system_prompt="测试",
    )
    result = ex.run(session_id="tool_case", user_message="查一下订单ORD001")
    assert result["reply"] == "订单ORD001已发货 ✅"
    assert result["tool_calls"][0]["tool"] == "query_order"
    assert result["tool_calls"][0]["result"]["status"] == "已发货"
    # 工具结果已回填给模型（第二轮 messages 中含 role=tool 的消息）
    second_round_messages = scripted.chat_with_tools_calls[1]["messages"]
    roles = [m["role"] if isinstance(m, dict) else getattr(m, "role", None) for m in second_round_messages]
    assert "tool" in roles
    # 回传的助手消息已清洗：不含 reasoning_content，且 tool_calls 为规范结构（推理模型兼容）
    assistant_entries = [m for m in second_round_messages if isinstance(m, dict) and m.get("role") == "assistant"]
    assert assistant_entries, "第二轮应包含清洗后的 assistant 消息"
    assert "reasoning_content" not in assistant_entries[0]
    assert assistant_entries[0]["tool_calls"][0]["function"]["name"] == "query_order"
    assert assistant_entries[0]["tool_calls"][0]["id"] == "call_001"


def test_agent_stream_run_with_tool_call():
    first_round = FakeResponse(tool_calls=[FakeToolCall("get_product_info", '{"product_name": "iPhone 15 Pro"}')])
    first_round.choices[0].message.reasoning_content = "先查产品价格再回答。"
    scripted = ScriptedLLM([
        first_round,
    ])
    scripted.reply = "iPhone 15 Pro 售价 7999 元"
    ex = AgentExecutor(
        llm=scripted,
        conversation_manager=ConversationManager(),
        tools_schema=TOOLS_SCHEMA,
        tools_map=TOOLS_MAP,
        system_prompt="测试",
    )
    chunks = list(ex.stream_run(session_id="stream_case", user_message="iPhone 15 Pro 多少钱"))
    assert "".join(chunks) == "iPhone 15 Pro 售价 7999 元"
    # 流式第二轮同样清洗：stream_chat 收到的消息中 assistant 条目不含思维链
    stream_messages = scripted.stream_chat_calls[0]["messages"]
    assistant_entries = [m for m in stream_messages if isinstance(m, dict) and m.get("role") == "assistant"]
    assert assistant_entries, "流式第二轮应包含清洗后的 assistant 消息"
    assert "reasoning_content" not in assistant_entries[0]
