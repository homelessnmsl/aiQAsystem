"""问答页（主页）— UI 智能体交互工程师 · W1-18 交付物

运行：在仓库根目录执行  ``python -m streamlit run web/app.py``
依赖：streamlit、requests（见仓库根 requirements.txt；未安装时先 pip install streamlit requests）

本页面对齐：
- 需求 FR-UI-01（提问框 + 对话流 + 引用区）、FR-UI-03（加载/空/错误态）、
  FR-UI-04（引用折叠条）、FR-UI-05（演示模式）、FR-CIT-03（引用可展开核对）；
- 架构 5.1 接口清单（/api/ask、/api/chat、/api/feedback）、8.3 失败降级文案。

本骨架在**后端未启动**时也不会崩：无后端时给出中文提示并引导开启演示模式（断网可演示）。
"""

from __future__ import annotations

import json
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

import streamlit as st

WEB_DIR = Path(__file__).resolve().parent
if str(WEB_DIR) not in sys.path:  # 让 web/ 下的 api_client 与 components 可被 import
    sys.path.insert(0, str(WEB_DIR))

from api_client import DEFAULT_BASE_URL, ApiClient, ApiError  # noqa: E402
from components import citations as cite_ui  # noqa: E402
from components import states  # noqa: E402

DEMO_FILE = WEB_DIR / "data" / "demo_answers.json"
EXAMPLE_QUESTIONS = ["公司年假有多少天？", "出差住宿标准是多少？", "试用期转正要走哪些流程？"]

st.set_page_config(page_title="企业知识库智能问答", page_icon="💬", layout="wide")

# 精简 Streamlit 默认外壳，让演示界面更像业务系统
st.markdown(
    """
    <style>
      #MainMenu, footer {visibility: hidden;}
      .block-container {padding-top: 2.2rem; padding-bottom: 6rem; max-width: 1080px;}
      div[data-testid="stChatMessage"] {border-radius: 12px; padding: 6px 4px;}
      div[data-testid="stExpander"] {border-radius: 10px;}
    </style>
    """,
    unsafe_allow_html=True,
)


# --------------------------------------------------------------------------- #
# 状态与工具
# --------------------------------------------------------------------------- #
def new_session_id() -> str:
    return "conv_web_" + datetime.now().strftime("%Y%m%d_%H%M%S")


@st.cache_data(show_spinner=False)
def load_demo_items() -> List[Dict[str, Any]]:
    """演示模式预置问答（FR-UI-05）。"""
    try:
        payload = json.loads(DEMO_FILE.read_text(encoding="utf-8"))
        return list(payload.get("items", []))
    except Exception:  # noqa: BLE001 - 演示数据缺失不应导致页面崩溃
        return []


@st.cache_resource(show_spinner=False)
def get_client(base_url: str) -> ApiClient:
    return ApiClient(base_url)


def init_state() -> None:
    ss = st.session_state
    ss.setdefault("messages", [])
    ss.setdefault("session_id", new_session_id())
    ss.setdefault("demo_mode", False)
    ss.setdefault("pending_question", "")
    ss.setdefault("pending_is_retry", False)
    ss.setdefault("last_question", "")
    ss.setdefault("api_base", DEFAULT_BASE_URL)
    ss.setdefault("health", None)
    ss.setdefault("doc_summary", None)


def current_client() -> ApiClient:
    return get_client(st.session_state.api_base)


def match_demo(question: str) -> Dict[str, Any]:
    """按关键词匹配预置问答；匹配不到就走"未找到依据"的兜底演示。"""
    items = load_demo_items()
    if not items:
        return {"answer": "（演示数据文件缺失，请检查 web/data/demo_answers.json）", "answer_type": "not_found", "citations": [], "retrieved": []}
    text = question.strip()
    best: Optional[Dict[str, Any]] = None
    best_score = 0
    for item in items:
        score = sum(len(kw) for kw in item.get("keywords", []) if kw and kw in text)
        if text == item.get("question"):
            score += 100
        if score > best_score:
            best, best_score = item, score
    if best is None:
        best = next((i for i in items if i.get("answer_type") == "not_found"), items[-1])
    return dict(best)


# --------------------------------------------------------------------------- #
# 渲染：一次回答
# --------------------------------------------------------------------------- #
def render_assistant_message(message: Dict[str, Any]) -> None:
    answer_type = message.get("answer_type", "answered")
    st.markdown(states.answer_type_badge(answer_type), unsafe_allow_html=True)

    citations = message.get("citations") or []
    body = message.get("answer", "")

    if answer_type == "not_found":
        states.not_found_notice(body)
    elif answer_type == "clarify":
        states.clarify_notice(body)
        cite_ui.render_citations(citations)
    else:
        cite_ui.render_answer(body, citations)

    cite_ui.render_retrieved(message.get("retrieved") or [])
    cite_ui.render_answer_meta(message)
    if answer_type != "not_found":
        cite_ui.render_feedback(current_client(), message)


