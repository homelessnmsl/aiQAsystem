"""批量导入文档建库脚本（架构设计 4.2 / 13；W2-03）

用法（仓库根目录执行）：
    python scripts/init_kb.py                       # 导入 tests/sample_docs/ 全部样例
    python scripts/init_kb.py tests/sample_docs/01_员工手册.pdf
    python scripts/init_kb.py some_dir --rebuild    # 先清空向量库再导入

提示：首次运行需要下载本地向量模型（约 100MB）。国内网络可先设置镜像：
    PowerShell:  $env:HF_ENDPOINT="https://hf-mirror.com"
    CMD:         set HF_ENDPOINT=https://hf-mirror.com
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app.knowledge.store import vector_store          # noqa: E402
from app.services.ingestion import ingest_paths       # noqa: E402
from app.services.repository import get_repository    # noqa: E402

DEFAULT_DIR = ROOT / "tests" / "sample_docs"


def main() -> int:
    """命令行入口：解析参数 → 批量入库 → 打印摘要"""
    parser = argparse.ArgumentParser(description="导入文档并构建知识库（Chroma）")
    parser.add_argument("paths", nargs="*", help="文件或目录（默认 tests/sample_docs/）")
    parser.add_argument("--rebuild", action="store_true", help="导入前清空向量库")
    args = parser.parse_args()

    targets = args.paths or [str(DEFAULT_DIR)]

    print(f"[知识库] 目标：{', '.join(str(t) for t in targets)}")
    print(f"[知识库] 集合：{vector_store.collection_name} @ {vector_store.path}")

    repository = get_repository()
    if args.rebuild:
        deleted = repository.delete_all_documents()
        print(f"[知识库] 台账已同步清空（{deleted} 行）")

    results, failures = ingest_paths(targets, rebuild=args.rebuild)

    # 同步 SQLite 台账（与向量库保持一致，架构 6.6）
    for result in results:
        source = Path(result.source_path)
        repository.upsert_document(
            doc_id=result.doc_id,
            filename=result.filename,
            file_type=result.file_type,
            size_bytes=source.stat().st_size if source.exists() else 0,
            upload_time=result.created_at,
            chunk_count=result.chunk_count,
            status="success",
        )

    for result in results:
        note = f"；提示：{'；'.join(result.warnings)}" if result.warnings else ""
        print(f"[成功] {result.filename} → {result.chunk_count} 个切片（{result.elapsed_ms}ms）{note}")
    for file_path, reason in failures:
        print(f"[失败] {file_path.name} → {reason}")

    total_chunks = sum(item.chunk_count for item in results)
    print(
        f"\n合计：成功 {len(results)} 个 / 失败 {len(failures)} 个，"
        f"本次入库 {total_chunks} 个切片，向量库现有 {vector_store.count()} 条，"
        f"台账现有 {repository.count_documents()} 个文档"
    )
    return 0 if results else 1


if __name__ == "__main__":
    raise SystemExit(main())
