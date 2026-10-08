# -*- coding: utf-8 -*-
"""前后端联调自测（UI 主责）——对应 W2-11 / W2-12 的验收证据。

前提：后端已在 `WEB_API_BASE`（默认 http://127.0.0.1:8000）运行，且知识库已建好。
做的事：用**前端真实的调用代码**（web/api_client.py）打真实接口，逐项检查界面依赖的字段，
并把结果打印成可直接贴进联调记录的形式。

运行（仓库根目录）：
    python web/live_check.py                 # 只读检查：健康 + 文档列表 + 三条问答
    python web/live_check.py --upload 文件   # 另外实测一次上传（谨慎：会再次入库）
    python web/live_check.py --no-ui         # 只查接口，不跑页面级渲染检查

退出码：0 = 通过；1 = 有断言失败；2 = 后端未启动（跳过，不算失败）。
"""
from __future__ import annotations

import os
import re
import sys
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:  # noqa: BLE001
        pass

sys.path.insert(0, str(Path(__file__).resolve().parent))
from api_client import ApiClient, ApiError  # noqa: E402

BASE = os.getenv("WEB_API_BASE", "http://127.0.0.1:8000")

#: 用例：(问题, 期望 answer_type)
CASES = [
    ("公司年假有多少天？", "answered"),
    ("出差住宿标准是多少？", "answered"),
    ("公司食堂几点开饭？", "not_found"),
]

RESULTS: list[tuple[bool, str, str]] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    RESULTS.append((ok, name, detail))
    print(f"{'✅' if ok else '❌'} {name}" + (f"\n      {detail}" if detail else ""))


def ui_stage(client: ApiClient, base: str) -> None:
    """页面级联调：用 Streamlit 官方测试运行器让**真实页面**读**真实后端**数据。

    这一步回答的是"界面上到底看不看得见"——API 通了不等于页面渲染对。
    不依赖浏览器，可在任何机器上复现（浏览器点击实测由人工在周会前补）。
    """
    print("\n" + "=" * 60 + "\n页面级联调（真实后端数据 → 真实页面渲染）")
    try:
        import warnings
        warnings.filterwarnings("ignore")
        from streamlit.testing.v1 import AppTest
    except ImportError:
        check("页面级联调", False, "未安装 streamlit，跳过")
        return

    os.environ["WEB_API_BASE"] = base
    web_dir = Path(__file__).resolve().parent

    at = AppTest.from_file(str(web_dir / "app.py"), default_timeout=120)
    at.run()
    at.chat_input[0].set_value(CASES[0][0]).run()
    texts = [m.value for m in at.markdown]
    labels = [e.label for e in at.expander]
    check("问答页：无异常", not at.exception, str([e.value for e in at.exception]))
    check("问答页：渲染出答案正文", any("年假" in x for x in texts))
    check("问答页：显示三态徽章", any("已找到依据" in x for x in texts))
    check("问答页：引用折叠条含文件名与位置", any("01_员工手册.pdf" in lb for lb in labels), str(labels[:2]))

    kb = AppTest.from_file(str(web_dir / "pages" / "1_知识库管理.py"), default_timeout=120)
    kb.run()
    rendered = " ".join([m.value for m in kb.markdown] + [c.value for c in kb.caption])
    check("知识库管理页：无异常", not kb.exception, str([e.value for e in kb.exception]))
    check("知识库管理页：渲染出文档列表", "01_员工手册.pdf" in rendered and "03_报销制度与费用标准.xlsx" in rendered)


def main() -> int:
    client = ApiClient(BASE)

    print(f"联调目标：{BASE}\n" + "-" * 60)
    health = client.health()
    if not health.get("ok"):
        print(f"⚠️  后端不可用或状态异常：{health.get('detail') or health.get('status')}")
        print("    请先启动后端：python -m uvicorn app.main:app --port 8000")
        return 2
    print(f"健康检查：status={health.get('status')} version={health.get('version')} 切片数={health.get('chunk_count')}")
    check("四项依赖全部 ok", all(v == "ok" for v in health["components"].values()), str(health["components"]))

    docs = client.list_documents()
    items = docs.get("items", [])
    print(f"\n知识库：共 {docs['total']} 份文档")
    for it in items:
        print(f"   - {it['filename']:<34} {it['file_type']:<5} {it['chunk_count']:>3} 切片  {it['status']}")
    check("文档列表有数据且字段齐全", bool(items) and all(
        it.get("doc_id") and it.get("filename") and it.get("status") for it in items), f"{len(items)} 条")

    for question, expected in CASES:
        print("\n" + "-" * 60)
        print(f"提问：{question}（期望 answer_type={expected}）")
        try:
            a = client.ask(question, session_id="conv_live_check")
        except ApiError as exc:
            check(f"[{question}] 接口正常返回", False, f"{exc.code} {exc.message} {exc.hint}")
            continue

        latency = a["latency_ms"]
        total_ms = latency.get("total") if isinstance(latency, dict) else latency
        print(f"   answer_type={a['answer_type']} 耗时={total_ms}ms 模型={a['model']}")
        print("   答案：" + (a["answer"] or "").replace("\n", " ")[:100])

        check(f"[{question}] answer_type 符合预期", a["answer_type"] == expected, a["answer_type"])
        check(f"[{question}] 答案非空", bool((a["answer"] or "").strip()))
        check(f"[{question}] 界面需要的元信息齐全",
              bool(a.get("message_id")) and bool(a.get("trace_id")) and total_ms is not None)

        if expected == "answered":
            cites = a["citations"]
            check(f"[{question}] 至少 1 条引用（FR-CIT-01）", len(cites) >= 1, f"{len(cites)} 条")
            missing = [c for c in cites if not c.get("source_file") or not c.get("location") or not c.get("snippet")]
            check(f"[{question}] 引用含 文件名/位置/原文片段（FR-CIT-02/03）", not missing, str(missing))
            numbers = {int(n) for n in re.findall(r"\[(\d{1,2})\]", a["answer"] or "")}
            cite_indexes = {c["index"] for c in cites}
            check(f"[{question}] 答案编号与引用编号一一对应（M-02）",
                  bool(numbers) and numbers <= cite_indexes, f"答案编号={sorted(numbers)} 引用编号={sorted(cite_indexes)}")
            for c in cites:
                print(f"   引用[{c['index']}] {c['source_file']} · {c['location']} · {c['score']}")
        else:
            check(f"[{question}] 兜底回答不带引用（不编造来源）", not a["citations"])

    if "--upload" in sys.argv:
        path = Path(sys.argv[sys.argv.index("--upload") + 1])
        print("\n" + "-" * 60)
        print(f"上传实测：{path.name}")
        try:
            res = client.upload([(path.name, path.read_bytes(), "application/octet-stream")])
            for it in res["items"]:
                flag = "成功" if it.get("status") == "success" else "失败"
                print(f"   {flag} {it['filename']}（{it.get('chunk_count', 0)} 切片，{it.get('elapsed_ms')}ms）{it.get('error_message') or ''}")
            check("上传结果字段齐全", all("filename" in it and "status" in it for it in res["items"]))
        except ApiError as exc:
            check("上传接口正常返回", False, f"{exc.code} {exc.message}")

    if "--no-ui" not in sys.argv:
        ui_stage(client, os.environ.get("WEB_API_BASE", BASE))

    passed = sum(1 for ok, _, _ in RESULTS if ok)
    print("\n" + "=" * 60)
    print(f"联调自测：{passed}/{len(RESULTS)} 项通过")
    return 0 if passed == len(RESULTS) else 1


if __name__ == "__main__":
    raise SystemExit(main())