def render_history() -> None:
    for message in st.session_state.messages:
        with st.chat_message(message.get("role", "assistant")):
            if message.get("role") == "user":
                st.markdown(message.get("content", ""))
            else:
                render_assistant_message(message)


def run_turn(question: str, *, is_retry: bool = False) -> None:
    """一轮问答：记录提问 → 检索/生成 → 渲染答案与引用 → 落 session_state。"""
    ss = st.session_state
    ss["last_question"] = question

    if not is_retry:
        ss["messages"].append({"role": "user", "content": question})
        with st.chat_message("user"):
            st.markdown(question)

    with st.chat_message("assistant"):
        if ss["demo_mode"]:
            reply: Dict[str, Any] = match_demo(question)
        else:
            try:
                with st.spinner("正在检索知识库…"):
                    reply = current_client().ask(question, session_id=ss["session_id"])
            except ApiError as exc:
                if states.error_notice(exc, retry_label="重试这次提问"):
                    ss["pending_question"] = question
                    ss["pending_is_retry"] = True
                    st.rerun()
                return

        reply = dict(reply)
        reply["session_id"] = ss["session_id"]  # 演示数据里的 session_id 统一替换成本次会话
        render_assistant_message(reply)
        ss["messages"].append({"role": "assistant", **reply})


# --------------------------------------------------------------------------- #
# 侧栏：连接状态 / 会话 / 演示模式 / 知识库概况
# --------------------------------------------------------------------------- #
def render_sidebar() -> None:
    ss = st.session_state
    with st.sidebar:
        st.markdown("### 💬 企业知识库智能问答")
        st.caption("Streamlit 前端骨架 · 第1周 UI 交付")

        st.divider()
        st.markdown("**服务连接**")
        ss["api_base"] = st.text_input("后端地址", value=ss["api_base"], help="对应环境变量 WEB_API_BASE")
        col_a, col_b = st.columns(2)
        with col_a:
            if st.button("检查连接", use_container_width=True):
                ss["health"] = current_client().health()
        with col_b:
            if st.button("刷新", use_container_width=True):
                st.cache_data.clear()
                ss["doc_summary"] = None
                ss["health"] = current_client().health()
        if ss["health"] is None:
            ss["health"] = current_client().health()
        states.backend_status_badge(ss["health"] or {})

        st.divider()
        st.markdown("**演示模式**")
        ss["demo_mode"] = st.toggle(
            "使用预置问答（断网可演示）",
            value=ss["demo_mode"],
            help="对应需求 FR-UI-05 / US-14：答辩现场网络异常时展示预置的带引用答案。",
        )

        st.divider()
        st.markdown("**会话**")
        st.caption(f"当前会话：`{ss['session_id']}`")
        col_1, col_2 = st.columns(2)
        with col_1:
            if st.button("新建会话", use_container_width=True):
                ss["messages"] = []
                ss["session_id"] = new_session_id()
                ss["pending_question"] = ""
                st.rerun()
        with col_2:
            if st.button("清空对话", use_container_width=True):
                ss["messages"] = []
                st.rerun()

        st.divider()
        st.markdown("**知识库概况**")
        if ss["doc_summary"] is None:
            try:
                data = current_client().list_documents()
                items = data.get("items", [])
                chunks = sum(int(i.get("chunk_count") or 0) for i in items if isinstance(i, dict))
                ss["doc_summary"] = {"ok": True, "count": len(items), "chunks": chunks}
            except ApiError as exc:
                ss["doc_summary"] = {"ok": False, "detail": exc.display}
        summary = ss["doc_summary"] or {}
        if summary.get("ok"):
            st.metric("已入库文档", summary.get("count", 0), f"{summary.get('chunks', 0)} 个切片")
        else:
            st.caption("暂时读不到知识库状态（/api/documents 为第2周交付）：")
            st.caption(str(summary.get("detail", ""))[:120])
        st.page_link("pages/1_知识库管理.py", label="前往知识库管理", icon="📚")

        st.divider()
        st.caption("答案由 AI 依据知识库内容生成，请以引用原文为准。")


# --------------------------------------------------------------------------- #
# 主流程
# --------------------------------------------------------------------------- #
def main() -> None:
    init_state()
    render_sidebar()
    ss = st.session_state

    if ss["demo_mode"]:
        states.demo_banner()

    states.page_header(
        "企业知识库智能问答",
        "上传公司文档后即可提问；答案会标注来源文件与页码 / 工作表 / 行号，点开引用即可核对原文。",
    )

    if not ss["messages"]:
        states.empty_chat_state(EXAMPLE_QUESTIONS)

    render_history()

    question = st.chat_input("请输入你的问题，例如：公司年假有多少天？")
    is_retry = False
    if not question and ss.get("pending_question"):
        question = ss.pop("pending_question")
        is_retry = bool(ss.pop("pending_is_retry", False))

    if question:
        run_turn(str(question), is_retry=is_retry)


main()