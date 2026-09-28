# day03 —— Function Calling 工具调用（第3天课程代码）

## 今日要点

| 主题 | 说明 | 代码位置 |
| :--- | :--- | :--- |
| 工具定义 | JSON Schema 描述 4 个工具（订单/产品/物流/转人工） | `tools/tools.py` |
| Agent 执行器 | 调用模型 → 判断 tool_calls → 执行工具 → 回填结果 → 生成回复 | `core/agent_executor.py` |
| 工具实现 | 模拟数据库 + 宽松匹配（忽略空格/大小写） | `tools/tools.py` |
| 接口透出 | `/api/chat` 返回 `tool_calls` 调用记录，便于演示 | `main.py` |

## 运行

```powershell
# 仓库根目录执行
uvicorn day03.main:app --reload --port 8003
```

## 验收

| 提问 | 期望 |
| :--- | :--- |
| "帮我查一下订单ORD001" | 回复含订单状态（已发货），`tool_calls[0].tool = query_order` |
| "iPhone 15 Pro多少钱？" | 回复含价格 7999，工具 `get_product_info` |
| "订单ORD002的物流到哪了？" | 回复含物流信息，工具 `check_delivery` |
| "转人工客服" | 回复"正在为您转接…"，工具 `transfer_to_human` |
| "查一下订单ORD999" | 工具返回 success=false，回复如实告知"未找到"（不编造） |
