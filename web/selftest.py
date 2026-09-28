"""前端骨架自测脚本（UI 主责）——W1-18 验收用。

作用：用 Streamlit 官方测试运行器（AppTest）真实执行页面脚本，
逐项检查「空态 / 错误态 / 演示模式 / 引用折叠 / 兜底态」是否按设计渲染，
全程**不需要启动后端**（后端未就绪正是第1周的默认状态）。

运行（在仓库根目录）：
    python web/selftest.py

退出码 0 = 全部通过；非 0 = 有断言失败，输出中文说明。
"""

from __future__ import annotations

import sys
import warnings
from pathlib import Path

WEB_DIR = Path(__file__).resolve().parent
REPO_ROOT = WEB_DIR.parent
sys.path.insert(0, str(WEB_DIR))

warnings.filterwarnings("ignore")

try:
    from streamlit.testing.v1 import AppTest
except ImportError:  # pragma: no cover
    print("未安装 streamlit，请先执行：pip install -r requirements.txt")
    raise SystemExit(2)

FAILURES: list[str] = []
CHECKS: list[str] = []


def check(name: str, condition: bool, detail: str = "") -> None:
    CHECKS.append(name)
    print(f"{'✅' if condition else '❌'} {name}" + (f" — {detail}" if detail and not condition else ""))
    if not condition:
        FAILURES.append(name)


def no_exception(at, label: str) -> None:
    errors = [e.value for e in at.exception]
    check(f"{label}：脚本无异常", not errors, str(errors))


def test_chat_page() -> None:
    print("\n[1/4] 问答页：首次进入（空态 + 加载骨架）")
    at = AppTest.from_file(str(WEB_DIR / "app.py"), default_timeout=90)
    at.run()
    no_exception(at, "问答页")
    texts = [m.value for m in at.markdown]
    check("显示欢迎空态", any("问问公司文档里的那些事" in t for t in texts))
    check("提供 3 个示例问题", len([b for b in at.button if b.label.endswith("？")]) >= 3)
    check("有提问输入框", len(at.chat_input) > 0)

    print("\n[2/4] 问答页：后端未启动时的错误态")
    at.chat_input[0].set_value("公司年假有多少天？").run()
    errs = [e.value for e in at.error]
    check("给出中文错误提示（不暴露堆栈）", any("无法连接后端服务" in e for e in errs))
    check("提供重试入口", any("重试" in b.label for b in at.button))

    print("\n[3/4] 问答页：演示模式（断网可演示，FR-UI-05）")
    at2 = AppTest.from_file(str(WEB_DIR / "app.py"), default_timeout=90)
    at2.run()
    at2.toggle[0].set_value(True).run()
    check("显示演示模式横幅", any("演示模式已开启" in w.value for w in at2.warning))
    at2.chat_input[0].set_value("公司年假有多少天？").run()
    no_exception(at2, "演示模式提问")
    texts = [m.value for m in at2.markdown]
    check("返回预置答案（含年假天数）", any("5 天" in t for t in texts))
    check("答案带三态徽章", any("已找到依据" in t for t in texts))
    check("引用折叠条含文件名与页码", any("01_员工手册.pdf" in e.label for e in at2.expander))
    check("提供检索详情与反馈入口", any("检索详情" in e.label for e in at2.expander))

    at2.chat_input[0].set_value("公司食堂几点开饭？").run()
    check("无依据时走兜底（不编造）", any("未找到依据" in m.value for m in at2.markdown))
    no_exception(at2, "兜底提问")


def test_kb_page() -> None:
    print("\n[4/4] 知识库管理页：上传区 + 空态")
    kb = AppTest.from_file(str(WEB_DIR / "pages" / "1_知识库管理.py"), default_timeout=90)
    kb.run()
    no_exception(kb, "知识库管理页")
    check("标题正确", [t.value for t in kb.title] == ["📚 知识库管理"])
    check("有上传控件", len(kb.get("file_uploader")) > 0)
    infos = " ".join(i.value for i in kb.info)
    check("读不到文档列表时给中文提示（不崩）", "暂时读不到文档列表" in infos or "知识库还没有文档" in infos)


def test_api_client() -> None:
    print("\n[附加] api_client：统一响应解析与中文错误映射")
    from api_client import ApiClient, ApiError, validate_files

    client = ApiClient("http://127.0.0.1:8000")
    health = client.health()
    check("health() 不抛异常（后端未启动也安全）", isinstance(health, dict) and "ok" in health)

    data = ApiClient._unwrap({"code": 0, "message": "success", "data": {"answer": "ok"}})
    check("正常响应可拆包", data.get("answer") == "ok")

    try:
        ApiClient._unwrap({"code": 2001, "message": "", "data": None})
    except ApiError as exc:
        check("业务错误码翻译成中文提示", "知识库" in exc.display, exc.display)
    else:
        check("业务错误码翻译成中文提示", False, "未抛出 ApiError")

    class _FakeFile:
        def __init__(self, name: str, size_bytes: int) -> None:
            self.name, self.size = name, size_bytes

    problems = validate_files([_FakeFile("报表.xls", 1024), _FakeFile("大文件.pdf", 30 * 1024 * 1024)])
    check("客户端先校验格式与大小（US-02）", len(problems) == 2, str(problems))


if __name__ == "__main__":
    test_chat_page()
    test_kb_page()
    test_api_client()
    print("\n" + "=" * 56)
    if FAILURES:
        print(f"❌ 未通过 {len(FAILURES)} 项：" + "；".join(FAILURES))
        raise SystemExit(1)
    print(f"✅ 前端骨架自测全部通过（{len(CHECKS)} 项）")