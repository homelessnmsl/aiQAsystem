"""日志与 Trace（架构 9.4 / core README；W1-13）

- setup_logging()：统一日志格式（启动时调用一次，幂等）；
- new_trace_id() / set_trace_id() / get_trace_id()：链路 ID tr_{yyyymmdd}_{6位}（接口文档 1.5）；
- mask_key()：日志中 API Key 脱敏为 sk-****（NFR-S-01）；
- now_iso()：+08:00 的 ISO8601 时间（接口文档 1.5）。
"""
import logging
import random
import string
from contextvars import ContextVar
from datetime import datetime, timedelta, timezone

#: 东八区（项目统一时区，接口文档 1.5）
CST = timezone(timedelta(hours=8), name="CST")

_trace_id_var: ContextVar[str] = ContextVar("trace_id", default="")
_logging_initialized = False


def now_iso() -> str:
    """当前时间（ISO8601，+08:00），例如 2026-10-01T15:20:11+08:00"""
    return datetime.now(CST).isoformat(timespec="seconds")


def random_id_suffix(length: int = 6) -> str:
    """随机小写字母数字后缀（ID 规则用，接口文档 1.5）"""
    return "".join(random.choices(string.ascii_lowercase + string.digits, k=length))


def new_trace_id() -> str:
    """生成链路 ID：tr_20261001_b7c2e1（接口文档 1.5）"""
    return f"tr_{datetime.now(CST):%Y%m%d}_{random_id_suffix()}"


def set_trace_id(trace_id: str) -> str:
    """把 trace_id 放入上下文（日志自动附带）"""
    _trace_id_var.set(trace_id)
    return trace_id


def get_trace_id() -> str:
    """当前上下文中的 trace_id（无则返回 "-"）"""
    return _trace_id_var.get() or "-"


def mask_key(api_key: str | None) -> str:
    """API Key 脱敏：sk-****（NFR-S-01，日志中禁止出现完整 Key）"""
    if not api_key:
        return "sk-****"
    if api_key.startswith("sk-"):
        return "sk-****"
    return "****"


def setup_logging(level: str = "INFO") -> None:
    """初始化日志格式（幂等，可重复调用）"""
    global _logging_initialized
    logging.basicConfig(
        level=getattr(logging, str(level).upper(), logging.INFO),
        format="%(asctime)s %(levelname)s [trace=%(trace_id)s] %(name)s: %(message)s",
    )
    if _logging_initialized:
        return

    old_factory = logging.getLogRecordFactory()

    def record_factory(*args, **kwargs):
        record = old_factory(*args, **kwargs)
        if not hasattr(record, "trace_id"):
            record.trace_id = get_trace_id()
        return record

    logging.setLogRecordFactory(record_factory)
    _logging_initialized = True
