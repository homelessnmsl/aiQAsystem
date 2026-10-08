# -*- coding: utf-8 -*-
"""RAG 端到端评测脚本：跑 tests/qa_dataset_v1.json 20 条，输出 M-01~M-04 与逐条明细（PE · W2-10）。

用法（仓库根目录，建议用虚拟环境 python）：
    python scripts/eval_rag.py                    # 自动：/api/ask 可连则走 API，否则走离线直连（不依赖后端进程）
    python scripts/eval_rag.py --mode offline     # 离线直连：检索 → Prompt → DeepSeek 生成
    python scripts/eval_rag.py --mode retrieval   # 只跑检索（不调用大模型）：M-01 + 拒答阈值体检
    python scripts/eval_rag.py --mode api --base-url http://127.0.0.1:8000   # DEV /api/ask 就绪后使用
    python scripts/eval_rag.py --report docs/评测报告_v1.md                  # 额外生成报告草稿

与 scripts/eval_retrieval.py 的分工：
- eval_retrieval.py（AD）：向量 vs Rerank 的检索侧 A/B 对比；
- eval_rag.py（PE，本脚本）：在检索之上补"生成 + 引用 + 拒答"的 M-01~M-04 全量评测，
  是 /api/ask 的评测替身——DEV 接口就绪后直接 `--mode api` 切换，口径不变。

指标口径见 docs/评测集说明_v1.md 第 4 节；M-02 / M-03 的自动结果为预判，最终以人工复核为准。
"""

from __future__ import annotations

import argparse
import json
import re
import statistics
import sys
import time
from datetime import datetime
from pathlib import Path
from string import Template
from typing import Any, Dict, List, Optional, Tuple

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app.core.config import settings  # noqa: E402
from app.services.retrieval import build_citations, build_context, retrieve  # noqa: E402

DATASET = ROOT / "tests" / "qa_dataset_v1.json"
PROMPTS = ROOT / "prompts"
DEFAULT_OUT_DIR = ROOT / "data" / "eval"

NUMBER_RE = re.compile(r"\d+(?:\.\d+)?")
CN_RUN_RE = re.compile(r"[\u4e00-\u9fa5]{3,}")
CITE_RE = re.compile(r"\[(\d+)\]")
PAGE_RE = re.compile(r"第\s*(\d+)\s*页")
SHEET_RE = re.compile(r"工作表「([^」]+)」")
TURN_PREFIX_RE = re.compile(r"^第\s*\d+\s*轮[：:]?\s*")

FALLBACK_ANSWER = "抱歉，未在企业知识库中找到相关依据。您可以换个说法提问，或联系管理员补充相关文档。"


# --------------------------------------------------------------------------- #
# 基础工具
# --------------------------------------------------------------------------- #
def parse_args(argv: List[str]) -> argparse.Namespace:
    """解析命令行参数。"""
    parser = argparse.ArgumentParser(description="RAG 端到端评测（M-01~M-04）")
    parser.add_argument("--mode", choices=["auto", "api", "offline", "retrieval"], default="auto")
    parser.add_argument("--base-url", default="http://127.0.0.1:8000", help="后端地址（api 模式）")
    parser.add_argument("--top-k", type=int, default=None, help="覆盖 TOP_K")
    parser.add_argument("--threshold", type=float, default=None, help="覆盖 SCORE_THRESHOLD")
    parser.add_argument("--rerank", action="store_true", help="启用 Rerank（第3周，默认关闭）")
    parser.add_argument("--out", default=None, help="逐条明细 JSON 输出路径")
    parser.add_argument("--report", default=None, help="Markdown 报告草稿输出路径")
    parser.add_argument("--limit", type=int, default=None, help="只跑前 N 条（调试用）")
    parser.add_argument("--sleep", type=float, default=0.3, help="逐条调用间隔（秒）")
    return parser.parse_args(argv)


def load_dataset(limit: Optional[int] = None) -> List[Dict[str, Any]]:
    """读取评测集（tests/qa_dataset_v1.json）。"""
    data = json.loads(DATASET.read_text(encoding="utf-8"))
    return data[:limit] if limit else data


def load_prompts() -> Tuple[str, Template]:
    """读取知识库问答系统提示词与问答模板。"""
    system_prompt = (PROMPTS / "system_rag.md").read_text(encoding="utf-8")
    template = Template((PROMPTS / "answer_template.md").read_text(encoding="utf-8"))
    return system_prompt, template


