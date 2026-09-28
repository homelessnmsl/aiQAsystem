# day05 —— 配置集中管理 + 项目整合（第1周课程收官）

## 今日要点

| 主题 | 说明 | 代码位置 |
| :--- | :--- | :--- |
| 配置集中管理 | `.env → config`，其他模块统一 `from .config import config` | `config.py` |
| 完整工程结构 | core / services / tools / prompts / frontend 分层 | 见目录 |
| CORS 与健康检查 | 前端跨域访问、`/health` 状态灯 | `main.py` |
| 一周功能整合 | 多轮对话 + 工具调用 + 流式输出 + Streamlit | `main.py` + `frontend/` |

## 运行（两个终端）

```powershell
# 终端 1（仓库根目录）：启动后端
uvicorn day05.main:app --reload --port 8005

# 终端 2（仓库根目录）：启动前端
streamlit run day05/frontend/streamlit_app.py
```

## 第1周课程总结（day01 ~ day05）

| 天 | 主题 | 关键产出 |
| :--- | :--- | :--- |
| day01 | FastAPI 入门 + DeepSeek 接入 | 路由 / 参数 / Pydantic / 统一响应 / 基类 / `/api/chat` |
| day02 | 多轮对话 + Prompt | ConversationManager、System Prompt |
| day03 | Function Calling | 工具 Schema、Agent 执行器、tool_calls 透出 |
| day04 | 流式输出 + Streamlit | SSE `/api/chat/stream`、逐字显示界面 |
| day05 | 配置管理 + 整合 | config.py、CORS、健康检查、完整工程结构 |

> 团队项目（企业知识库问答系统）的正式后端骨架见仓库 `app/` 目录（接口契约：`docs/接口文档.md`）。
