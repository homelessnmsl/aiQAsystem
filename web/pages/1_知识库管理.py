"""知识库管理页 — 上传 / 文档列表 / 删除（FR-UI-02、FR-DOC、FR-KB-04/05、US-02/10/11）

运行：`python -m streamlit run web/app.py` 后，从左侧页面导航进入本页。
对齐接口：API-03 `/api/upload`、API-04 `/api/documents`、API-05 `DELETE /api/documents/{doc_id}`。
第1周说明：接口由 DEV/AD 在第2周交付；未接通时本页显示空态与"暂不可用"提示，不会报错崩溃。
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


@st.cache_resource(show_spinner=False)
def get_client(base_url: str) -> ApiClient:
    return ApiClient(base_url)


def client() -> ApiClient:
    return get_client(st.session_state.get("api_base", ""))


def is_demo_mode() -> bool:
    return bool(st.session_state.get("demo_mode", False))


def load_documents() -> Dict[str, Any]:
    return client().list_documents()


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
        else:
            reason = item.get("error_message") or item.get("message") or item.get("error")
            st.error(f"《{name}》处理失败：{reason or '文件可能已损坏或不含可解析文本'}")
    succeeded, failed = result.get("succeeded"), result.get("failed")
    if isinstance(succeeded, int):
        st.caption(f"本次上传：成功 {succeeded} 个，失败 {failed or 0} 个。")


def render_documents() -> None:
    st.subheader("已入库文档")
    col_a, col_b = st.columns([1, 5])
    with col_a:
        if st.button("刷新列表", use_container_width=True):
            st.session_state["documents"] = None
            st.session_state["confirm_delete"] = ""
    with col_b:
        st.caption(f"支持格式：{' / '.join(UPLOAD_EXTENSIONS)}；单文件 ≤ {MAX_FILE_SIZE_MB}MB；单次 ≤ {MAX_FILES_PER_UPLOAD} 个")

    if st.session_state.get("documents") is None:
        try:
            st.session_state["documents"] = load_documents().get("items", [])
        except ApiError as exc:
            st.session_state["documents"] = []
            st.info(
                "**暂时读不到文档列表**：" + exc.display
                + "\n\n该接口（`GET /api/documents`）由 DEV/AD 在第2周交付，本页骨架已按接口文档预留。"
            )
            return

    docs: List[Dict[str, Any]] = st.session_state["documents"] or []
    if not docs:
        st.info("知识库还没有文档。上传后即可在问答页针对文档内容提问（US-11）。")
        return

    header = st.columns([4, 1.2, 1.4, 1.4, 2.4])
    for col, title in zip(header, ["文件名", "格式", "切片数", "上传时间", "操作"]):
        col.markdown(f"**{title}**")

    for doc in docs:
        doc_id = str(doc.get("doc_id", ""))
        cols = st.columns([4, 1.2, 1.4, 1.4, 2.4])
        status = str(doc.get("status", "success"))
        icon = {"success": "✅", "processing": "⏳", "failed": "❌", "deleted": "🗑️"}.get(status, "•")
        cols[0].write(f"{icon} {doc.get('filename', '未命名文件')}")
        cols[1].write(str(doc.get("file_type", "-")).upper())
        cols[2].write(str(doc.get("chunk_count", 0)))
        cols[3].write(str(doc.get("upload_time", "-"))[:16].replace("T", " "))
        if cols[4].button("删除", key=f"del_{doc_id}", use_container_width=True):
            st.session_state["confirm_delete"] = doc_id

        if st.session_state.get("confirm_delete") == doc_id:
            st.warning(f"确认删除《{doc.get('filename', '')}》？删除后其向量将不可再被检索（US-10：上传新版并删除旧版）。")
            c1, c2, _ = st.columns([1, 1, 6])
            if c1.button("确认删除", key=f"ok_{doc_id}", type="primary"):
                try:
                    res = client().delete_document(doc_id)
                    st.success(f"已删除《{doc.get('filename', '')}》，清理 {res.get('deleted_chunks', '若干')} 个切片。")
                except ApiError as exc:
                    st.error(exc.display)
                st.session_state["confirm_delete"] = ""
                st.session_state["documents"] = None
                st.rerun()
            if c2.button("取消", key=f"cancel_{doc_id}"):
                st.session_state["confirm_delete"] = ""
                st.rerun()


def main() -> None:
    st.title("📚 知识库管理")
    st.caption("上传公司文档 → 系统自动解析、切片、建立索引 → 回到问答页即可带引用提问。")

    if is_demo_mode():
        st.warning("当前处于**演示模式**，问答使用预置数据。上传与删除需要真实后端，建议关闭演示模式后操作。")

    st.subheader("上传文档（US-01 / US-02）")
    uploaded = st.file_uploader(
        "拖拽或点击选择文件",
        type=list(UPLOAD_EXTENSIONS),
        accept_multiple_files=True,
        help=f"支持 PDF / Word / Excel / TXT / Markdown；单文件 ≤ {MAX_FILE_SIZE_MB}MB，单次最多 {MAX_FILES_PER_UPLOAD} 个。",
    )

    if uploaded:
        problems = validate_files(uploaded)
        if problems:
            for problem in problems:
                st.error(problem)
        else:
            st.caption("已选择：" + "、".join(f"《{f.name}》" for f in uploaded))
            if st.button("开始上传并建立索引", type="primary"):
                payload = [(f.name, f.getvalue(), getattr(f, "type", "")) for f in uploaded]
                try:
                    with st.spinner("正在解析文档并建立索引（多份文件会逐个处理）…"):
                        result = client().upload(payload)
                except ApiError as exc:
                    st.error(
                        "**上传失败**：" + exc.display
                        + "\n\n该接口（`POST /api/upload`）由 DEV/AD 在第2周交付，本页骨架已按接口文档预留。"
                    )
                else:
                    st.session_state["documents"] = None
                    render_upload_results(result)

    st.divider()
    render_documents()

    with st.expander("本页交互说明（第1周原型，供评审）"):
        st.markdown(
            """
            - **加载态**：上传中显示"正在解析文档并建立索引…"，逐文件结果独立展示，单个失败不影响其他文件；
            - **错误态**：格式/大小/数量在客户端先校验，用中文说清原因与建议（不出现技术术语）；
            - **删除**：二次确认后才执行，避免误操作；删除后自动刷新列表；
            - **待完善（第2周）**：接入真实上传进度百分比，需要后端返回逐文件处理进度。
            """
        )


main()