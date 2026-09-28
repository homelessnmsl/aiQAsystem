# prompts/ —— Prompt 模板（PE 主责，第1周交付 W1-15）

| 文件（建议） | 用途 | 关联需求 |
| :--- | :--- | :--- |
| `system_chat.md` | `/api/chat` 的系统提示词 | UC-11 |
| `system_rag.md` | RAG 问答系统提示词（含"只依据上下文回答、无法回答时明确说明"约束） | FR-QA-04 |
| `answer_template.md` | 答案格式约束（≤200 字、要点式、结论后附 `[n]` 编号） | FR-CIT-01、M-02 |
| `README.md`（本文件） | 模板说明、变量占位符、版本与迭代记录 | W1-15 |

约定：
- 变量占位符统一 `${context}`、`${question}`、`${history}`（由 `app/services/rag.py` 注入）；
- 编号上下文 `[1]~[5]` 由**程序**生成（架构设计 6.8），Prompt 中只声明"只能引用给定编号"；
- 每次修改 Prompt 必须在本文件记录版本与改动原因，供 PE 评测对比（M-01~M-04）。
