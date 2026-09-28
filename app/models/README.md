# app/models/ —— Pydantic 模型

- 主责：DEV（AD 定契约）　｜　契约：`docs/接口文档.md` 第 3 章（数据模型对照表，逐字段对齐）

命名约定（与接口文档一致）：

| 模型类 | 用途 |
| :--- | :--- |
| `ChatRequest` / `ChatResponse` | `/api/chat` |
| `AskRequest` / `AskResponse` / `Citation` / `RetrievedChunk` | `/api/ask` |
| `UploadItem` / `UploadResult` | `/api/upload` |
| `DocumentItem` / `PageData` | `/api/documents` 等列表 |
| `FeedbackRequest` / `ConversationData` | 第3周会话与反馈 |

规则：字段名、类型、可空性、默认值逐字对齐接口文档；空值返回 `null`（不返回空字符串）；时间统一 ISO8601（+08:00）。
