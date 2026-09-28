"""页面状态与提示组件（需求 FR-UI-03：空态 / 加载态 / 错误态必有）。

文案原则（需求 8.3）：面向业务用户、说清"为什么 + 怎么办"、不出现堆栈与技术术语。
"""

from __future__ import annotations

from typing import Any, Optional, Sequence

import streamlit as st

from api_client import ApiError

#: answer_type 三态（架构 6.10）→ 徽章文案与颜色
ANSWER_TYPE_META = {
    "answered": ("已找到依据", "#15803D", "#DCFCE7"),
    "not_found": ("未找到依据", "#B45309", "#FEF3C7"),
    "clarify": ("需要补充信息", "#1D4ED8", "#DBEAFE"),
}


def badge(text: str, fg: str, bg: str) -> str:
    """返回一个内联徽章 HTML（配合 st.markdown(..., unsafe_allow_html=True)）。"""
    return (
        f'<span style="display:inline-block;padding:2px 10px;border-radius:999px;'
        f'font-size:12px;font-weight:600;color:{fg};background:{bg};'
        f'border:1px solid {fg}33;">{text}</span>'
    )


def answer_type_badge(answer_type: str) -> str:
    label, fg, bg = ANSWER_TYPE_META.get(answer_type, ANSWER_TYPE_META["answered"])
    return badge(label, fg, bg)


def page_header(title: str, subtitle: str) -> None:
    st.markdown(f"### {title}")
    st.caption(subtitle)


def demo_banner() -> None:
    """演示模式横幅（FR-UI-05 / US-14：断网也能讲完流程）。"""
    st.warning(
        "**演示模式已开启**：回答来自预置数据（不是实时检索），"
        "用于答辩现场断网时演示完整流程。关闭后恢复真实问答。"
    )


def backend_unavailable(detail: str = "") -> None:
    st.error(
        "**后端服务未连接**：请先启动后端（默认 `127.0.0.1:8000`），"
        "或在左侧打开「演示模式」用预置问答演示。"
    )
    if detail:
        with st.expander("技术细节（排障用）"):
            st.code(str(detail))


def empty_knowledge_state(on_goto: bool = True) -> None:
    """知识库为空时的空态（需求 8.2 空态：给跳转按钮）。"""
    st.info(
        "**知识库还是空的**：请先到「知识库管理」页上传公司文档，"
        "之后就能针对文档内容提问了。"
    )
    if on_goto:
        st.page_link("pages/1_知识库管理.py", label="前往「知识库管理」上传文档", icon="📚")


def empty_chat_state(examples: Sequence[str] = ()) -> None:
    """首次进入、还没有任何提问时的引导（M-07：非项目同学也能无指导上手）。"""
    st.markdown(
        """
        <div style="border:1px solid #E2E8F0;border-radius:12px;padding:18px 20px;background:#F8FAFC;">
          <div style="font-size:16px;font-weight:600;color:#0F172A;">👋 问问公司文档里的那些事</div>
          <div style="font-size:13px;color:#475569;margin-top:6px;line-height:1.7;">
            直接在下方输入问题即可，答案会附上原文出处方便你核对。<br/>
            例如：年假有多少天？出差住宿标准是多少？试用期转正要走哪些流程？
          </div>
        </div>
        """,
        unsafe_allow_html=True,
    )
    st.write("")
    if examples:
        st.caption("试试这些问题：")
        cols = st.columns(min(len(examples), 3))
        for i, question in enumerate(examples):
            with cols[i % len(cols)]:
                if st.button(question, key=f"example_{i}", use_container_width=True):
                    st.session_state["pending_question"] = question
                    st.rerun()


def not_found_notice(message: str = "") -> None:
    """无依据兜底（US-08 / FR-QA-04）：中性语气 + 补救建议，绝不编造。"""
    st.warning(
        (message or "未在知识库中找到相关依据。")
        + "\n\n建议：换一种问法，或联系管理员补充相关文档后再试。"
    )


def clarify_notice(message: str = "") -> None:
    """问法宽泛、需要澄清（US-09）。"""
    st.info(
        (message or "这个问题有多个适用标准，请补充关键信息。")
        + "\n\n例如补充：出差城市级别、员工职级或具体场景。"
    )


def error_notice(error: Any, retry_label: Optional[str] = "重试") -> bool:
    """错误态统一出口：只展示中文原因 + 建议，并给出重试入口。返回是否点了重试。"""
    if isinstance(error, ApiError):
        detail = "\n".join(f"- {d}" for d in getattr(error, "details", []))
        st.error(f"**{error.message}**\n\n{error.hint or '请稍后重试。'}" + (f"\n\n{detail}" if detail else ""))
        trace_id = error.trace_id
    else:
        st.error(f"**出了点问题**\n\n{error}")
        trace_id = ""
    if trace_id:
        st.caption(f"排障编号（trace_id）：`{trace_id}`")
    if retry_label:
        return st.button(retry_label, key="retry_button", type="primary")
    return False


def loading_hint(text: str = "正在检索知识库…") -> None:
    st.caption(f"⏳ {text}")


def backend_status_badge(health: dict) -> None:
    """侧栏后端状态灯（架构 9.4 健康检查 API-01）。"""
    components = health.get("components") or {}
    if health.get("ok"):
        st.success("后端连接正常")
    elif components:
        st.warning("后端已连接，但有依赖异常")
    else:
        st.error("后端未连接")
    if components:
        labels = {"llm": "模型", "embedding": "向量化", "vector_store": "知识库", "sqlite": "数据库"}
        text = " · ".join(f"{labels.get(k, k)}:{'✅' if v == 'ok' else '❌'}" for k, v in components.items())
        st.caption(text)
    if health.get("version"):
        st.caption(f"服务版本：{health['version']}")