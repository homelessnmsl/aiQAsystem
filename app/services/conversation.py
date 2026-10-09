"""会话历史管理（第1周：内存实现；第2~3周迁移 SQLite messages 表）

接口文档 2.2：session_id 传入则带上该会话历史（最近 10 轮）；不传则自动新建会话。
会话 ID 规则：conv_{yyyymmdd}_{6位}（接口文档 1.5）。
"""
import threading
from datetime import datetime
from typing import Dict, List

from ..core.logging import CST, random_id_suffix


def new_session_id() -> str:
    """生成会话 ID：conv_20261001_7d2e10（接口文档 1.5）"""
    return f"conv_{datetime.now(CST):%Y%m%d}_{random_id_suffix()}"


def new_message_id() -> str:
    """生成消息 ID：msg_20261008_5e6f70（接口文档 1.5）"""
    return f"msg_{datetime.now(CST):%Y%m%d}_{random_id_suffix()}"


def new_feedback_id() -> str:
    """生成反馈 ID：fb_20261008_0c1d2e（接口文档 2.7 响应示例）"""
    return f"fb_{datetime.now(CST):%Y%m%d}_{random_id_suffix()}"


class ConversationStore:
    """内存版会话历史：{session_id: [{"role","content"}, ...]}（线程安全）"""

    def __init__(self, max_rounds: int = 10):
        """max_rounds：保留最近多少轮（user/assistant 成对，接口文档 2.2）"""
        self.max_rounds = max_rounds
        self._sessions: Dict[str, List[Dict[str, str]]] = {}
        self._lock = threading.Lock()

    def ensure(self, session_id: str | None) -> str:
        """传入 session_id 则沿用（不存在则创建该 ID）；不传则自动新建"""
        sid = session_id or new_session_id()
        with self._lock:
            self._sessions.setdefault(sid, [])
        return sid

    def history(self, session_id: str) -> List[Dict[str, str]]:
        """最近 max_rounds 轮历史（最多 max_rounds*2 条）"""
        with self._lock:
            return list(self._sessions.get(session_id, []))

    def append(self, session_id: str, role: str, content: str) -> None:
        """追加一条消息，并按 max_rounds 截断"""
        with self._lock:
            records = self._sessions.setdefault(session_id, [])
            records.append({"role": role, "content": content})
            keep = self.max_rounds * 2
            if len(records) > keep:
                del records[: len(records) - keep]

    def clear(self, session_id: str) -> None:
        """清空会话（保留 session_id）"""
        with self._lock:
            self._sessions[session_id] = []

    def session_count(self) -> int:
        """当前活跃会话数"""
        with self._lock:
            return len(self._sessions)


#: 全局单例（第2周迁移 SQLite 后由 app/services/repository.py 替代）
conversation_store = ConversationStore(max_rounds=10)
