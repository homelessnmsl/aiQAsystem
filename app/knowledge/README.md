# app/knowledge/ —— 知识库层（AD 主责，第2周交付）

施工图：`docs/架构设计.md` 第 6 章（解析 → 切片 → 元数据 → 向量库）。

| 文件/目录 | 职责 | 交付 |
| :--- | :--- | :--- |
| `loaders/` | 五格式解析（pdf/docx/xlsx/txt/md），统一输出 `ParsedDocument`（含页码/工作表/行号） | 第2周（10-09） |
| `splitter.py` | 结构化切片 300~600 字、重叠 10%~20%、表格重复表头 | 第2周（10-09） |
| `metadata.py` | `doc_id` 生成、元数据规范、`format_location()` 引用位置文本 | 第2周（10-09） |
| `store.py` | Chroma 封装：`add / query / delete_by_doc / list / count`，`PersistentClient` 持久化 | 第2周（10-09） |

**本层为纯 Python，可单独单测**（`tests/test_splitter.py` 等）；不得 import `services` / `api`；不依赖 FastAPI。

验收口径（M-06）：`tests/sample_docs/` 10 份文档全部解析成功、元数据完整、重启服务后仍可检索。