def numbers_in(text: str) -> set:
    """提取文本中的数字集合（用于自动预评分与编造检测）。"""
    return set(NUMBER_RE.findall(text or ""))


def score_key_points(answer: str, key_points: List[str]) -> Tuple[float, Dict[str, Any]]:
    """按 key_points 自动预评分：1.0 完整 / 0.5 部分 / 0.0 错误（人工复核为准）。

    规则：关键数字命中率 = 100% 记 1.0，≥60% 记 0.5；无数字的要点退化为中文片段命中判断。
    """
    answer = answer or ""
    points = [TURN_PREFIX_RE.sub("", point) for point in (key_points or [])]
    expected_nums = set()
    for point in points:
        expected_nums |= numbers_in(point)
    if expected_nums:
        matched = expected_nums & numbers_in(answer)
        ratio = len(matched) / len(expected_nums)
        score = 1.0 if ratio >= 1.0 else (0.5 if ratio >= 0.6 else 0.0)
        return score, {"关键数字": f"{len(matched)}/{len(expected_nums)}", "缺失": sorted(expected_nums - matched)}
    runs = CN_RUN_RE.findall(" ".join(points))
    hits = [run for run in runs if run in answer]
    return (1.0 if hits else 0.0), {"中文片段": f"{len(hits)}/{len(runs)}"}


def locator_ok(expected: str, actual: str) -> bool:
    """宽松判定引用位置是否覆盖期望位置（M-02 预检；最终人工核验）。"""
    if not expected or not actual:
        return False
    page_expected, page_actual = PAGE_RE.search(expected), PAGE_RE.search(actual)
    if page_expected and page_actual:
        return page_expected.group(1) == page_actual.group(1)
    sheet_expected, sheet_actual = SHEET_RE.search(expected), SHEET_RE.search(actual)
    if sheet_expected and sheet_actual:
        return sheet_expected.group(1) == sheet_actual.group(1)
    tokens = re.findall(r"「([^」]+)」", expected)
    return any(token in actual for token in tokens)


# --------------------------------------------------------------------------- #
# 三种运行模式
# --------------------------------------------------------------------------- #
def run_retrieval(item: Dict[str, Any], args: argparse.Namespace) -> List[Dict[str, Any]]:
    """检索模式：只取上下文，不做生成。"""
    questions = [item["question"]] + list(item.get("follow_up_questions") or [])
    turns = []
    previous = ""
    for index, question in enumerate(questions):
        query = question if index == 0 else f"{previous} {question}"
        started = time.perf_counter()
        chunks = retrieve(query, top_k=args.top_k, score_threshold=args.threshold, use_rerank=args.rerank)
        elapsed = (time.perf_counter() - started) * 1000
        turns.append(
            {
                "question": question,
                "query": query,
                "answer": None,
                "answer_type": None,
                "used_indices": [],
                "citations": [],
                "retrieved": [
                    {"rank": c.rank, "source_file": c.source_file, "location": c.location, "score": c.score}
                    for c in chunks
                ],
                "latency_ms": round(elapsed),
            }
        )
        previous = question
    return turns


