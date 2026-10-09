# -*- coding: utf-8 -*-
"""RAG 端到端评测脚本：跑 tests/qa_dataset_v1.json 20 条，输出 M-01~M-04 与逐条明细（PE · W2-10）。

用法（仓库根目录，建议用虚拟环境 python）：
    python scripts/eval_rag.py --mode api --dataset tests/qa_multiturn_v1.json        # 多轮集：调真实 /api/ask（生产方案）
    python scripts/eval_rag.py --mode offline --dataset tests/qa_multiturn_v1.json --rewrite llm --history-style text      # 离线 A：改写 + 文本注入（对齐生产）
    python scripts/eval_rag.py --mode offline --dataset tests/qa_multiturn_v1.json --rewrite llm --history-style messages  # 离线 B：改写 + messages 注入（备选）
    python scripts/eval_rag.py --mode offline --dataset tests/qa_multiturn_v1.json --rewrite none --history-style text     # 基线：不改写（第2周行为）
    python scripts/eval_rag.py --mode retrieval --dataset tests/qa_multiturn_v1.json  # 只跑检索，不调用大模型
    python scripts/eval_rag.py --report docs/评测报告_v1.md                           # 单轮集 + 报告草稿（默认 qa_dataset_v1.json）

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
    """解析命令行参数（支持单轮/多轮评测集与历史注入 A/B）。"""
    parser = argparse.ArgumentParser(description="RAG 端到端评测（M-01~M-04；支持多轮与历史注入 A/B）")
    parser.add_argument("--mode", choices=["auto", "api", "offline", "retrieval"], default="auto")
    parser.add_argument(
        "--dataset",
        default=str(DATASET),
        help="评测集路径（默认 tests/qa_dataset_v1.json；多轮集为 tests/qa_multiturn_v1.json）",
    )
    parser.add_argument("--base-url", default="http://127.0.0.1:8000", help="后端地址（api 模式）")
    parser.add_argument("--top-k", type=int, default=None, help="覆盖 TOP_K")
    parser.add_argument("--threshold", type=float, default=None, help="覆盖 SCORE_THRESHOLD")
    parser.add_argument("--rerank", action="store_true", help="启用 Rerank（第3周，默认关闭）")
    parser.add_argument(
        "--history-style",
        choices=["text", "messages"],
        default="text",
        help="offline 历史注入：text=用户/助手文本（与生产一致）；messages=消息数组（备选，W3-08 A/B）",
    )
    parser.add_argument(
        "--rewrite",
        choices=["none", "llm"],
        default="llm",
        help="offline 多轮改写：llm=与生产同口径；none=不改写（第2周基线行为）",
    )
    parser.add_argument("--out", default=None, help="逐条明细 JSON 输出路径")
    parser.add_argument("--report", default=None, help="Markdown 报告草稿输出路径")
    parser.add_argument("--limit", type=int, default=None, help="只跑前 N 条（调试用）")
    parser.add_argument("--repeat", type=int, default=1, help="整集重复采样次数（稳定性复核，默认 1）")
    parser.add_argument("--sleep", type=float, default=0.3, help="逐条调用间隔（秒）")
    return parser.parse_args(argv)


def load_dataset(path: Path, limit: Optional[int] = None) -> List[Dict[str, Any]]:
    """读取评测集并归一化为统一记录结构（兼容单轮 qa_dataset_v1 与多轮 qa_multiturn_v1）。"""
    data = json.loads(path.read_text(encoding="utf-8"))
    records = [normalize_item(item) for item in data]
    return records[:limit] if limit else records


def normalize_item(item: Dict[str, Any]) -> Dict[str, Any]:
    """单轮/多轮条目 → 统一结构。

    统一结构：{id, question, type, difficulty, scenario, notes, expected:[逐轮期望], ...}
    逐轮期望：{question, expected_source, expected_location, key_points, answer_type_expected}
    单轮条目（qa_dataset_v1.json）的 follow_up_questions 逐轮复用本题期望；多轮条目（qa_multiturn_v1.json）自带逐轮 turns。
    """
    if "turns" in item:
        expected = [
            {
                "question": turn["question"],
                "expected_source": turn.get("expected_source"),
                "expected_location": turn.get("expected_location"),
                "key_points": turn.get("key_points") or [],
                "answer_type_expected": turn.get("answer_type", "answered"),
            }
            for turn in item["turns"]
        ]
    else:
        base = {
            "expected_source": item.get("expected_source"),
            "expected_location": item.get("expected_location"),
            "key_points": item.get("key_points") or [],
            "answer_type_expected": item.get("answer_type", "answered"),
        }
        expected = [{"question": item["question"], **base}]
        for follow_up in item.get("follow_up_questions") or []:
            expected.append({"question": follow_up, **base})
    answered = [turn for turn in expected if turn["answer_type_expected"] == "answered"]
    return {
        "id": item["id"],
        "question": expected[0]["question"],
        "type": item.get("type", "多轮追问"),
        "difficulty": item.get("difficulty", "medium"),
        "scenario": item.get("scenario"),
        "notes": item.get("notes"),
        "expected": expected,
        "answer_type_expected": "answered" if answered else "not_found",
        "expected_source": answered[0]["expected_source"] if answered else None,
        "expected_location": answered[0]["expected_location"] if answered else None,
        "key_points": answered[0]["key_points"] if answered else [],
    }


def load_prompts() -> Tuple[str, Template]:
    """读取知识库问答系统提示词与问答模板。"""
    system_prompt = (PROMPTS / "system_rag.md").read_text(encoding="utf-8")
    template = Template((PROMPTS / "answer_template.md").read_text(encoding="utf-8"))
    return system_prompt, template


def format_history_text(entries: List[Dict[str, str]], rounds: int = 3) -> str:
    """历史对话 → “用户：/助手：”文本（与 app/services/rag.py 同口径）。"""
    if not entries:
        return "（无）"
    lines: List[str] = []
    for message in entries[-rounds * 2:]:
        speaker = "用户" if message.get("role") == "user" else "助手"
        lines.append(f"{speaker}：{message.get('content', '')}")
    return "\n".join(lines)


def rewrite_system_prompt() -> str:
    """多轮改写系统提示：优先复用生产实现（app/services/rag.py），不可用时用本地副本。"""
    try:
        from app.services.rag import REWRITE_SYSTEM_PROMPT

        return REWRITE_SYSTEM_PROMPT
    except Exception:  # noqa: BLE001 - A/B 脚本不因生产模块重构而中断
        return (
            "你是检索查询改写助手。结合对话历史，把用户当前问题改写为不依赖上下文、语义完整、可独立检索的中文问句。"
            "若当前问题本身已语义完整（不依赖历史），原样输出。只输出改写后的问句，一行，不要任何解释。"
        )


def rewrite_question(client: Any, question: str, entries: List[Dict[str, str]]) -> Optional[str]:
    """LLM 改写（与生产同口径）：无历史/改写失败/无变化时返回 None（降级原文检索）。"""
    if not entries:
        return None
    try:
        result = client.chat(
            [
                {"role": "system", "content": rewrite_system_prompt()},
                {"role": "user", "content": f"【历史对话】\n{format_history_text(entries)}\n\n【当前问题】\n{question}"},
            ],
            temperature=0.0,
            max_tokens=64,
        )
    except Exception as exc:  # noqa: BLE001 - 改写失败不影响主链路
        print(f"  [警告] 改写失败，按原文检索：{exc}")
        return None
    rewritten = (result.content or "").strip().splitlines()[0].strip() if result.content else ""
    return rewritten if rewritten and rewritten != question else None


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
    def bigrams(text: str) -> set:
        compact = re.sub(r"[^\u4e00-\u9fa5]", "", text or "")
        return {compact[i : i + 2] for i in range(max(0, len(compact) - 1))}

    point_bigrams: set = set()
    for point in points:
        point_bigrams |= bigrams(point)
    covered = len(point_bigrams & bigrams(answer)) / max(1, len(point_bigrams))
    score = 1.0 if covered >= 0.7 else (0.5 if covered >= 0.4 else 0.0)
    return score, {"中文双字覆盖率": f"{covered:.0%}"}


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
def run_retrieval(record: Dict[str, Any], args: argparse.Namespace) -> List[Dict[str, Any]]:
    """检索模式：逐轮只取上下文，不做生成（不调用 LLM 改写，沿用简单拼接）。"""
    turns: List[Dict[str, Any]] = []
    previous = ""
    for index, expected in enumerate(record["expected"]):
        question = expected["question"]
        query = question if index == 0 else f"{previous} {question}"
        started = time.perf_counter()
        chunks = retrieve(query, top_k=args.top_k, score_threshold=args.threshold, use_rerank=args.rerank)
        elapsed = round((time.perf_counter() - started) * 1000)
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
                "latency_ms": elapsed,
            }
        )
        previous = question
    return turns


def run_offline(
    record: Dict[str, Any], args: argparse.Namespace, client: Any, system_prompt: str, template: Template
) -> List[Dict[str, Any]]:
    """离线直连：检索 →（可选改写）→ 上下文 → Prompt → DeepSeek（模拟 /api/ask 主链路）。

    --history-style text     历史按“用户：/助手：”文本注入 ${history}（与生产一致）；
    --history-style messages 历史作为 messages 数组注入，${history} 填「（无）」（备选方案）；
    --rewrite none|llm       是否用 LLM 把追问改写为可独立检索的问题（与生产同口径）。
    """
    history: List[Dict[str, str]] = []
    turns: List[Dict[str, Any]] = []
    for index, expected in enumerate(record["expected"]):
        question = expected["question"]
        rewritten = rewrite_question(client, question, history) if args.rewrite == "llm" else None
        if rewritten is None and index > 0 and args.rewrite == "none":
            query = f"{record['expected'][index - 1]['question']} {question}"  # 第2周基线：简单拼接
        else:
            query = rewritten or question

        started = time.perf_counter()
        chunks = retrieve(query, top_k=args.top_k, score_threshold=args.threshold, use_rerank=args.rerank)
        if not chunks:
            elapsed = round((time.perf_counter() - started) * 1000)
            turns.append(
                {
                    "question": question,
                    "query": query,
                    "rewritten_question": rewritten,
                    "answer": FALLBACK_ANSWER,
                    "answer_type": "not_found",
                    "used_indices": [],
                    "citations": [],
                    "retrieved": [],
                    "latency_ms": elapsed,
                    "model_called": False,
                }
            )
            history.append({"role": "user", "content": question})
            history.append({"role": "assistant", "content": FALLBACK_ANSWER})
            continue

        context = build_context(chunks)
        citations = build_citations(chunks)
        if args.history_style == "messages":
            history_text = "（无）"
            messages: List[Dict[str, str]] = [{"role": "system", "content": system_prompt}]
            messages += [dict(entry) for entry in history]
        else:
            history_text = format_history_text(history)
            messages = [{"role": "system", "content": system_prompt}]
        user_content = template.safe_substitute(history=history_text, context=context, question=question)
        result = client.chat(messages + [{"role": "user", "content": user_content}], temperature=0.2, max_tokens=512)
        elapsed = round((time.perf_counter() - started) * 1000)
        answer = result.content
        used = sorted({int(x) for x in CITE_RE.findall(answer)})
        turns.append(
            {
                "question": question,
                "query": query,
                "rewritten_question": rewritten,
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
        history.append({"role": "user", "content": question})
        history.append({"role": "assistant", "content": answer})
    return turns


def run_api(record: Dict[str, Any], args: argparse.Namespace) -> List[Dict[str, Any]]:
    """API 模式：调用运行中的 /api/ask（多轮题复用同一 session_id）。"""
    import requests  # 延迟导入，便于 retrieval/offline 模式在无 requests 环境运行

    session_id: Optional[str] = None
    turns: List[Dict[str, Any]] = []
    for expected in record["expected"]:
        question = expected["question"]
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
            raise RuntimeError(f"{record['id']} 调用失败：code={body.get('code')} message={body.get('message')}")
        data = body["data"]
        session_id = data.get("session_id")
        answer = data.get("answer") or ""
        turns.append(
            {
                "question": question,
                "query": data.get("rewritten_question") or question,
                "rewritten_question": data.get("rewritten_question"),
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
    """逐轮计算 M-01~M-04（自动部分）与多轮重复率。

    口径：M-01 以“轮”为单位（应可答轮的正确来源是否在 Top-5）；M-03 按逐轮 key_points 预评后取整题最低分；
    M-04 覆盖拒答轮；重复率 = 本轮答案与上一轮答案的 8 字片段重合占比（越低越好）。
    """
    def shingles(text: str, size: int = 8) -> set:
        compact = re.sub(r"\s+", "", text or "")
        return {compact[i : i + size] for i in range(max(0, len(compact) - size + 1))}

    m01_total = m01_hit = 0
    cite_total = cite_source_ok = cite_loc_ok = 0
    m03_scores: List[float] = []
    m04_total = m04_ok = 0
    repeat_ratios: List[float] = []
    latencies: List[float] = []
    record_hits: List[bool] = []

    for record in records:
        turn_hit_flags: List[bool] = []
        turn_scores: List[float] = []
        refusal_flags: List[bool] = []
        previous_answer: Optional[str] = None
        previous_was_answered = False
        for expected, turn in zip(record["expected"], record["turns"]):
            latencies.append(turn["latency_ms"])
            if expected["expected_source"]:  # 应可答轮
                hit = any(chunk["source_file"] == expected["expected_source"] for chunk in turn["retrieved"])
                turn_hit_flags.append(hit)
                m01_total += 1
                m01_hit += int(hit)
                for index in turn.get("used_indices") or []:
                    citation = next((c for c in turn.get("citations", []) if c.get("index") == index), None)
                    if citation is None:
                        continue
                    cite_total += 1
                    cite_source_ok += int(citation.get("source_file") == expected["expected_source"])
                    cite_loc_ok += int(locator_ok(expected.get("expected_location") or "", citation.get("location") or ""))
                if mode != "retrieval":
                    score, detail = score_key_points(turn.get("answer") or "", expected["key_points"])
                    turn["auto_score"] = score
                    turn["auto_score_detail"] = detail
                    turn_scores.append(score)
            else:  # 拒答轮
                answer = turn.get("answer") or ""
                if mode == "retrieval":
                    ok = not turn.get("retrieved")
                else:
                    ok = (
                        turn.get("answer_type") == "not_found"
                        and not turn.get("used_indices")
                        and not NUMBER_RE.search(answer)
                    )
                turn["refusal_ok"] = ok
                turn["retrieval_leak"] = bool(turn.get("retrieved"))
                refusal_flags.append(ok)
            if previous_answer and turn.get("answer") and turn.get("answer_type") == "answered" and previous_was_answered:
                current = shingles(turn["answer"])
                previous = shingles(previous_answer)
                ratio = len(current & previous) / max(1, len(current))
                turn["repeat_ratio"] = round(ratio, 3)
                repeat_ratios.append(ratio)
            previous_answer = turn.get("answer") or previous_answer or None
            previous_was_answered = turn.get("answer_type") == "answered"

        record["m01_hit"] = all(turn_hit_flags) if turn_hit_flags else None
        record["auto_score"] = min(turn_scores) if turn_scores else None
        record["m04_ok"] = all(refusal_flags) if refusal_flags else None
        if turn_hit_flags:
            record_hits.append(all(turn_hit_flags))
        if turn_scores:
            m03_scores.append(min(turn_scores))
        if refusal_flags:
            m04_total += 1
            m04_ok += int(all(refusal_flags))

    def percentile(values: List[float], ratio: float) -> Optional[float]:
        if not values:
            return None
        ordered = sorted(values)
        return ordered[min(len(ordered) - 1, int(len(ordered) * ratio))]

    return {
        "mode": mode,
        "total": len(records),
        "turns_total": sum(len(record["turns"]) for record in records),
        "answered_total": sum(1 for record in records if record["answer_type_expected"] == "answered"),
        "noanswer_total": sum(1 for record in records if record["answer_type_expected"] == "not_found"),
        "m01_hit": m01_hit,
        "m01_total": m01_total,
        "m01_rate": round(m01_hit / m01_total * 100, 1) if m01_total else None,
        "m01_items": sum(1 for hit in record_hits if hit),
        "m01_items_total": len(record_hits),
        "cite_total": cite_total,
        "cite_source_ok": cite_source_ok,
        "cite_source_rate": round(cite_source_ok / cite_total * 100, 1) if cite_total else None,
        "cite_location_ok": cite_loc_ok,
        "cite_location_rate": round(cite_loc_ok / cite_total * 100, 1) if cite_total else None,
        "m03_avg": round(sum(m03_scores) / len(m03_scores), 3) if m03_scores else None,
        "m03_full": sum(1 for score in m03_scores if score == 1.0),
        "m03_partial": sum(1 for score in m03_scores if score == 0.5),
        "m03_zero": sum(1 for score in m03_scores if score == 0.0),
        "m04_ok": m04_ok,
        "m04_total": m04_total,
        "m04_rate": round(m04_ok / m04_total * 100, 1) if m04_total else None,
        "repeat_avg": round(sum(repeat_ratios) / len(repeat_ratios) * 100, 1) if repeat_ratios else None,
        "repeat_over30": sum(1 for ratio in repeat_ratios if ratio > 0.3),
        "repeat_turns": len(repeat_ratios),
        "latency_median_ms": round(statistics.median(latencies)) if latencies else None,
        "latency_p95_ms": round(percentile(latencies, 0.95)) if latencies else None,
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
    m01 = f"{metrics['m01_hit']}/{metrics['m01_total']} = {metrics['m01_rate']}%（轮级）"
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
    m04 = f"{metrics['m04_ok']}/{metrics['m04_total']} = {metrics['m04_rate']}%（轮级）"
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


def print_repeat_summary(run: Dict[str, Any]) -> None:
    """多次采样汇总：指标 min/avg/max + 逐条稳定性 + 答案长度分布。"""
    metrics_list = run.get("repeat_metrics") or []
    if len(metrics_list) < 2:
        return

    def stat(key: str, suffix: str = "") -> str:
        values = [m.get(key) for m in metrics_list if m.get(key) is not None]
        if not values:
            return "—"
        return f"{min(values):.1f} / {sum(values) / len(values):.1f} / {max(values):.1f}{suffix}"

    print("\n== 多次采样汇总（min / avg / max） ==")
    print(f"M-01 命中率（轮级）：{stat('m01_rate', '%')}")
    print(f"M-03 自动预评均分：{stat('m03_avg')}")
    print(f"M-04 拒答率：{stat('m04_rate', '%')}")
    print(f"端到端中位时延：{stat('latency_median_ms', 'ms')}")
    print("\n逐条稳定性（M-01 命中次数 | 预评分序列 | 长度区间 | 超 200 字数）：")
    for item_id, stats in run["per_item_stats"].items():
        hits = stats["m01"]
        hit_text = f"{sum(hits)}/{len(hits)}" if hits else "—"
        scores = stats["scores"]
        score_text = "/".join(str(s) for s in scores) if scores else "—"
        lengths = stats["lengths"]
        length_text = f"{min(lengths)}~{max(lengths)}" if lengths else "—"
        print(f"  {item_id:8} M-01 {hit_text:5} 预评分 {score_text:14} 长度 {length_text:10} 超200：{stats['over200']}")


def print_summary(run: Dict[str, Any]) -> None:
    """打印逐条结果与控制台指标汇总（多轮集显示重复率）。"""
    metrics = run["metrics"]
    print(
        f"[模式] {metrics['mode']} | 数据集 {Path(run['dataset']).name} | TOP_K={settings.TOP_K} "
        f"阈值={settings.SCORE_THRESHOLD} RERANK={settings.RERANK_ENABLED} "
        f"历史={run.get('history_style')} 改写={run.get('rewrite')}"
    )
    print(f"{'ID':8} {'命中':4} {'评分':5} {'拒答':4} {'重复':6} {'时延':8} 摘要")
    for record in run["records"]:
        last = record["turns"][-1]
        answer = (last.get("answer") or ("（仅检索）" if last.get("retrieved") else "")).replace("\n", " ")[:30]
        hit = "√" if record.get("m01_hit") else ("×" if record.get("m01_hit") is not None else "—")
        score = record.get("auto_score")
        score_text = f"{score:.1f}" if isinstance(score, float) else "—"
        refusal = "√" if record.get("m04_ok") else ("×" if record.get("m04_ok") is not None else "—")
        repeats = [turn.get("repeat_ratio") for turn in record["turns"] if turn.get("repeat_ratio") is not None]
        repeat_text = f"{max(repeats) * 100:.0f}%" if repeats else "—"
        print(
            f"{record['id']:8} {hit:4} {score_text:5} {refusal:4} {repeat_text:6} {last['latency_ms']:>6}ms {answer}"
        )
    print("\n== 指标汇总（自动预判，M-02/M-03 以人工复核为准）==")
    print(f"M-01 检索命中率（轮级）  = {metrics['m01_hit']}/{metrics['m01_total']} = {metrics['m01_rate']}%")
    if metrics["cite_total"]:
        print(
            f"M-02 引用来源预检        = {metrics['cite_source_ok']}/{metrics['cite_total']} = {metrics['cite_source_rate']}%"
            f"（位置覆盖 {metrics['cite_location_rate']}%）"
        )
    if metrics["m03_avg"] is not None:
        print(
            f"M-03 答案自动预评        = 均分 {metrics['m03_avg']}（完整 {metrics['m03_full']} / 部分 {metrics['m03_partial']} / 错误 {metrics['m03_zero']}）"
        )
    if metrics["m04_total"]:
        print(f"M-04 拒答正确率（轮级）  = {metrics['m04_ok']}/{metrics['m04_total']} = {metrics['m04_rate']}%")
    if metrics["repeat_avg"] is not None:
        print(
            f"多轮重复率（8 字片段）   = 平均 {metrics['repeat_avg']}%；超过 30% 的轮次 {metrics['repeat_over30']}/{metrics['repeat_turns']}"
        )
    if metrics["latency_median_ms"]:
        print(f"时延（辅助）             = 中位 {metrics['latency_median_ms']}ms / P95 {metrics['latency_p95_ms']}ms")


def main(argv: Optional[List[str]] = None) -> int:
    """脚本入口：选择运行模式，逐条评测并输出明细与指标（--repeat N 做多次采样）。"""
    args = parse_args(sys.argv[1:] if argv is None else argv)
    dataset_path = Path(args.dataset).resolve()
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

    iterations = max(1, int(args.repeat))
    run: Dict[str, Any] = {
        "started_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "mode": mode,
        "dataset": str(dataset_path),
        "history_style": args.history_style if mode == "offline" else "api",
        "rewrite": args.rewrite if mode == "offline" else "api",
        "repeat": iterations,
        "records": [],
    }
    repeat_metrics: List[Dict[str, Any]] = []
    per_item: Dict[str, Dict[str, Any]] = {}
    for iteration in range(1, iterations + 1):
        if iterations > 1:
            print(f"—— 第 {iteration}/{iterations} 次采样 ——")
        records = load_dataset(dataset_path, args.limit)
        for index, record in enumerate(records, start=1):
            print(f"[{index}/{len(records)}] {record['id']} {record['question']}")
            if mode == "retrieval":
                turns = run_retrieval(record, args)
            elif mode == "offline":
                turns = run_offline(record, args, client, system_prompt, template)
            else:
                turns = run_api(record, args)
            record["turns"] = turns
            if args.sleep:
                time.sleep(args.sleep)
        metrics = compute_metrics(records, mode)
        repeat_metrics.append(metrics)
        for record in records:
            stats = per_item.setdefault(record["id"], {"m01": [], "scores": [], "lengths": [], "over200": 0})
            if record.get("m01_hit") is not None:
                stats["m01"].append(bool(record["m01_hit"]))
            if record.get("auto_score") is not None:
                stats["scores"].append(record["auto_score"])
            for turn in record["turns"]:
                answer = turn.get("answer") or ""
                if answer and turn.get("answer_type") != "not_found":
                    stats["lengths"].append(len(answer))
                    if len(answer) > 200:
                        stats["over200"] += 1
        run["records"] = records

    run["metrics"] = repeat_metrics[-1]
    run["repeat_metrics"] = repeat_metrics
    run["per_item_stats"] = per_item
    print_summary(run)
    if iterations > 1:
        print_repeat_summary(run)

    out_path = Path(args.out) if args.out else DEFAULT_OUT_DIR / f"eval_rag_{dataset_path.stem}_{mode}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
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