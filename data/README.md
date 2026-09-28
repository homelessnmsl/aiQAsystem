# data/ —— 运行时数据目录（不入库，仅保留占位文件）

| 目录/文件 | 内容 | 重建方式 |
| :--- | :--- | :--- |
| `uploads/{doc_id}/` | 上传的原始文件 | 重新上传，或从备份恢复 |
| `chroma/` | Chroma 向量库持久化数据 | `python scripts/build_kb.py --rebuild`（依据 uploads 全量重建） |
| `app.db` | SQLite：文档台账 / 会话 / 反馈 | 删除后首次启动自动重建（历史会话丢失） |
| `logs/` | 运行日志（`app.log`，10MB×5 滚动） | 可随时删除 |

`.gitignore` 已排除本目录下的所有内容（仅保留 `.gitkeep` 与说明），**禁止把数据文件提交到仓库**。
