# day02 —— 多轮对话 + System Prompt（第2天课程代码）

## 今日要点

| 主题 | 说明 | 代码位置 |
| :--- | :--- | :--- |
| 对话历史管理 | 多 Session 隔离、按轮数截断（保留最近 N 轮） | `core/conversation.py` |
| System Prompt | 定义角色、回复风格、服务范围、禁止行为 | `prompts/system_prompts.py` |
| 多轮对话接口 | 同一 `session_id` 自动携带历史上下文 | `main.py` |
| 会话重置 | `POST /api/chat/reset` 清空指定会话历史 | `main.py` |

## 运行

```powershell
# 仓库根目录执行
uvicorn day02.main:app --reload --port 8002
```

## 验收（与第1天对比）

| 操作 | 请求 | 期望 |
| :--- | :--- | :--- |
| 自我介绍 | `POST /api/chat` `{"message": "你好，我叫小明", "session_id": "user001"}` | 正常回复 |
| 记忆测试 | `POST /api/chat` `{"message": "我叫什么名字？", "session_id": "user001"}` | 记得"小明" |
| 会话隔离 | `{"message": "我叫什么名字？", "session_id": "user002"}` | 新会话，不记得 |
| 重置 | `POST /api/chat/reset?session_id=user001` | 历史清空，再问不记得 |

> 提示：历史轮数由 `.env` 的 `MAX_HISTORY` 控制（默认 3 轮）。
