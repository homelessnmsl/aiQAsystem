# app/ —— 后端（FastAPI）

- 主责：**DEV**（AD 定结构与接口契约）
- 规范依据：`docs/架构设计.md` 第 3.2（分层规则）、第 4 章（模块划分）；字段契约见 `docs/接口文档.md`

| 目录 | 职责 | 主责 | 交付周 |
| :--- | :--- | :--- | :--- |
| `api/` | 路由、参数校验、响应封装 | DEV | 第1周（chat）~ 第3周 |
| `core/` | 配置、统一响应、错误码、日志 | DEV（AD 定规范） | 第1周 |
| `models/` | Pydantic 请求/响应模型 | DEV（AD 定契约） | 第1~3周 |
| `services/` | RAG 编排、LLM/Embedding/Rerank 适配器、SQLite 仓储 | DEV + AD | 第1~3周 |
| `knowledge/` | 文档解析、切片、向量库（**AD 主责**） | AD | 第2~3周 |
| `main.py` | 应用入口（当前为占位，W1-13 由 DEV 扩展） | DEV | 第1周 |

**依赖铁律**：`api → services → knowledge / core`，禁止反向 import（架构设计 3.2）。

启动：`python -m uvicorn app.main:app --reload --port 8000`（Swagger: http://127.0.0.1:8000/docs）