def run_offline(
    item: Dict[str, Any], args: argparse.Namespace, client: Any, system_prompt: str, template: Template
) -> List[Dict[str, Any]]:
    """离线直连：检索 → 编号上下文 → 注入 Prompt → DeepSeek 生成（模拟 /api/ask 主链路）。"""
    questions = [item["question"]] + list(item.get("follow_up_questions") or [])
    messages: List[Dict[str, str]] = [{"role": "system", "content": system_prompt}]
    turns = []
    previous = ""
    for index, question in enumerate(questions):
        query = question if index == 0 else f"{previous} {question}"  # 第2周简易改写，第3周换模型改写
        started = time.perf_counter()
        chunks = retrieve(query, top_k=args.top_k, score_threshold=args.threshold, use_rerank=args.rerank)
        if not chunks:
            elapsed = round((time.perf_counter() - started) * 1000)
            user_content = template.safe_substitute(history="（无）", context="（空）", question=question)
            turns.append(
                {
                    "question": question,
                    "query": query,
                    "answer": FALLBACK_ANSWER,
                    "answer_type": "not_found",
                    "used_indices": [],
                    "citations": [],
                    "retrieved": [],
                    "latency_ms": elapsed,
                    "model_called": False,
                }
            )
            messages.append({"role": "user", "content": user_content})
            messages.append({"role": "assistant", "content": FALLBACK_ANSWER})
            previous = question
            continue

        context = build_context(chunks)
        citations = build_citations(chunks)
        user_content = template.safe_substitute(history="（无）", context=context, question=question)
        result = client.chat(messages + [{"role": "user", "content": user_content}], temperature=0.2, max_tokens=512)
        elapsed = round((time.perf_counter() - started) * 1000)
        answer = result.content
        used = sorted({int(x) for x in CITE_RE.findall(answer)})
        turns.append(
            {
                "question": question,
                "query": query,
                "answer": answer,
                "answer_type": "answered" if used else "not_found",
                "used_indices": used,
                "citations": citations,
                "retrieved": [
                    {"rank": c.rank, "source_file": c.source_file, "location": c.location, "score": c.score}
                    for c in chunks
                ],
                "latency_ms": elapsed,
                "model_called": True,
                "usage": {
                    "prompt_tokens": result.usage.prompt_tokens,
                    "completion_tokens": result.usage.completion_tokens,
                    "total_tokens": result.usage.total_tokens,
                },
            }
        )
        messages.append({"role": "user", "content": user_content})
        messages.append({"role": "assistant", "content": answer})
        previous = question
    return turns


def run_api(item: Dict[str, Any], args: argparse.Namespace) -> List[Dict[str, Any]]:
    """API 模式：调用运行中的 /api/ask（DEV 交付后使用）。"""
    import requests  # 延迟导入，便于 retrieval/offline 模式在无 requests 环境运行

    questions = [item["question"]] + list(item.get("follow_up_questions") or [])
    session_id: Optional[str] = None
    turns = []
    for question in questions:
        payload: Dict[str, Any] = {"question": question, "session_id": session_id}
        if args.top_k is not None:
            payload["top_k"] = args.top_k
        if args.threshold is not None:
            payload["score_threshold"] = args.threshold
        if args.rerank:
            payload["use_rerank"] = True
        started = time.perf_counter()
        response = requests.post(f"{args.base_url.rstrip('/')}/api/ask", json=payload, timeout=180)
        elapsed = round((time.perf_counter() - started) * 1000)
        body = response.json()
        if body.get("code") != 0:
            raise RuntimeError(f"{item['id']} 调用失败：code={body.get('code')} message={body.get('message')}")
        data = body["data"]
        session_id = data.get("session_id")
        answer = data.get("answer") or ""
        turns.append(
            {
                "question": question,
                "query": data.get("rewritten_question") or question,
                "answer": answer,
                "answer_type": data.get("answer_type"),
                "used_indices": sorted({int(x) for x in CITE_RE.findall(answer)}),
                "citations": data.get("citations") or [],
                "retrieved": [
                    {"rank": c.get("rank"), "source_file": c.get("source_file"), "location": c.get("location"), "score": c.get("score")}
                    for c in (data.get("retrieved") or [])
                ],
                "latency_ms": (data.get("latency_ms") or {}).get("total", elapsed),
                "model_called": data.get("model") is not None,
                "trace_id": data.get("trace_id"),
            }
        )
    return turns


