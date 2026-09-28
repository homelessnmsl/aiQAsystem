# day04 —— 流式输出（SSE）+ Streamlit 前端（第4天课程代码）

## 今日要点

| 主题 | 说明 | 代码位置 |
| :--- | :--- | :--- |
| SSE 流式接口 | `POST /api/chat/stream` 逐块返回 `data: {"content","done"}` | `main.py` |
| 流式执行链 | 先判断工具 → 执行工具 → 逐块生成回复 | `core/agent_executor.py`（`stream_run`） |
| 流式适配器 | `stream=True` 调用 DeepSeek 并逐块产出 | `services/llm/deepseek_adapter.py` |
| Streamlit 前端 | 类 ChatGPT 界面，逐字显示回复、会话重置、状态灯 | `frontend/streamlit_app.py` |

## 运行（两个终端）

```powershell
# 终端 1（仓库根目录）：启动后端
uvicorn day04.main:app --reload --port 8004

# 终端 2（仓库根目录）：启动前端
streamlit run day04/frontend/streamlit_app.py
```

浏览器打开 http://localhost:8501 ，提问"帮我查一下订单ORD001"，回复应逐字出现。

## 验收

- [ ] Swagger 中调用 `POST /api/chat/stream`，响应为 `text/event-stream`
- [ ] 前端对话界面上，AI 回复逐字显示（非一次性弹出）
- [ ] 流式对话同样支持工具调用（"订单ORD002的物流到哪了？"）
