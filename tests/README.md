# tests/ —— 测试与数据

| 内容 | 说明 | 主责 | 状态 |
| :--- | :--- | :--- | :--- |
| `sample_docs/` | 10 份多格式示例企业文档 + 生成脚本 | RA | RA 分支已交付（W1-08） |
| `qa_dataset_v1.json` | 20 条评测集（简单 8 / 中等 9 / 困难 3；含 ≥4 条无答案兜底） | PE | 第1周（W1-16） |
| `test_splitter.py` | 切片逻辑单测（长度、重叠、元数据、Excel 行数上限） | AD | ✅ 第2周 |
| `test_knowledge_loaders.py` | 五格式解析与错误码（M-06、FR-DOC-04） | AD | ✅ 第2周 |
| `test_retrieval_offline.py` | 检索/阈值/引用结构（假 Embedding，不联网） | AD | ✅ 第2周 |
| `test_api_smoke.py` | 接口冒烟（统一响应、错误码、上传/问答主链路） | DEV | 第2周 |
| `test_retriever.py` | 检索与阈值单测 | DEV | 第3周 |

运行：`pytest -q`；接口冒烟前需先启动后端服务（`uvicorn app.main:app`）。
