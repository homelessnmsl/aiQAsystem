"""检索侧 A/B 对比脚本（FR-QA-03 对比数据；W3 AD 任务）

用法（仓库根目录）：
    python scripts/eval_retrieval.py            # 基线：向量检索（不重排）
    python scripts/eval_retrieval.py --rerank   # 开启 Rerank 重排

输出指标（以 tests/qa_dataset_v1.json 20 条为输入）：
- M-01 Recall@5：正确文档出现在返回前 5 条中的比例
- Top-1 来源准确率：第 1 条来自正确文档的比例
- Top-1 引用位置覆盖率：第 1 条位置覆盖题目期望位置（页码/工作表/章节，自动宽松判定，M-02 以人工核验为准）
- 越界问题最高分：5 条无答案问题的 top-1 分数（应低于 SCORE_THRESHOLD，否则会误答）
"""
from __future__ import annotations

import argparse
import json
import re
import statistics
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app.core.config import settings          # noqa: E402
from app.services.retrieval import retrieve   # noqa: E402

DATASET = ROOT / "tests" / "qa_dataset_v1.json"


def locator_ok(expected: str, actual: str, metadata: dict) -> bool:
    """宽松判定位置覆盖：页码相等 / 工作表相等 / 期望章节名出现在位置串或 sections 元数据中"""
    if not expected or not actual:
        return False
    page_expected = re.search(r"第\s*(\d+)\s*页", expected)
    page_actual = re.search(r"第\s*(\d+)\s*页", actual)
    if page_expected and page_actual:
        return page_expected.group(1) == page_actual.group(1)
    sheet_expected = re.search(r"工作表「([^」]+)」", expected)
    sheet_actual = re.search(r"工作表「([^」]+)」", actual)
    if sheet_expected and sheet_actual:
        return sheet_expected.group(1) == sheet_actual.group(1)
    tokens = re.findall(r"「([^」]+)」", expected)
    haystack = f"{actual}｜{metadata.get('sections', '')}"
    return any(token in haystack for token in tokens)


def main() -> int:
    """命令行入口：跑 20 条评测集并打印对比指标"""
    parser = argparse.ArgumentParser(description="检索 A/B 对比（向量检索 vs Rerank 重排）")
    parser.add_argument("--rerank", action="store_true", help="开启 Rerank 重排")
    args = parser.parse_args()

    data = json.loads(DATASET.read_text(encoding="utf-8"))
    answered = [item for item in data if item.get("expected_source")]
    noanswer = [item for item in data if not item.get("expected_source")]

    mode = "Rerank 重排" if args.rerank else "向量检索（基线）"
    print(f"[模式] {mode} | 阈值={settings.SCORE_THRESHOLD} | 召回={settings.RETRIEVE_K} → Top{settings.TOP_K}")
    print(f"{'ID':8} {'Recall@5':9} {'Top1来源':9} {'位置覆盖':9} 分数")
    # 预热：加载 Embedding / Rerank 模型（不计入时延统计，避免冷启动拉高 P95）
    try:
        retrieve("预热", use_rerank=args.rerank, top_k=1)
    except Exception:
        pass

    recall = top1_file = locator = 0
    latencies = []
    for item in answered:
        started = time.perf_counter()
        chunks = retrieve(item["question"], use_rerank=args.rerank)
        latencies.append((time.perf_counter() - started) * 1000)
        sources = [chunk.source_file for chunk in chunks]
        hit5 = item["expected_source"] in sources
        top1 = chunks[0] if chunks else None
        top1_ok = bool(top1) and top1.source_file == item["expected_source"]
        loc_ok = bool(top1) and locator_ok(item.get("expected_location", ""), top1.location, top1.metadata)
        recall += int(hit5)
        top1_file += int(top1_ok)
        locator += int(loc_ok)
        score = top1.score if top1 else 0.0
        print(f"{item['id']:8} {'√' if hit5 else '×':9} {'√' if top1_ok else '×':9} {'√' if loc_ok else '×':9} {score:.3f}")

    total = len(answered)
    print(f"\nM-01 Recall@5        = {recall}/{total} = {recall / total * 100:.1f}%")
    print(f"Top-1 来源准确率      = {top1_file}/{total} = {top1_file / total * 100:.1f}%")
    print(f"Top-1 引用位置覆盖率  = {locator}/{total} = {locator / total * 100:.1f}%")
    if latencies:
        ordered = sorted(latencies)
        p95 = ordered[min(len(ordered) - 1, int(len(ordered) * 0.95))]
        print(
            f"检索耗时              = 中位 {statistics.median(latencies):.0f}ms / P95 {p95:.0f}ms"
            f"（M-05 检索段预算 ≤1500ms）"
        )

    print("\n== 越界问题（top-1 应低于阈值 → 正确拒答）==")
    worst = 0.0
    for item in noanswer:
        chunks = retrieve(item["question"], top_k=1, use_rerank=args.rerank)
        score = chunks[0].score if chunks else 0.0
        worst = max(worst, score)
        verdict = "√ 正确拒答" if not chunks else "× 会误答"
        print(f"{item['id']:8} {item['question'][:26]:28} top1={score:.3f} {verdict}")
    print(f"越界问题最高分 = {worst:.3f}（阈值 {settings.SCORE_THRESHOLD}）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