# --------------------------------------------------------------------------- #
# 指标计算
# --------------------------------------------------------------------------- #
def compute_metrics(records: List[Dict[str, Any]], mode: str) -> Dict[str, Any]:
    """按 docs/评测集说明_v1.md 的口径计算 M-01~M-04（自动部分）。"""
    answered = [r for r in records if r["answer_type_expected"] == "answered"]
    noanswer = [r for r in records if r["answer_type_expected"] == "not_found"]

    m01_hit = 0
    for record in answered:
        hit = all(
            any(chunk["source_file"] == record["expected_source"] for chunk in turn["retrieved"])
            for turn in record["turns"]
        )
        record["m01_hit"] = hit
        m01_hit += int(hit)

    cite_total = cite_source_ok = cite_loc_ok = 0
    m03_scores = []
    for record in answered:
        turn_scores = []
        for turn in record["turns"]:
            used = turn.get("used_indices") or []
            for index in used:
                citation = next((c for c in turn.get("citations", []) if c.get("index") == index), None)
                if citation is None:
                    continue
                cite_total += 1
                cite_source_ok += int(citation.get("source_file") == record["expected_source"])
                cite_loc_ok += int(locator_ok(record.get("expected_location", ""), citation.get("location", "")))
            if mode != "retrieval":
                score, detail = score_key_points(turn.get("answer") or "", record.get("key_points") or [])
                turn["auto_score"] = score
                turn["auto_score_detail"] = detail
                turn_scores.append(score)
        record["auto_score"] = min(turn_scores) if turn_scores else None
        if record["auto_score"] is not None:
            m03_scores.append(record["auto_score"])

    m04_ok = 0
    for record in noanswer:
        turn_ok = []
        for turn in record["turns"]:
            answer = turn.get("answer") or ""
            if mode == "retrieval":
                ok = not turn.get("retrieved")  # 检索为空 → /api/ask 将走 not_found 兜底
            else:
                ok = (
                    turn.get("answer_type") == "not_found"
                    and not turn.get("used_indices")
                    and not NUMBER_RE.search(answer)
                )
            turn["refusal_ok"] = ok
            turn["retrieval_leak"] = bool(turn.get("retrieved"))
            turn_ok.append(ok)
        record["m04_ok"] = all(turn_ok)
        m04_ok += int(record["m04_ok"])

    answered_lat = [t["latency_ms"] for r in answered for t in r["turns"]]

    def percentile(values: List[float], ratio: float) -> Optional[float]:
        if not values:
            return None
        ordered = sorted(values)
        return ordered[min(len(ordered) - 1, int(len(ordered) * ratio))]

    return {
        "mode": mode,
        "total": len(records),
        "answered_total": len(answered),
        "noanswer_total": len(noanswer),
        "m01_hit": m01_hit,
        "m01_rate": round(m01_hit / len(answered) * 100, 1) if answered else None,
        "cite_total": cite_total,
        "cite_source_ok": cite_source_ok,
        "cite_source_rate": round(cite_source_ok / cite_total * 100, 1) if cite_total else None,
        "cite_location_ok": cite_loc_ok,
        "cite_location_rate": round(cite_loc_ok / cite_total * 100, 1) if cite_total else None,
        "m03_avg": round(sum(m03_scores) / len(m03_scores), 3) if m03_scores else None,
        "m03_full": sum(1 for s in m03_scores if s == 1.0),
        "m03_partial": sum(1 for s in m03_scores if s == 0.5),
        "m03_zero": sum(1 for s in m03_scores if s == 0.0),
        "m04_ok": m04_ok,
        "m04_rate": round(m04_ok / len(noanswer) * 100, 1) if noanswer else None,
        "latency_median_ms": round(statistics.median(answered_lat)) if answered_lat else None,
        "latency_p95_ms": round(percentile(answered_lat, 0.95)) if answered_lat else None,
    }


