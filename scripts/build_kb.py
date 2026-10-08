"""重建向量库脚本（架构设计 6.6 / 4.2；W2-03）

用法（仓库根目录执行）：
    python scripts/build_kb.py --rebuild                  # 清空 + 全量重建 data/uploads/（FR-KB-02 重建策略）
    python scripts/build_kb.py --dir tests/sample_docs    # 指定目录重建
    python scripts/build_kb.py                            # 不清空，增量导入 data/uploads/

说明：data/uploads/ 为运行时上传目录（.env 的 UPLOAD_DIR）；样例演示可直接用 --dir tests/sample_docs。
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app.core.config import settings                  # noqa: E402
from app.knowledge.store import vector_store          # noqa: E402
from app.services.ingestion import ingest_paths       # noqa: E402
from app.services.repository import get_repository    # noqa: E402


def main() -> int:
    """命令行入口：按参数重建/增量导入向量库"""
    parser = argparse.ArgumentParser(description="重建知识库向量库（Chroma）")
    parser.add_argument("--dir", default=str(settings.upload_dir), help="要导入的目录（默认 data/uploads/）")
    parser.add_argument("--rebuild", action="store_true", help="导入前清空向量库")
    args = parser.parse_args()

    target = Path(args.dir)
    if not target.exists():
        print(f"[错误] 目录不存在：{target}（可先用 scripts/init_kb.py 导入样例）")
        return 1

    print(f"[重建] 来源目录：{target}")
    print(f"[重建] 集合：{vector_store.collection_name} @ {vector_store.path}（rebuild={args.rebuild}）")

    repository = get_repository()
    if args.rebuild:
        deleted = repository.delete_all_documents()
        print(f"[重建] 台账已同步清空（{deleted} 行）")

    results, failures = ingest_paths([target], rebuild=args.rebuild)

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
        print(f"[成功] {result.filename} → {result.chunk_count} 个切片（{result.elapsed_ms}ms）")
    for file_path, reason in failures:
        print(f"[失败] {file_path.name} → {reason}")

    print(
        f"\n合计：成功 {len(results)} 个 / 失败 {len(failures)} 个，"
        f"向量库现有 {vector_store.count()} 条，台账现有 {repository.count_documents()} 个文档"
    )
    return 0 if results else 1


if __name__ == "__main__":
    raise SystemExit(main())
