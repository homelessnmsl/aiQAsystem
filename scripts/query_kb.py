"""命令行检索自测（W2-03 验收：入库 → 查询 top-k 闭环）

用法（仓库根目录执行）：
    python scripts/query_kb.py "公司年假有多少天？"
    python scripts/query_kb.py "出差住宿标准是多少？" --top-k 3 --threshold 0.3 --context

说明：检索参数与 /api/ask 一致（RETRIEVE_K → 阈值过滤 → TOP_K），
阈值以上无结果时输出提示，供 DEV 走 not_found 兜底。
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app.core.config import settings                       # noqa: E402
from app.knowledge.store import vector_store               # noqa: E402
from app.services.retrieval import build_context, retrieve  # noqa: E402


def main() -> int:
    """命令行入口：检索并打印 top-k 结果"""
    parser = argparse.ArgumentParser(description="命令行检索知识库（top-k 自测）")
    parser.add_argument("question", nargs="?", default="公司年假有多少天？", help="用户问题")
    parser.add_argument("--top-k", type=int, default=None, help="返回条数（默认 TOP_K=5）")
    parser.add_argument("--threshold", type=float, default=None, help="相似度阈值（默认 0.35）")
    parser.add_argument("--context", action="store_true", help="同时打印注入 Prompt 的编号上下文")
    args = parser.parse_args()

    print(f"[知识库] {vector_store.count()} 条切片 | 集合 {vector_store.collection_name}")
    print(f"[问题] {args.question}")

    chunks = retrieve(args.question, top_k=args.top_k, score_threshold=args.threshold)
    if not chunks:
        print("（无命中：相似度均低于阈值 → /api/ask 应走 not_found 兜底，不调用 LLM）")
        return 0

    for chunk in chunks:
        preview = chunk.content[:70].replace("\n", " ")
        print(f"[{chunk.rank}] score={chunk.score:.4f}  {chunk.source_file}（{chunk.location}）")
        print(f"     {preview}…")

    if args.context:
        print("\n--- 编号上下文（供 Prompt 注入） ---")
        print(build_context(chunks))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