# --------------------------------------------------------------------------- #
# 输出
# --------------------------------------------------------------------------- #
def build_report(run: Dict[str, Any]) -> str:
    """生成 Markdown 报告草稿（PE 复核后定稿为 docs/评测报告_v1.md）。"""
    metrics = run["metrics"]
    records = run["records"]
    lines: List[str] = []
    lines.append("# RAG 评测报告 v1（草稿，待 PE 复核结论）")
    lines.append("")
    lines.append("> 由 `scripts/eval_rag.py` 自动生成；M-02 / M-03 的自动结果为预判，需要人工复核列确认。")
    lines.append("")
    lines.append("| 运行信息 | 值 |")
    lines.append("| :--- | :--- |")
    lines.append(f"| 运行时间 | {run['started_at']} |")
    lines.append(f"| 模式 | {metrics['mode']} |")
    lines.append(f"| 参数 | TOP_K={settings.TOP_K}｜SCORE_THRESHOLD={settings.SCORE_THRESHOLD}｜RERANK={settings.RERANK_ENABLED} |")
    lines.append(f"| 题目数 | {metrics['total']}（可答 {metrics['answered_total']} / 拒答 {metrics['noanswer_total']}） |")
    lines.append("")
    lines.append("## 1. 指标汇总")
    lines.append("")
    lines.append("| 指标 | 目标 | 实测（自动预判） | 达标 |")
    lines.append("| :--- | :--- | :--- | :--- |")
    m01 = f"{metrics['m01_hit']}/{metrics['answered_total']} = {metrics['m01_rate']}%"
    lines.append(f"| M-01 检索命中率 Recall@5 | ≥ 80% | {m01} | {'✅' if (metrics['m01_rate'] or 0) >= 80 else '❌'} |")
    if metrics["cite_total"]:
        cite = f"{metrics['cite_source_ok']}/{metrics['cite_total']} = {metrics['cite_source_rate']}%（位置覆盖 {metrics['cite_location_rate']}%）"
        lines.append(f"| M-02 引用准确率（来源预检） | ≥ 85% | {cite} | 待人工 |")
    else:
        lines.append("| M-02 引用准确率 | ≥ 85% | 本模式未生成答案 | — |")
    if metrics["m03_avg"] is not None:
        m03 = f"均分 {metrics['m03_avg']}（完整 {metrics['m03_full']} / 部分 {metrics['m03_partial']} / 错误 {metrics['m03_zero']}）"
        lines.append(f"| M-03 答案正确率（自动预判） | ≥ 75% | {m03} | 待人工 |")
    else:
        lines.append("| M-03 答案正确率 | ≥ 75% | 本模式未生成答案 | — |")
    m04 = f"{metrics['m04_ok']}/{metrics['noanswer_total']} = {metrics['m04_rate']}%"
    lines.append(f"| M-04 拒答正确率 | ≥ 90% | {m04} | {'✅' if (metrics['m04_rate'] or 0) >= 90 else '❌'} |")
    if metrics["latency_median_ms"]:
        lines.append(f"| 时延（辅助） | 检索 P95 ≤ 1.5s | 全链路中位 {metrics['latency_median_ms']}ms / P95 {metrics['latency_p95_ms']}ms（含生成） | — |")
    lines.append("")
    lines.append("## 2. 逐条明细")
    lines.append("")
    lines.append("| 编号 | 题型 | 难度 | 检索命中 | 引用来源 | 自动评分 | 拒答 | 时延 | 答案摘要 |")
    lines.append("| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |")
    for record in records:
        hits = "√" if record.get("m01_hit") else "×"
        if record["answer_type_expected"] == "not_found":
            hits = "—"
            score_text = "—"
            refusal = "√" if record.get("m04_ok") else "×"
        else:
            score = record.get("auto_score")
            score_text = {1.0: "1.0", 0.5: "0.5", 0.0: "0.0", None: "—"}.get(score, "—")
            refusal = "—"
        last_turn = record["turns"][-1]
        answer = last_turn.get("answer") or ("（仅检索）" if last_turn.get("retrieved") else "")
        answer = answer.replace("\n", " ")[:60]
        cite_files = "、".join(sorted({c.get("source_file", "") for t in record["turns"] for c in t.get("citations", [])})) or "—"
        lines.append(
            f"| {record['id']} | {record['type']} | {record['difficulty']} | {hits} | {cite_files} | {score_text} | {refusal} | {last_turn['latency_ms']}ms | {answer} |"
        )
    lines.append("")
    lines.append("## 3. 人工复核清单（M-02 / M-03）")
    lines.append("")
    lines.append("| 编号 | 期望来源 / 位置 | 实际引用 | 片段是否支撑结论 | 答案完整/部分/错误 |")
    lines.append("| :--- | :--- | :--- | :--- | :--- |")
    for record in records:
        if record["answer_type_expected"] != "answered":
            continue
        cited = "；".join(
            f"[{c['index']}] {c['source_file']}（{c['location']}）"
            for t in record["turns"]
            for c in t.get("citations", [])
            if c.get("index") in (t.get("used_indices") or [])
        )
        lines.append(
            f"| {record['id']} | {record.get('expected_source')}（{record.get('expected_location')}） | {cited or '未引用'} |  |  |"
        )
    lines.append("")
    lines.append("## 4. 结论（待 PE 填写）")
    lines.append("")
    lines.append("- 达标情况：")
    lines.append("- 主要问题与原因：")
    lines.append("- 下一步（Prompt v1.1 / 检索优化）：")
    lines.append("")
    return "\n".join(lines)


