"""错误码、业务异常与全局异常处理器（接口文档 1.3 / 1.4；W1-13）

- 错误码全表以 docs/接口文档.md 1.4 为唯一来源：新增错误码必须先改文档再改代码；
- 全局兜底不返回 Traceback（NFR-R-04），未捕获异常统一 5000；
- 参数校验失败返回 code=1001 与 data.errors[{field, reason}]（接口文档 1.2 示例）。
"""
import logging

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from .response import ApiResponse

logger = logging.getLogger(__name__)

# ============================================================
# 错误码（接口文档 1.4，全组唯一来源）
# ============================================================
CODE_OK = 0

# ---- 1xxx 请求与校验 ----
CODE_VALIDATION_FAILED = 1001      # HTTP 400 参数校验失败（data.errors 明细）
CODE_FILE_TYPE_UNSUPPORTED = 1002  # HTTP 415 文件类型不支持
CODE_FILE_TOO_LARGE = 1003         # HTTP 413 文件超限
CODE_INVALID_QUESTION = 1004       # HTTP 400 问题不合法（空/超长）
CODE_NOT_FOUND = 1005              # HTTP 404 资源不存在
CODE_BAD_JSON = 1006               # HTTP 400 请求体不是合法 JSON

# ---- 2xxx 知识库 / 文档 ----
CODE_KB_EMPTY = 2001               # HTTP 409 知识库为空
CODE_PARSE_FAILED = 2002           # HTTP 422 文档解析失败
CODE_VECTOR_STORE_ERROR = 2003     # HTTP 503 向量库异常
CODE_DOC_DUPLICATE = 2004          # HTTP 409 文档重复

# ---- 3xxx 模型与外部服务 ----
CODE_LLM_TIMEOUT = 3001            # HTTP 504 模型调用超时
CODE_LLM_RATE_LIMIT = 3002         # HTTP 429 模型限流/额度不足
CODE_LLM_NO_KEY = 3003             # HTTP 500 未配置模型密钥
CODE_LLM_BAD_RESPONSE = 3004       # HTTP 502 模型返回异常

# ---- 5xxx 服务端内部 ----
CODE_INTERNAL_ERROR = 5000         # HTTP 500 服务器内部错误

#: 业务 code → HTTP 状态码（接口文档 1.4）
CODE_HTTP_STATUS = {
    CODE_OK: 200,
    CODE_VALIDATION_FAILED: 400,
    CODE_FILE_TYPE_UNSUPPORTED: 415,
    CODE_FILE_TOO_LARGE: 413,
    CODE_INVALID_QUESTION: 400,
    CODE_NOT_FOUND: 404,
    CODE_BAD_JSON: 400,
    CODE_KB_EMPTY: 409,
    CODE_PARSE_FAILED: 422,
    CODE_VECTOR_STORE_ERROR: 503,
    CODE_DOC_DUPLICATE: 409,
    CODE_LLM_TIMEOUT: 504,
    CODE_LLM_RATE_LIMIT: 429,
    CODE_LLM_NO_KEY: 500,
    CODE_LLM_BAD_RESPONSE: 502,
    CODE_INTERNAL_ERROR: 500,
}

#: HTTP 状态码 → 业务 code（HTTPException 兜底映射）
HTTP_STATUS_CODE = {v: k for k, v in CODE_HTTP_STATUS.items() if k != CODE_OK}


class BizError(Exception):
    """业务异常：携带接口文档错误码与面向用户的中文 message"""

    def __init__(self, code: int, message: str, data=None):
        self.code = code
        self.message = message
        self.data = data
        super().__init__(f"[{code}] {message}")


# ============================================================
# 参数校验错误 → 面向用户的中文 reason（接口文档 1.2 示例）
# ============================================================
def _reason_for(error: dict) -> str:
    """把 Pydantic 校验错误翻译成中文说明"""
    loc = error.get("loc") or ()
    field = str(loc[-1]) if loc else "body"
    etype = error.get("type", "")

    if field == "message":
        if etype in ("missing", "string_too_short"):
            return "消息不能为空"
        if etype == "string_too_long":
            return "消息过长（最多 2000 字）"
    if field == "temperature":
        return "temperature 必须在 0~2 之间"
    if field == "max_tokens":
        return "max_tokens 必须在 1~4096 之间"
    if field == "session_id":
        return "session_id 不合法"
    if field == "question":
        if etype in ("missing", "string_too_short"):
            return "问题不能为空"
        if etype == "string_too_long":
            return "问题过长，请精简到 500 字以内"
    if field == "top_k":
        return "top_k 必须在 1~10 之间"
    if field == "score_threshold":
        return "score_threshold 必须在 0~1 之间"
    if field == "page":
        return "page 必须 ≥1"
    if field == "page_size":
        return "page_size 必须在 1~100 之间"
    return str(error.get("msg", "参数不合法"))


def register_exception_handlers(app: FastAPI) -> None:
    """挂载全局异常处理器（业务异常、参数校验、HTTP 异常、兜底）"""

    @app.exception_handler(BizError)
    async def biz_error_handler(request: Request, exc: BizError):
        status = CODE_HTTP_STATUS.get(exc.code, 500)
        return JSONResponse(
            status_code=status,
            content=ApiResponse.fail(exc.code, exc.message, exc.data),
        )

    @app.exception_handler(RequestValidationError)
    async def validation_error_handler(request: Request, exc: RequestValidationError):
        errors = [
            {"field": str(e.get("loc", ("body",))[-1]), "reason": _reason_for(e)}
            for e in exc.errors()
        ]
        if errors and errors[0]["field"] == "question":
            # /api/ask：空 / 超长问题按接口文档 1.4 返回 1004（问题不合法）
            return JSONResponse(
                status_code=400,
                content=ApiResponse.fail(CODE_INVALID_QUESTION, errors[0]["reason"], {"errors": errors}),
            )
        return JSONResponse(
            status_code=400,
            content=ApiResponse.fail(CODE_VALIDATION_FAILED, "参数校验失败", {"errors": errors}),
        )

    @app.exception_handler(StarletteHTTPException)
    async def http_error_handler(request: Request, exc: StarletteHTTPException):
        code = HTTP_STATUS_CODE.get(
            exc.status_code,
            CODE_INTERNAL_ERROR if exc.status_code >= 500 else CODE_VALIDATION_FAILED,
        )
        detail = exc.detail if isinstance(exc.detail, str) else "请求失败"
        if exc.status_code == 404 and detail == "Not Found":
            detail = "资源不存在或已被删除"
        return JSONResponse(status_code=exc.status_code, content=ApiResponse.fail(code, detail))

    @app.exception_handler(Exception)
    async def fallback_handler(request: Request, exc: Exception):
        logger.exception("未处理异常：%s", exc)
        return JSONResponse(
            status_code=500,
            content=ApiResponse.fail(CODE_INTERNAL_ERROR, "系统开小差了，请稍后重试"),
        )
