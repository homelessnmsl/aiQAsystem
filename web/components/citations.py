"""引用展示组件（FR-CIT-03 / FR-UI-04：序号 + 折叠条，一眼看出答案与出处的对应关系）。

约定：
- 答案正文里的 `[1]` 由程序注入高亮，与下方折叠条序号一一对应；
- 引用字段使用需求 7.4 数据字典：source_file / location / snippet / score；
- 展示的是"原文片段"而非全文下载（US-04）。
"""

from __future__ import annotations

import re
from typing import Any, Dict, List, Optional

import streamlit as st

from api_client import ApiError

CITE_PATTERN = re.compile(r"\[(\d{1,2})\]")


def highlight_references(answer: str) -> str:
    """把正文中的 [n] 渲染成上标锚点，视觉上与引用折叠条呼应。"""
    return CITE_PATTERN.sub(
        r'<sup style="color:#2563EB;font-weight:700;background:#EFF6FF;'
        r'border-radius:4px;padding:0 3px;">[\1]</sup>',
        answer or "",
    )


def render_answer(answer: str, citations: Optional[List[Dict[str, Any]]] = None) -> None:
    st.markdown(highlight_references(answer or ""), unsafe_allow_html=True)
    if citations:
        render_citations(citations)


def render_citations(citations: List[Dict[str, Any]]) -> None:
    """每条引用一个可折叠条：标题给"文件名 + 位置"，展开看原文片段与相关度。"""
    if not citations:
        st.caption("本条回答没有引用来源（未在知识库中找到依据）。")
        return
    st.caption(f"📎 引用来源（{len(citations)}）— 编号与答案中的 [n] 一致，点开可核对原文")
    for i, cite in enumerate(citations, start=1):
        index = cite.get("index", i)
        file_name = cite.get("source_file") or "未知来源"
        location = cite.get("location") or ""
        score = cite.get("score")
        title = f"[{index}]  📄 {file_name}"
        if location:
            # 位置可能很长（如 Markdown 章节链），折叠条标题只留前 36 字，完整内容在展开区
            short_location = location if len(location) <= 36 else location[:36] + "…"
            title += f" · {short_location}"
        if isinstance(score, (int, float)):
            title += f" · 相关度 {score:.2f}"
        with st.expander(title):
            if location:
                st.caption(f"完整位置：{location}")
            snippet = cite.get("snippet") or "（该引用未返回原文片段）"
            st.markdown(f"> {snippet}")
            meta = []
            if cite.get("doc_id"):
                meta.append(f"doc_id: `{cite['doc_id']}`")
            if cite.get("chunk_id"):
                meta.append(f"chunk_id: `{cite['chunk_id']}`")
            if meta:
                st.caption(" · ".join(meta))


def render_retrieved(retrieved: List[Dict[str, Any]]) -> None:
    """检索详情（架构 6.12）：供 PE 评测与排障，默认收起，不干扰业务用户。"""
    if not retrieved:
        return
    with st.expander(f"检索详情（Top-{len(retrieved)}，评测与排障用）"):
        for row in retrieved:
            if not isinstance(row, dict):
                continue
            score = row.get("score")
            rerank = row.get("rerank_score")
            score_text = f"{score:.3f}" if isinstance(score, (int, float)) else "-"
            rerank_text = f"{rerank:.3f}" if isinstance(rerank, (int, float)) else "-"
            st.markdown(
                f"- `{row.get('chunk_id', '')}` ｜ {row.get('source_file', '')} "
                f"｜ {row.get('location', '')} ｜ 相似度 {score_text} ｜ 重排 {rerank_text}"
            )


def render_answer_meta(message: Dict[str, Any]) -> None:
    """一行元信息：耗时 / trace_id / 模型（FR-OPS-04）。"""
    parts = []
    latency = message.get("latency_ms")
    if isinstance(latency, dict):  # 接口文档 2.6：latency_ms 为分段耗时，取 total
        latency = latency.get("total")
    if isinstance(latency, (int, float)):
        parts.append(f"耗时 {latency / 1000:.1f}s")
    if message.get("model"):
        parts.append(str(message["model"]))
    if message.get("trace_id"):
        parts.append(f"trace_id `{message['trace_id']}`")
    if parts:
        st.caption(" ｜ ".join(parts))


def render_feedback(client: Any, message: Dict[str, Any]) -> None:
    """点赞/点踩（US-12 / 接口文档 2.7）。

    - 👍 直接提交；👎 先问一句"哪里不准确"（可留空）再提交；
    - 同一条回答只提交一次，提交后显示"已收到你的反馈"；
    - **反馈失败不影响主流程**（US-12 明确要求）：只给一句提示，不打断问答。
    """
    message_id = message.get("message_id") or ""
    key = message_id or f"anon_{id(message)}"
    ss = st.session_state
    done: Dict[str, str] = ss.setdefault("feedback_done", {})
    if key in done:
        st.caption("✅ 已收到你的反馈，谢谢！")
        return

    pending_key = f"feedback_pending_{key}"
    col_up, col_down, _ = st.columns([1, 1, 6])
    with col_up:
        liked = st.button("👍 有帮助", key=f"fb_up_{key}")
    with col_down:
        disliked = st.button("👎 不准确", key=f"fb_down_{key}")

    if liked:
        _submit_feedback(client, message, "up", "", key, done)
        return
    if disliked:
        ss[pending_key] = True
        st.rerun()

    if ss.get(pending_key):
        comment = st.text_area(
            "哪里不准确？（可选，最多 200 字）",
            key=f"fb_comment_{key}",
            max_chars=200,
            height=80,
            placeholder="例如：答案没有给出天数 / 引用位置对不上",
        )
        c1, c2, _ = st.columns([1, 1, 6])
        with c1:
            if st.button("提交反馈", key=f"fb_send_{key}", type="primary"):
                _submit_feedback(client, message, "down", comment, key, done)
                return
        with c2:
            if st.button("取消", key=f"fb_cancel_{key}"):
                ss[pending_key] = False
                st.rerun()


def _submit_feedback(client: Any, message: Dict[str, Any], rating: str, comment: str,
                     key: str, done: Dict[str, str]) -> None:
    """提交一条反馈；无论成功与否都标记为已提交，避免同一条回答反复打扰用户。"""
    message_id = message.get("message_id") or ""
    if not message_id:
        st.toast("（本条回答没有 message_id，暂时无法提交反馈）", icon="ℹ️")
    else:
        try:
            client.send_feedback(
                message_id,
                rating,
                comment=comment or "",
                session_id=message.get("session_id", ""),
            )
            st.toast("感谢反馈，我们会持续改进！", icon="✅")
        except ApiError:
            st.toast("感谢反馈（记录失败，不影响本次问答）", icon="ℹ️")
    done[key] = rating
    st.session_state[f"feedback_pending_{key}"] = False
    st.rerun()
