# scripts/ —— 运维与评测脚本

| 脚本 | 用途 | 主责 | 状态 |
| :--- | :--- | :--- | :--- |
| `init_kb.py` | 批量导入文档建库（默认 `tests/sample_docs/`，支持 `--rebuild`） | AD | ✅ 第2周（10-08 实测 10/10 入库） |
| `query_kb.py` | 命令行检索自测（top-k + 阈值 + 上下文预览） | AD | ✅ 第2周 |
| `eval_retrieval.py` | 检索 A/B 对比（向量 vs Rerank：Recall@5 / Top-1 来源 / 位置覆盖 / 时延 / 越界体检） | AD | ✅ 第3周预研（10-08 出对比数据） |
| `build_kb.py` | 重建向量库（`--rebuild` 清空后扫描 `data/uploads/` 全量重导入） | AD | ✅ 第2周 |
| `download_model.py` | 从 ModelScope（魔搭）下载 Embedding 模型到本地（应对 HF 不可达） | AD | ✅ 第2周 |
| `eval_rag.py` | 评测 M-01~M-04：`--mode retrieval/offline/api`、`--dataset`（单轮/多轮）、`--rewrite none/llm`、`--history-style text/messages`（W3-08 A/B），输出逐条明细与报告草稿 | PE | ✅ 第3周（10-09 多轮四配置 A/B，见 `docs/多轮评测与A-B数据.md`） |
| `check_qa_dataset.py` | 评测集格式校验（PE 交付） | PE | ✅ 第1周 |
| `run_all.py` | 一键启动前后端（演示与 M-07 首次可用时间） | DEV | 第2周（W2-08 联调期） |

常用命令（仓库根目录）：
```bash
python scripts/init_kb.py --rebuild                    # 重建知识库（样例数据）
python scripts/query_kb.py "出差住宿标准是多少？" --context
python scripts/build_kb.py --dir tests/sample_docs     # 指定目录重建
python scripts/download_model.py                       # 首次使用本地模型前的下载（HF 不可达时）
```

## Issue 批量补传（PM 工具，W2-15）

- `issues_batch.json`：35 条 Issue 数据（第1周18 + 第2周17），由周任务清单生成
- `upload_issues.py`：幂等上传（按标题判重）；`--dry-run` 预演；令牌经 `--token` / `GITEE_TOKEN` 环境变量 / 仓库根 `.gitee_token` 文件提供（该文件已被 .gitignore 忽略）
- 用法：`python scripts/upload_issues.py --dry-run`；真实上传：`python scripts/upload_issues.py --token <私人令牌>`
- `sync_issue_states.py`：按 `issues_batch.json` 的 status 同步 Gitee Issue 状态（✅→已完成，其余保持打开）；`--dry-run` 预演，幂等可复跑