# scripts/ —— 运维与评测脚本

| 脚本 | 用途 | 主责 | 交付周 |
| :--- | :--- | :--- | :--- |
| `init_kb.py` | 批量导入 `tests/sample_docs/` 建库 | AD | 第2周 |
| `build_kb.py` | 重建向量库（`--rebuild` 清空后全量重导入） | AD | 第2周 |
| `eval_rag.py` | 跑 20 条评测集，输出 M-01~M-04 与逐条明细 | PE | 第2~3周 |
| `run_all.py` | 一键启动前后端（答辩演示、M-07 首次可用时间） | DEV | 第2周 |

运行示例：`python scripts/init_kb.py`（需先 `pip install -r requirements.txt` 并配置 `.env`）
