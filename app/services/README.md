# app/services/ —— 业务编排层

- 主责：**DEV**（`llm.py` / `rag.py` / `repository.py`），**AD**（`embedding.py` / `reranker.py` / `retriever.py`）

| 文件 | 职责 | 关键约定 | 交付周 |
| :--- | :--- | :--- | :--- |
| `llm.py` | `BaseLLM` + `DeepSeekClient` | 超时 60s、重试 1 次、Key 脱敏；见接口文档 2.2 | 第1周（W1-14）✅ |
| `ingestion.py` | `ingest_file()` / `ingest_paths()`：解析→切片→向量化→入库（AD） | 逐文件失败隔离（FR-DOC-04）；供 /api/upload 复用 | 第2周 ✅ |
| `retrieval.py` | `retrieve()` / `build_context()` / `build_citations()`（AD） | 接口文档 2.6：召回 20 → 阈值 0.485 → Top-K 5 | 第2周 ✅ |
| `reranker.py` | `rerank()`：bge-reranker-base 精排（AD） | 失败自动降级；**默认关闭**（A/B 数据见架构 6.8），可一键开启 | 第3周 ✅（预研） |
| `embedding.py` | Embedding 适配器（local / 在线） | 归一化、维度校验、批处理、LRU 缓存；见架构设计 6.7 | 第2周 |
| `retriever.py` | 召回 → 阈值 → （重排）→ 上下文拼装 | 参数 `RETRIEVE_K=20 / TOP_K=5 / SCORE_THRESHOLD=0.35`；见 6.8 | 第2~3周 |
| `reranker.py` | Rerank 适配器（可开关） | `RERANK_ENABLED` 控制，供 A/B 对比（FR-QA-03） | 第3周 |
| `rag.py` | RAG 主链路：检索 → 生成 → 引用装配 | 引用由程序生成（ADR-06）；`answer_type` 三态 | 第2周 |
| `repository.py` | SQLite DAO（documents/conversations/messages/feedback） | 表结构见架构设计 7.2 | 第2周 |

规则：本层不出现 FastAPI 的 `Request`/`Response` 对象；对外抛 `BizError(code)`（`app/core/errors.py`）。