def print_summary(run: Dict[str, Any]) -> None:
    """打印逐条结果与控制台指标汇总。"""
    metrics = run["metrics"]
    print(f"[模式] {metrics['mode']} | TOP_K={settings.TOP_K} 阈值={settings.SCORE_THRESHOLD} RERANK={settings.RERANK_ENABLED}")
    print(f"{'ID':8} {'可用':4} {'命中':4} {'评分':5} {'拒答':4} {'时延':8} 摘要")
    for record in run["records"]:
        last = record["turns"][-1]
        answer = (last.get("answer") or "").replace("\n", " ")[:34]
        hit = "√" if record.get("m01_hit") else ("×" if record["answer_type_expected"] == "answered" else "—")
        score = record.get("auto_score")
        score_text = f"{score:.1f}" if isinstance(score, float) else "—"
        refusal = "√" if record.get("m04_ok") else ("×" if record["answer_type_expected"] == "not_found" else "—")
        status = last.get('answer_type') or '—'
        print(f"{record['id']:8} {status:4} {hit:4} {score_text:5} {refusal:4} {last['latency_ms']:>6}ms {answer}")
    print("\n== 指标汇总（自动预判，M-02/M-03 以人工复核为准）==")
    print(f"M-01 检索命中率 Recall@5 = {metrics['m01_hit']}/{metrics['answered_total']} = {metrics['m01_rate']}%")
    if metrics["cite_total"]:
        print(f"M-02 引用来源预检       = {metrics['cite_source_ok']}/{metrics['cite_total']} = {metrics['cite_source_rate']}%（位置覆盖 {metrics['cite_location_rate']}%）")
    if metrics["m03_avg"] is not None:
        print(f"M-03 答案自动预评       = 均分 {metrics['m03_avg']}（完整 {metrics['m03_full']} / 部分 {metrics['m03_partial']} / 错误 {metrics['m03_zero']}）")
    if metrics["noanswer_total"]:
        print(f"M-04 拒答正确率         = {metrics['m04_ok']}/{metrics['noanswer_total']} = {metrics['m04_rate']}%")
    if metrics["latency_median_ms"]:
        print(f"时延（辅助）            = 中位 {metrics['latency_median_ms']}ms / P95 {metrics['latency_p95_ms']}ms")


def main(argv: Optional[List[str]] = None) -> int:
    """脚本入口：选择运行模式，逐条评测并输出明细与指标。"""
    args = parse_args(sys.argv[1:] if argv is None else argv)
    data = load_dataset(args.limit)
    mode = args.mode

    system_prompt = template = None
    client = None
    if mode in ("auto", "offline", "api"):
        system_prompt, template = load_prompts()
    if mode in ("auto", "api"):
        import requests

        try:
            requests.get(f"{args.base_url.rstrip('/')}/api/health", timeout=3)
            mode = "api"
            print(f"[自动] 检测到后端 {args.base_url}，使用 api 模式")
        except Exception:
            mode = "offline"
            print("[自动] 后端不可用，回退 offline 模式（本地直连检索 + DeepSeek）")
    if mode == "offline":
        from app.services.llm import get_llm_client

        client = get_llm_client()

    run: Dict[str, Any] = {
        "started_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "mode": mode,
        "dataset": str(DATASET),
        "records": [],
    }
    for index, item in enumerate(data, start=1):
        print(f"[{index}/{len(data)}] {item['id']} {item['question']}")
        if mode == "retrieval":
            turns = run_retrieval(item, args)
        elif mode == "offline":
            turns = run_offline(item, args, client, system_prompt, template)
        else:
            turns = run_api(item, args)
        run["records"].append(
            {
                "id": item["id"],
                "question": item["question"],
                "type": item["type"],
                "difficulty": item["difficulty"],
                "answer_type_expected": item["answer_type"],
                "expected_source": item.get("expected_source"),
                "expected_location": item.get("expected_location"),
                "key_points": item.get("key_points") or [],
                "notes": item.get("notes"),
                "turns": turns,
            }
        )
        if args.sleep:
            time.sleep(args.sleep)

    run["metrics"] = compute_metrics(run["records"], mode)
    print_summary(run)

    out_path = Path(args.out) if args.out else DEFAULT_OUT_DIR / f"eval_rag_{mode}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(run, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n逐条明细已写入：{out_path}")

    if args.report:
        report_path = Path(args.report)
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(build_report(run), encoding="utf-8")
        print(f"报告草稿已写入：{report_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())