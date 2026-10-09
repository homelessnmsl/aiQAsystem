"""接口稳定性压测脚本（W4-05；M-08：连续提问 50 次不崩溃、错误率 < 2%）

用法（仓库根目录，后端已启动）：
    python scripts/stress_ask.py --count 50
    python scripts/stress_ask.py --count 50 --base-url http://127.0.0.1:8000

说明：
- 复现"连续提问"场景：可答题 / 拒答题轮换，每两题共用一个会话（覆盖多轮路径）；
- 统计成功率、时延（中位 / P95 / 最大）、answer_type 分布与错误明细；
- 原始明细保存 data/eval/stress_<时间戳>.json；错误率 ≥ 2% 时退出码为 1；
- 默认跑完清理本次压测产生的会话（sqlite，session_id 前缀 stress_；--no-cleanup 可关闭）。
"""
from __future__ import annotations

import argparse
import json
import sqlite3
import statistics
import sys
import time
from datetime import datetime
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app.core.config import settings  # noqa: E402

#: 轮换题库：可答 8 条 + 拒答 4 条（与演示 QA 集同源）
ANSWERABLE_QUESTIONS = [
    "公司年假有多少天？",
    "出差住宿标准是多少？",
    "公司的标准工作时间是几点到几点？",
    "试用期转正要走哪些流程？",
    "报销审批要走哪几步？",
    "年假需要提前多久申请？",
    "通讯补贴的标准是多少？",
    "入职当天需要完成哪些事项？",
]
NOT_FOUND_QUESTIONS = [
    "公司食堂几点开饭？",
    "公司附近有什么好吃的推荐吗？",
    "员工可以带宠物上班吗？",
    "公司班车路线经过哪些站点？",
]


def _percentile(values, ratio: float) -> int:
    if not values:
        return 0
    ordered = sorted(values)
    position = max(0, int(len(ordered) * ratio) - 1)
    return int(ordered[position])


def _cleanup_sessions(prefix: str = "stress_") -> int:
    """清理压测产生的会话与消息（本地 sqlite；失败不抛出）"""
    try:
        conn = sqlite3.connect(str(settings.sqlite_file))
        cursor = conn.execute("DELETE FROM messages WHERE session_id LIKE ?", (f"{prefix}%",))
        removed = cursor.rowcount
        conn.execute("DELETE FROM conversations WHERE session_id LIKE ?", (f"{prefix}%",))
        conn.commit()
        conn.close()
        return int(removed)
    except Exception as exc:  # noqa: BLE001 - 清理失败不影响压测结论
        print(f"[压测] 会话清理失败（可忽略）：{exc}")
        return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="连续提问稳定性压测（M-08）")
    parser.add_argument("--count", type=int, default=50, help="提问次数（默认 50）")
    parser.add_argument("--base-url", default="http://127.0.0.1:8000", help="后端地址")
    parser.add_argument("--timeout", type=int, default=60, help="单次请求超时秒数")
    parser.add_argument("--no-cleanup", action="store_true", help="不清理本次压测会话")
    args = parser.parse_args()

    pool = []
    while len(pool) < args.count:
        pool.extend(ANSWERABLE_QUESTIONS)
        pool.extend(NOT_FOUND_QUESTIONS)
    pool = pool[: args.count]

    print(f"[压测] 目标：{args.base_url}｜次数：{args.count}｜开始：{datetime.now():%Y-%m-%d %H:%M:%S}")
    records = []
    errors = []
    started_all = time.perf_counter()

    for index, question in enumerate(pool, start=1):
        session_id = f"stress_{(index - 1) // 2}"  # 每两题共用一个会话：覆盖多轮路径
        t0 = time.perf_counter()
        record = {"index": index, "question": question, "session_id": session_id, "ok": False}
        try:
            resp = requests.post(
                f"{args.base_url}/api/ask",
                json={"question": question, "session_id": session_id},
                timeout=args.timeout,
            )
            elapsed_ms = int((time.perf_counter() - t0) * 1000)
            record["http_status"] = resp.status_code
            record["elapsed_ms"] = elapsed_ms
            try:
                payload = resp.json()
                record["code"] = payload.get("code")
                data = payload.get("data") or {}
                record["answer_type"] = data.get("answer_type")
                record["latency_ms"] = (data.get("latency_ms") or {}).get("total")
            except ValueError:
                record["error"] = "响应不是合法 JSON"
            record["ok"] = resp.status_code == 200 and record.get("code") == 0
            if not record["ok"]:
                errors.append(record)
            print(f"  {index:>3}/{args.count}  {str(record.get('answer_type') or 'error'):<10} {elapsed_ms:>5}ms  {question}")
        except Exception as exc:  # noqa: BLE001 - 压测脚本记录所有异常
            elapsed_ms = int((time.perf_counter() - t0) * 1000)
            record.update({"error": f"{type(exc).__name__}: {exc}", "elapsed_ms": elapsed_ms})
            errors.append(record)
            print(f"  {index:>3}/{args.count}  ERROR      {elapsed_ms:>5}ms  {question} -> {exc}")

        records.append(record)

    total_seconds = time.perf_counter() - started_all
    latencies = [r["elapsed_ms"] for r in records]
    success = len(records) - len(errors)
    error_rate = len(errors) / len(records) if records else 0.0

    answer_types = {}
    for record in records:
        key = record.get("answer_type") or ("error" if not record.get("ok") else "unknown")
        answer_types[key] = answer_types.get(key, 0) + 1

    summary = {
        "started_at": datetime.now().isoformat(timespec="seconds"),
        "base_url": args.base_url,
        "count": len(records),
        "success": success,
        "errors": len(errors),
        "error_rate": round(error_rate, 4),
        "answered": answer_types.get("answered", 0),
        "not_found": answer_types.get("not_found", 0),
        "other": {k: v for k, v in answer_types.items() if k not in ("answered", "not_found")},
        "latency_ms": {
            "median": int(statistics.median(latencies)) if latencies else 0,
            "p95": _percentile(latencies, 0.95),
            "max": max(latencies) if latencies else 0,
        },
        "total_seconds": round(total_seconds, 1),
    }

    out_dir = ROOT / "data" / "eval"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_file = out_dir / f"stress_{datetime.now():%Y%m%d_%H%M%S}.json"
    out_file.write_text(
        json.dumps({"summary": summary, "error_details": errors, "records": records}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    print("\n===== 汇总（M-08：错误率 < 2%）=====")
    print(f"总请求 {summary['count']}｜成功 {success}｜失败 {len(errors)}｜错误率 {error_rate:.1%}")
    print(f"answer_type：answered {summary['answered']}｜not_found {summary['not_found']}｜其它 {summary['other']}")
    print(f"时延（端到端）：中位 {summary['latency_ms']['median']}ms｜P95 {summary['latency_ms']['p95']}ms｜最大 {summary['latency_ms']['max']}ms")
    print(f"总耗时 {total_seconds:.1f}s｜明细：{out_file}")
    if errors:
        print("\n错误明细（前 5 条）：")
        for record in errors[:5]:
            detail = record.get("error") or f"HTTP {record.get('http_status')} code={record.get('code')}"
            print(f"  #{record['index']} {record['question']} -> {detail}")

    if not args.no_cleanup:
        removed = _cleanup_sessions()
        print(f"已清理本次压测会话与消息（messages {removed} 条，前缀 stress_）")

    passed = error_rate < 0.02
    print(f"\n结论：{'达标 [OK]' if passed else '未达标 [NG]'}（错误率 {error_rate:.1%}，阈值 2%）")
    return 0 if passed else 1


if __name__ == "__main__":
    sys.exit(main())
