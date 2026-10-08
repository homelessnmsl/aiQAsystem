"""入库编排流水线：解析 → 切片 → 向量化 → Chroma（架构 6.1；W2-03）

供 ``scripts/init_kb.py`` 与 DEV 的 ``POST /api/upload``（W2-05）复用：

    from app.services.ingestion import ingest_file

    result = ingest_file(Path("tests/sample_docs/01_员工手册.pdf"))
    print(result.doc_id, result.chunk_count)

单文件失败抛 BizError（1002/2002/2003）；**调用方负责逐文件 try/except**，
保证单个文件失败不影响批量流程（FR-DOC-04 / NFR-R-01）。
"""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional

from ..core.errors import CODE_PARSE_FAILED, BizError
from ..core.logging import now_iso
from ..knowledge.loaders.registry import SUPPORTED_EXTENSIONS, load_document
from ..knowledge.metadata import new_doc_id, safe_filename
from ..knowledge.splitter import Chunk, split_document
from ..knowledge.store import VectorStore, vector_store
from .embedding import EmbeddingProvider, get_embedding_provider

logger = logging.getLogger(__name__)


@dataclass
class IngestResult:
    """单文件入库结果（对齐接口文档 2.3 /api/upload 的 items[] 字段）"""

    doc_id: str
    filename: str
    file_type: str
    chunk_count: int
    elapsed_ms: int
    warnings: List[str] = field(default_factory=list)
    created_at: str = ""


def ingest_file(
    path: str | Path,
    *,
    doc_id: Optional[str] = None,
    store: Optional[VectorStore] = None,
    provider: Optional[EmbeddingProvider] = None,
) -> IngestResult:
    """单文件入库：解析 → 切片 → 向量化 → 批量写入 Chroma"""
    started = time.perf_counter()
    file_path = Path(path)
    created_at = now_iso()

    parsed = load_document(file_path)                       # 1002 / 2002
    doc_id = doc_id or new_doc_id()
    chunks: List[Chunk] = split_document(parsed, doc_id, created_at=created_at)
    if not chunks:
        raise BizError(CODE_PARSE_FAILED, f"《{file_path.name}》解析失败：未生成有效切片")

    provider = provider or get_embedding_provider()
    embeddings = provider.embed_documents([chunk.content for chunk in chunks])

    target = store or vector_store
    target.add_chunks(chunks, embeddings)                   # 2003

    elapsed_ms = int((time.perf_counter() - started) * 1000)
    logger.info(
        "入库完成：%s → %s（%d chunks，%dms）", file_path.name, doc_id, len(chunks), elapsed_ms
    )
    return IngestResult(
        doc_id=doc_id,
        filename=safe_filename(file_path.name),
        file_type=parsed.file_type,
        chunk_count=len(chunks),
        elapsed_ms=elapsed_ms,
        warnings=list(parsed.warnings),
        created_at=created_at,
    )

def iter_supported_files(root: str | Path) -> List[Path]:
    """递归收集目录下支持白名单格式的文件（按路径排序，保证批量导入可复现）"""
    root_path = Path(root)
    if root_path.is_file():
        return [root_path] if root_path.suffix.lower() in SUPPORTED_EXTENSIONS else []
    return [
        path
        for path in sorted(root_path.rglob("*"))
        if path.is_file() and path.suffix.lower() in SUPPORTED_EXTENSIONS
    ]


def ingest_paths(
    paths: List[str | Path],
    *,
    rebuild: bool = False,
    store: Optional[VectorStore] = None,
    provider: Optional[EmbeddingProvider] = None,
) -> tuple[List[IngestResult], List[tuple[Path, str]]]:
    """批量入库（逐文件失败隔离，FR-DOC-04 / NFR-R-01）

    返回 ``(成功结果列表, 失败列表[(文件路径, 中文原因)])``；``rebuild=True`` 时先清空集合。
    """
    files: List[Path] = []
    for item in paths:
        files.extend(iter_supported_files(item))

    target = store or vector_store
    if rebuild:
        target.reset()
        logger.info("向量库已清空（rebuild）")

    results: List[IngestResult] = []
    failures: List[tuple[Path, str]] = []
    for file_path in files:
        try:
            results.append(ingest_file(file_path, store=target, provider=provider))
        except BizError as exc:
            failures.append((file_path, exc.message))
            logger.warning("入库失败：%s → %s", file_path.name, exc.message)
    return results, failures
