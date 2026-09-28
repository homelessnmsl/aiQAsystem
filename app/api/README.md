# app/api/ —— 路由层

- 主责：DEV　｜　契约：`docs/接口文档.md`（**先改文档再改代码**）
- 原则：本层只做「参数校验 → 调 service → `ApiResponse` 封装」，不写业务逻辑、不直接碰 Chroma/SQLite。

| 文件 | 接口 | 交付周 |
| :--- | :--- | :--- |
| `chat.py` | `POST /api/chat` | 第1周（W1-14） |
| `health.py` | `GET /api/health` | 第2周（第1周可选） |
| `documents.py` | `POST /api/upload`、`GET /api/documents`、`DELETE /api/documents/{doc_id}` | 第2~3周 |
| `ask.py` | `POST /api/ask`（含流式） | 第2~3周 |
| `conversation.py` | 会话列表/详情/清空、`POST /api/feedback` | 第3周 |

错误码只允许使用接口文档 1.4 节定义过的 code；新增错误码必须先更新接口文档。
