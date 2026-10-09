"""前端统一 HTTP 客户端（UI 主责，W1-18）。

设计要点（对齐 docs/架构设计.md 第 5 章、docs/接口文档.md）：
1. 前端只通过 HTTP 调后端，**不 import 任何后端代码、不读数据库**（架构 3.2 依赖铁律）；
2. 后端统一响应 ``{"code", "message", "data"}``，本模块负责拆包并把错误码翻译成
   面向业务用户的中文提示（需求 8.2 错误态：不显示堆栈、要说清原因与建议）；
3. 所有调用都设超时；对外抛出的只有 :class:`ApiError`，不把底层异常泄露给页面；
4. 字段解析**向后兼容**：接口文档尚未定稿期间，对同义字段（answer/reply/content）
   做兼容取值，字段缺失时给默认值，避免页面直接崩。
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

import requests

# --------------------------------------------------------------------------- #
# 基础配置（与架构 9.5 节 WEB_API_BASE 对齐）
# --------------------------------------------------------------------------- #
DEFAULT_BASE_URL = os.getenv("WEB_API_BASE", "http://127.0.0.1:8000")
#: 问答链路预算 ≤10s（M-05），这里留足重试余量；可在 .env 覆盖
DEFAULT_TIMEOUT = float(os.getenv("WEB_API_TIMEOUT_SECONDS", "120"))
#: 健康检查要"秒回"，超时就认为后端没起来
HEALTH_TIMEOUT = 3.0

UPLOAD_EXTENSIONS: Tuple[str, ...] = ("pdf", "docx", "xlsx", "txt", "md")
MAX_FILE_SIZE_MB = int(os.getenv("MAX_FILE_SIZE_MB", "20"))
MAX_FILES_PER_UPLOAD = int(os.getenv("MAX_FILES_PER_UPLOAD", "5"))

#: 错误码 → 中文提示（文案取自需求 8.2 / 架构 8.3，业务用户看得懂，不出现技术术语）
ERROR_HINTS: Dict[Any, str] = {
    1001: "请求参数有误，请检查后重试。",
    1002: "文件格式不支持，目前仅支持 PDF、Word、Excel、TXT、Markdown。",
    1003: f"文件过大或数量过多，请压缩到 {MAX_FILE_SIZE_MB}MB 以内，单次不超过 {MAX_FILES_PER_UPLOAD} 个。",
    1004: "问题内容为空或过长，请精简后再问。",
    1005: "文档不存在，可能已被删除，请刷新文档列表。",
    1006: "请求内容格式不正确，请刷新页面后重试。",
    2001: "知识库还是空的，请先到「知识库管理」上传公司文档。",
    2002: "文档还在处理中，请稍等片刻再提问。",
    2003: "知识库暂时不可用，请稍后重试或联系管理员。",
    2004: "已存在同名文档，请选择覆盖或先删除旧文档。",
    3001: "回答生成超时了，请稍后重试。",
    3002: "模型服务有点忙（可能被限流），请稍后重试。",
    3003: "服务未配置模型密钥，请联系管理员。",
    3004: "回答生成异常，请重试。",
    5000: "服务内部错误，请稍后重试。",
}


@dataclass
class ApiError(Exception):
    """面向前端的统一异常：页面只需要 message + hint 两句话。"""

    code: Any = None
    message: str = "服务暂时不可用"
    hint: str = ""
    trace_id: str = ""
    http_status: Optional[int] = None
    details: List[str] = field(default_factory=list)

    def __str__(self) -> str:  # pragma: no cover - 仅用于日志
        return f"[{self.code}] {self.message} {self.hint}".strip()

    @property
    def display(self) -> str:
        """给页面用的一句话（原因 + 建议）。"""
        return self.hint or self.message


def _hint_for(code: Any) -> str:
    return ERROR_HINTS.get(code, "")


def _offline_error(exc: Exception) -> ApiError:
    """把网络层异常翻译成"后端没起来/断网"的中文提示。"""
    return ApiError(
        code="network",
        message="无法连接后端服务",
        hint=(
            "后端服务似乎没有启动（或网络不通）。请确认后端已在 127.0.0.1:8000 运行；"
            "演示现场可打开左侧「演示模式」，用预置问答继续演示。"
        ),
    )


class ApiClient:
    """后端接口的薄封装；每个方法对应 docs/接口文档.md 中的一个接口。"""

    def __init__(self, base_url: Optional[str] = None, timeout: Optional[float] = None) -> None:
        self.base_url = (base_url or DEFAULT_BASE_URL).rstrip("/")
        self.timeout = timeout or DEFAULT_TIMEOUT
        self.session = requests.Session()

    # ------------------------------------------------------------------ #
    # 内部工具
    # ------------------------------------------------------------------ #
    def _url(self, path: str) -> str:
        return f"{self.base_url}{path if path.startswith('/') else '/' + path}"

    def _request(self, method: str, path: str, **kwargs: Any) -> Dict[str, Any]:
        """发请求 → 拆统一响应 → 返回 data；任何异常都转成 ApiError。"""
        kwargs.setdefault("timeout", self.timeout)
        try:
            resp = self.session.request(method, self._url(path), **kwargs)
        except requests.exceptions.Timeout as exc:  # 超时
            raise ApiError(
                code="timeout",
                message="请求超时",
                hint="后端响应太慢，请稍后重试；若反复超时请检查模型网络。",
            ) from exc
        except requests.exceptions.RequestException as exc:  # 连接失败等
            raise _offline_error(exc) from exc

        try:
            payload = resp.json()
        except ValueError as exc:
            raise ApiError(
                code="bad_response",
                message="后端返回了无法解析的内容",
                hint=f"接口地址可能不对（HTTP {resp.status_code}），请确认 WEB_API_BASE 指向后端服务。",
                http_status=resp.status_code,
            ) from exc

        return self._unwrap(payload, resp.status_code)

    @staticmethod
    def _unwrap(payload: Dict[str, Any], http_status: int = 200) -> Dict[str, Any]:
        """拆 ``{"code","message","data"}``；code 非 0 或 HTTP 非 2xx 一律报错。"""
        if not isinstance(payload, dict):
            raise ApiError(code="bad_response", message="后端返回结构异常", hint="请联系管理员。")
        code = payload.get("code", 0)
        message = payload.get("message") or ""
        data = payload.get("data")
        if code in (0, "0", None) and 200 <= http_status < 300:
            return data if isinstance(data, dict) else (data or {})
        # 接口文档 1.4 的 message 列即"面向用户的 message"，后端已说清楚时不再叠加本地提示，
        # 避免同一条限制（如 20MB / 支持格式）在界面上说两遍。
        backend_message = (message or "").strip()
        generic = backend_message.lower() in ("", "success", "error", "fail", "失败", "请求失败")
        hint = _hint_for(code) if generic else ""

        details: List[str] = []
        if isinstance(data, dict):
            for item in data.get("errors", []) or []:
                if isinstance(item, dict):
                    reason = item.get("reason") or item.get("message")
                    if reason:
                        details.append(str(reason))
                elif item:
                    details.append(str(item))
        raise ApiError(
            code=code,
            message=backend_message or ERROR_HINTS.get(code, "请求失败"),
            hint=hint,
            trace_id=(data or {}).get("trace_id", "") if isinstance(data, dict) else "",
            http_status=http_status,
            details=details,
        )

    # ------------------------------------------------------------------ #
    # 具体接口
    # ------------------------------------------------------------------ #
    def health(self) -> Dict[str, Any]:
        """API-01 ``GET /api/health``；不抛异常，用于侧栏状态灯。"""
        try:
            resp = self.session.get(self._url("/api/health"), timeout=HEALTH_TIMEOUT)
            payload = resp.json()
            if isinstance(payload, dict) and payload.get("code") in (0, "0", None):
                data = payload.get("data") or {}
                components = {
                    name: (info or {}).get("status", "unknown")
                    for name, info in (data.get("dependencies") or {}).items()
                }
                return {
                    "ok": data.get("status", "ok") == "ok",
                    "status": data.get("status", "ok"),
                    "version": data.get("version", ""),
                    "components": components,
                    "chunk_count": (data.get("dependencies", {}).get("vector_store") or {}).get("chunk_count"),
                }
            return {"ok": False, "status": "error", "detail": payload.get("message", "服务异常")}
        except Exception as exc:  # noqa: BLE001 - 状态检查不该影响页面
            return {"ok": False, "detail": str(exc)}

    def ask(self, question: str, session_id: str = "", top_k: Optional[int] = None) -> Dict[str, Any]:
        """API-06 ``POST /api/ask``：RAG 问答（答案 + 引用）。第2周 DEV 交付。"""
        body: Dict[str, Any] = {"question": question, "session_id": session_id}
        if top_k:
            body["top_k"] = top_k
        data = self._request("POST", "/api/ask", json=body)
        return _normalize_answer(data)

    def chat(self, question: str, session_id: str = "") -> Dict[str, Any]:
        """API-02 ``POST /api/chat``：基础对话（第1周打通 DeepSeek 用）。"""
        data = self._request("POST", "/api/chat", json={"message": question, "session_id": session_id or None})
        return _normalize_answer(data)

    def upload(self, files: Sequence[Tuple[str, bytes, str]]) -> Dict[str, Any]:
        """API-03 ``POST /api/upload``：上传文档建库（multipart，失败隔离）。"""
        multipart = [("files", (name, content, mime or "application/octet-stream")) for name, content, mime in files]
        data = self._request("POST", "/api/upload", files=multipart)
        items = list(data.get("items", []) or [])
        succeeded = data.get("succeeded", sum(1 for i in items if i.get("status") == "success"))
        failed = data.get("failed", sum(1 for i in items if i.get("status") == "failed"))
        return {"total": data.get("total", len(items)), "succeeded": succeeded, "failed": failed, "items": items}

    def list_documents(self) -> Dict[str, Any]:
        """API-04 ``GET /api/documents``：知识库文档列表（US-11）。"""
        data = self._request("GET", "/api/documents")
        items = data.get("items") if isinstance(data, dict) else None
        if items is None and isinstance(data, list):
            items = data
        return {"items": list(items or []), "total": data.get("total", len(items or [])) if isinstance(data, dict) else len(items or [])}

    def delete_document(self, doc_id: str) -> Dict[str, Any]:
        """API-05 ``DELETE /api/documents/{doc_id}``：删除文档及其向量（US-10）。"""
        return self._request("DELETE", f"/api/documents/{doc_id}")

    def send_feedback(self, message_id: str, rating: str, comment: str = "", session_id: str = "") -> Dict[str, Any]:
        """API-08 ``POST /api/feedback``：点赞/点踩（US-12）。"""
        return self._request(
            "POST",
            "/api/feedback",
            json={"message_id": message_id, "session_id": session_id, "rating": rating, "comment": comment},
        )

    def list_conversations(self, page: int = 1, page_size: int = 20) -> Dict[str, Any]:
        """API-09 ``GET /api/conversations``：侧栏历史会话（接口文档 2.8、FR-CONV-01）。"""
        data = self._request("GET", "/api/conversations", params={"page": page, "page_size": page_size})
        items = list(data.get("items", []) if isinstance(data, dict) else data or [])
        return {"total": data.get("total", len(items)) if isinstance(data, dict) else len(items), "items": items}

    def get_conversation(self, session_id: str) -> Dict[str, Any]:
        """API-10 ``GET /api/conversations/{session_id}``：恢复历史（接口文档 2.9、US-13）。

        返回的消息会归一化成页面渲染用的结构（``answer`` / ``answer_type`` / ``citations``），
        历史记录里没有 ``answer_type`` 字段，这里按"有引用即 answered、无引用且像兜底话术则 not_found"还原。
        """
        data = self._request("GET", f"/api/conversations/{session_id}")
        messages: List[Dict[str, Any]] = []
        for raw in data.get("messages", []) or []:
            if not isinstance(raw, dict):
                continue
            role = raw.get("role", "assistant")
            text = _first(raw, ANSWER_TEXT_KEYS, "")
            citations = [
                _normalize_citation(c, i + 1)
                for i, c in enumerate(raw.get("citations") or [])
                if isinstance(c, dict)
            ]
            if role == "assistant":
                fallback_words = ("未在", "抱歉", "没找到", "未找到")
                answer_type = "answered" if citations else ("not_found" if any(w in text for w in fallback_words) else "answered")
                messages.append({
                    "role": "assistant",
                    "answer": text,
                    "content": text,
                    "answer_type": answer_type,
                    "citations": citations,
                    "retrieved": [],
                    "message_id": raw.get("message_id", ""),
                    "trace_id": raw.get("trace_id", ""),
                    "session_id": data.get("session_id", session_id),
                    "created_at": raw.get("created_at", ""),
                })
            else:
                messages.append({"role": "user", "content": text, "created_at": raw.get("created_at", "")})
        return {
            "session_id": data.get("session_id", session_id),
            "title": data.get("title", ""),
            "messages": messages,
        }

    def clear_conversation(self, session_id: str) -> Dict[str, Any]:
        """API-11 ``DELETE /api/conversations/{session_id}``（第3周）。"""
        return self._request("DELETE", f"/api/conversations/{session_id}")


# --------------------------------------------------------------------------- #
# 响应归一化：让页面只认一套字段名
# --------------------------------------------------------------------------- #
ANSWER_TEXT_KEYS = ("answer", "reply", "content", "text", "message")
CITATION_LIST_KEYS = ("citations", "sources", "references")


def _first(data: Dict[str, Any], keys: Iterable[str], default: Any = "") -> Any:
    for key in keys:
        value = data.get(key)
        if value not in (None, ""):
            return value
    return default


def _normalize_citation(raw: Dict[str, Any], index: int) -> Dict[str, Any]:
    """引用字段对齐需求 7.4 数据字典：source_file / location / snippet / score。"""
    return {
        "index": raw.get("index", raw.get("n", index)),
        "doc_id": raw.get("doc_id", ""),
        "chunk_id": raw.get("chunk_id", ""),
        "source_file": _first(raw, ("source_file", "filename", "file", "source"), "未知来源"),
        "location": _first(raw, ("location", "position", "loc"), ""),
        "snippet": _first(raw, ("snippet", "text", "content"), ""),
        "score": raw.get("score"),
    }


def _normalize_answer(data: Any) -> Dict[str, Any]:
    """把后端响应整理成页面固定使用的结构，字段缺失也不炸。"""
    if not isinstance(data, dict):
        return {"answer": str(data), "answer_type": "answered", "citations": [], "retrieved": []}
    citations_raw = _first(data, CITATION_LIST_KEYS, []) or []
    result = {
        "answer": _first(data, ANSWER_TEXT_KEYS, "（后端未返回答案文本）"),
        "answer_type": data.get("answer_type", "answered"),
        "citations": [_normalize_citation(c, i + 1) for i, c in enumerate(citations_raw) if isinstance(c, dict)],
        "retrieved": data.get("retrieved", []) or [],
        "session_id": data.get("session_id", ""),
        "message_id": data.get("message_id", ""),
        "trace_id": data.get("trace_id", ""),
        "latency_ms": data.get("latency_ms"),
        "model": data.get("model", ""),
    }
    return result


def validate_files(files: Sequence[Any]) -> List[str]:
    """上传前的客户端校验（FR-DOC-03、US-02）：返回中文错误列表，空表示通过。"""
    problems: List[str] = []
    if not files:
        problems.append("请先选择要上传的文件。")
        return problems
    if len(files) > MAX_FILES_PER_UPLOAD:
        problems.append(f"单次最多上传 {MAX_FILES_PER_UPLOAD} 个文件，当前选了 {len(files)} 个。")
    for f in files:
        name = getattr(f, "name", str(f))
        size_mb = getattr(f, "size", 0) / 1024 / 1024
        ext = name.rsplit(".", 1)[-1].lower() if "." in name else ""
        if ext not in UPLOAD_EXTENSIONS:
            problems.append(f"《{name}》格式不支持，仅支持 PDF / Word / Excel / TXT / Markdown。")
        if size_mb > MAX_FILE_SIZE_MB:
            problems.append(f"《{name}》有 {size_mb:.1f}MB，超过 {MAX_FILE_SIZE_MB}MB 限制，请压缩后再传。")
    return problems


def client_from_env() -> ApiClient:
    """按环境变量创建客户端（Streamlit 侧栏可临时覆盖地址）。"""
    return ApiClient()


def pretty_json(data: Any) -> str:
    return json.dumps(data, ensure_ascii=False, indent=2, default=str)