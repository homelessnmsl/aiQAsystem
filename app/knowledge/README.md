# app/knowledge/ —— 知识库层（AD 主责）

施工图：`docs/架构设计.md` 第 6 章（解析 → 切片 → 元数据 → 向量库）。**第2周已交付（2026-10-08）**。

| 文件/目录 | 职责 | 状态 |
| :--- | :--- | :--- |
| `loaders/` | 五格式解析（pdf/docx/xlsx/txt/md），统一输出 `ParsedDocument`（含页码/工作表/行号） | ✅ W2-02 |
| `splitter.py` | 结构化切片：500/80、短块合并到 300 字、Excel ≤20 行/块、元数据装配 | ✅ W2-03 |
| `metadata.py` | `doc_id` 生成、文件名安全处理（NFR-S-02）、`format_location()` 引用位置文本 | ✅ W2-03 |
| `store.py` | Chroma 封装：`add_chunks / query / delete_by_doc / count / reset`（PersistentClient） | ✅ W2-03 |

**编排与调用（在 services 层，DEV 的 /api/upload、/api/ask 直接复用）**
- `app/services/ingestion.py`：`ingest_file()` / `ingest_paths()`（解析→切片→向量化→入库，逐文件失败隔离）
- `app/services/retrieval.py`：`retrieve()` / `build_context()` / `build_citations()`（W2-04）
- `app/services/embedding.py`：Embedding 适配器（本地 bge-small-zh / 在线 OpenAI 兼容）

**命令行验收（2026-10-08 实测）**
```bash
python scripts/init_kb.py --rebuild        # 10 份样例全部入库 → 31 个切片，0 失败
python scripts/query_kb.py "公司年假有多少天？" --context
```

**模型下载（重要）**：部分网络无法直连 huggingface.co，sentence-transformers 自动下载会失败：
```bash
python scripts/download_model.py           # 从 ModelScope（魔搭）下载到 ~/.cache/aiqasystem/models/
# 然后在 .env 设置（Windows 路径用正斜杠）：
# EMBEDDING_MODEL=C:/Users/HP/.cache/aiqasystem/models/bge-small-zh-v1.5
```

**实测指标（2026-10-08，20 条评测集检索侧）**：Recall@5 = 15/15 = 100%；
越界问题 top1 最高 0.479、正确来源最低 0.490 → `SCORE_THRESHOLD=0.485`（ADR-08）。

**本层规则**：纯 Python、可单独单测；不得 import `services` / `api`；不依赖 FastAPI。
