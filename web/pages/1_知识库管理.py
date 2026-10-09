r"""知识库管理页 — 上传 / 文档列表 / 删除（FR-UI-02、FR-DOC、FR-KB-04/05、US-01/02/10/11）

运行：`.venv\Scripts\python.exe -m streamlit run web/app.py` 后，从左侧页面导航进入本页。
对齐接口：API-03 `/api/upload`、API-04 `/api/documents`、API-05 `DELETE /api/documents/{doc_id}`
（字段以 `docs/接口文档.md` 2.3/2.4/2.5 为准）。

第3周打磨点：
- 顶部知识库概况（文档数 / 切片总数 / 解析失败数 / 最近上传时间）；
- 上传用步骤态（st.status）展示"接收 → 解析入库 → 完成"，比单纯转圈更能说明在做什么；
- 列表读取失败给中文原因 + 一键重试，不再出现"第2周交付"这类过时文案；
- 删除二次确认 + 结果提示（接口文档 2.5；该接口第3周交付，未实现时给出友好提示而不是报错）。
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any, Dict, List

import streamlit as st

WEB_DIR = Path(__file__).resolve().parent.parent
if str(WEB_DIR) not in sys.path:
    sys.path.insert(0, str(WEB_DIR))

from api_client import (  # noqa: E402
    MAX_FILE_SIZE_MB,
    MAX_FILES_PER_UPLOAD,
    UPLOAD_EXTENSIONS,
    ApiClient,
    ApiError,
    validate_files,
)

st.set_page_config(page_title="知识库管理 · 企业知识库智能问答", page_icon="📚", layout="wide")

STATUS_META = {
    "success": ("✅", "已入库"),
    "processing": ("⏳", "处理中"),
    "failed": ("❌", "解析失败"),
    "deleted": ("🗑️", "已删除"),
}


@st.cache_resource(show_spinner=False)
def get_client(base_url: str) -> ApiClient:
    return ApiClient(base_url)


def client() -> ApiClient:
    return get_client(st.session_state.get("api_base", ""))


def is_demo_mode() -> bool:
    return bool(st.session_state.get("demo_mode", False))


def ensure_documents() -> List[Dict[str, Any]]:
    """读取文档列表（会话内缓存）。失败时把原因记在 ``doc_error``，不抛给页面。"""
    ss = st.session_state
    if ss.get("documents") is None:
        try:
            ss["documents"] = client().list_documents().get("items", [])
            ss["doc_error"] = ""
        except ApiError as exc:
            ss["documents"] = []
            ss["doc_error"] = exc.display
    return ss.get("documents") or []


def refresh_documents() -> None:
    st.session_state["documents"] = None
    st.session_state["confirm_delete"] = ""


def render_overview(docs: List[Dict[str, Any]]) -> None:
    """知识库概况（US-11）：让管理员一眼判断知识覆盖是否完整。"""
    chunks = sum(int(d.get("chunk_count") or 0) for d in docs if isinstance(d, dict))
    failed = sum(1 for d in docs if d.get("status") == "failed")
    times = [str(d.get("upload_time") or "") for d in docs if d.get("upload_time")]
    latest = max(times)[:16].replace("T", " ") if times else "—"
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("已入库文档", len(docs))
    c2.metric("切片总数", chunks)
    c3.metric("解析失败", failed)
    c4.metric("最近上传", latest)


def render_upload_results(result: Dict[str, Any]) -> None:
    """逐文件展示结果（架构 8.3：单文件失败不影响其他文件）。"""
    files = result.get("items") or result.get("results") or []
    if not files:
        st.success("上传完成。")
        return
    for item in files:
        if not isinstance(item, dict):
            continue
        name = item.get("filename") or item.get("file") or "未命名文件"
        status = str(item.get("status", "success"))
        if status in ("success", "ok"):
            chunks = item.get("chunk_count", item.get("chunks", 0))
            elapsed = item.get("elapsed_ms")
            extra = f"，生成 {chunks} 个切片" if chunks else ""
            extra += f"，耗时 {elapsed / 1000:.1f}s" if isinstance(elapsed, (int, float)) else ""
            st.success(f"《{name}》已入库{extra}。")
        elif status == "skipped":
            st.warning(f"《{name}》已存在同名文档，本次跳过（需要覆盖请在上传时选择覆盖）。")
        else:
            reason = item.get("error_message") or item.get("message") or item.get("error")
            st.error(f"《{name}》处理失败：{reason or '文件可能已损坏或不含可解析文本'}")
    succeeded, failed = result.get("succeeded"), result.get("failed")
    if isinstance(succeeded, int):
        st.caption(f"本次上传：成功 {succeeded} 个，失败 {failed or 0} 个。")


def _close_dialog() -> None:
    """关闭弹窗：整页重跑，确保模态框真的消失（弹窗是 fragment，默认 rerun 只重跑片段）。"""
    try:
        st.rerun(scope="app")
    except TypeError:   # 老版本没有 scope 参数
        st.rerun()


def _do_delete(doc_id: str, filename: str) -> None:
    """真正执行删除：成功/失败都写一条提示，交给下次运行显示（跨 st.rerun 保留）。"""
    try:
        res = client().delete_document(doc_id)
        st.session_state["flash"] = f"已删除《{filename}》，清理 {res.get('deleted_chunks', '若干')} 个切片。"
    except ApiError as exc:
        st.session_state["flash"] = f"删除《{filename}》失败：{exc.display}"
    refresh_documents()
    st.session_state["confirm_delete"] = ""


if hasattr(st, "dialog"):  # Streamlit ≥ 1.34：用真正的模态弹窗，避免误点

    @st.dialog("确认删除文档")
    def open_delete_dialog(doc_id: str, filename: str) -> None:
        st.warning(f"确认删除《{filename}》？删除后其向量不可再被检索，也无法恢复。")
        st.caption("对应需求 US-10：上传新版制度后删除旧版，避免答案继续引用过期文件。")
        c1, c2 = st.columns(2)
        if c1.button("确认删除", type="primary", use_container_width=True, key=f"ok_{doc_id}"):
            _do_delete(doc_id, filename)
            _close_dialog()
        if c2.button("取消", use_container_width=True, key=f"cancel_{doc_id}"):
            st.session_state["confirm_delete"] = ""
            _close_dialog()

else:  # 极老版本兜底：页面内联确认

    def open_delete_dialog(doc_id: str, filename: str) -> None:
        st.warning(f"确认删除《{filename}》？删除后其向量不可再被检索，也无法恢复。")
        c1, c2, _ = st.columns([1, 1, 6])
        if c1.button("确认删除", type="primary", key=f"ok_{doc_id}"):
            _do_delete(doc_id, filename)
            _close_dialog()
        if c2.button("取消", key=f"cancel_{doc_id}"):
            st.session_state["confirm_delete"] = ""
            _close_dialog()


def render_upload() -> None:
    st.subheader("上传文档（US-01 / US-02）")
    uploaded = st.file_uploader(
        "拖拽或点击选择文件",
        type=list(UPLOAD_EXTENSIONS),
        accept_multiple_files=True,
        help=f"支持 PDF / Word / Excel / TXT / Markdown；单文件 ≤ {MAX_FILE_SIZE_MB}MB，单次最多 {MAX_FILES_PER_UPLOAD} 个。",
    )
    if not uploaded:
        return

    problems = validate_files(uploaded)
    if problems:
        for problem in problems:
            st.error(problem)
        return

    st.caption("已选择：" + "、".join(f"《{f.name}》" for f in uploaded))
    if not st.button("开始上传并建立索引", type="primary"):
        return

    payload = [(f.name, f.getvalue(), getattr(f, "type", "")) for f in uploaded]
    with st.status("正在处理上传…", expanded=True) as status:
        st.write(f"① 已接收 {len(payload)} 个文件，正在校验格式与大小…")
        try:
            result = client().upload(payload)
        except ApiError as exc:
            status.update(label="上传失败", state="error")
            st.error("**上传失败**：" + exc.display)
            return
        st.write("② 解析 → 切片 → 向量化 → 写入知识库（逐文件处理，单个失败不影响其他文件）")
        st.write(f"③ 完成：成功 {result.get('succeeded', 0)} 个，失败 {result.get('failed', 0)} 个")
        status.update(label="上传完成", state="complete")
    refresh_documents()
    st.session_state["doc_summary"] = None      # 问答页侧栏的概况也要跟着刷新
    render_upload_results(result)


def render_documents(docs: List[Dict[str, Any]]) -> None:
    st.subheader("已入库文档")
    col_a, col_b = st.columns([1, 5])
    with col_a:
        if st.button("刷新列表", use_container_width=True):
            refresh_documents()
            st.rerun()
    with col_b:
        st.caption(f"支持格式：{' / '.join(UPLOAD_EXTENSIONS)}；单文件 ≤ {MAX_FILE_SIZE_MB}MB；单次 ≤ {MAX_FILES_PER_UPLOAD} 个")

    if st.session_state.get("doc_error"):
        st.info(
            "**暂时读不到文档列表**：" + str(st.session_state["doc_error"])
            + "\n\n请确认后端已启动（默认 127.0.0.1:8000），然后点下面的按钮重试。"
        )
        if st.button("重试读取", key="retry_docs"):
            refresh_documents()
            st.rerun()
        return

    if not docs:
        st.info("知识库还没有文档。上传后即可在问答页针对文档内容提问（US-11）。")
        return

    header = st.columns([4, 1.2, 1.2, 1.5, 2.4])
    for col, title in zip(header, ["文件名", "格式", "切片数", "上传时间", "状态 / 操作"]):
        col.markdown(f"**{title}**")

    for doc in docs:
        doc_id = str(doc.get("doc_id", ""))
        cols = st.columns([4, 1.2, 1.2, 1.5, 2.4])
        status = str(doc.get("status", "success"))
        icon, status_text = STATUS_META.get(status, ("•", status))
        cols[0].write(f"{icon} {doc.get('filename', '未命名文件')}")
        cols[1].write(str(doc.get("file_type", "-")).upper())
        cols[2].write(str(doc.get("chunk_count", 0)))
        cols[3].write(str(doc.get("upload_time", "-"))[:16].replace("T", " "))
        with cols[4]:
            c_status, c_del = st.columns([1.2, 1])
            c_status.caption(status_text)
            if c_del.button("删除", key=f"del_{doc_id}", use_container_width=True):
                st.session_state["confirm_delete"] = doc_id
                st.rerun()

    # 删除确认弹窗（W4-07：用模态弹窗替代行内确认，减少误操作）
    pending = st.session_state.get("confirm_delete")
    if pending:
        target = next((d for d in docs if str(d.get("doc_id")) == str(pending)), None)
        if target:
            open_delete_dialog(str(target.get("doc_id")), str(target.get("filename", "")))
        else:
            st.session_state["confirm_delete"] = ""


def main() -> None:
    st.title("📚 知识库管理")
    st.caption("上传公司文档 → 系统自动解析、切片、建立索引 → 回到问答页即可带引用提问。")

    if is_demo_mode():
        st.warning("当前处于**演示模式**，问答使用预置数据。上传与删除需要真实后端，建议关闭演示模式后操作。")

    flash = st.session_state.pop("flash", "")
    if flash:
        st.toast(flash, icon="🗑️")

    docs = ensure_documents()
    render_overview(docs)

    st.divider()
    render_upload()

    st.divider()
    render_documents(docs)

    with st.expander("本页交互说明（供评审）"):
        st.markdown(
            """
            - **加载态**：上传用步骤态展示"接收 → 解析入库 → 完成"，单文件结果独立展示，单个失败不影响其他文件；
            - **错误态**：格式/大小/数量在客户端先拦截；列表读取失败给出中文原因与一键重试；
            - **删除**：点删除弹出模态确认框（Streamlit 1.34+ 的 `st.dialog`），确认后自动刷新列表与概况；
            - **待完善**：上传进度百分比需要后端返回逐文件进度（当前为同步接口，只能给步骤态）。
            """
        )

if __name__ == "__main__":  # 与 app.py 保持一致，便于被导入做测试
    main()
