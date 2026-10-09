"""SQLite 台账（架构设计 7.1 / 7.2；W2-05/06/07）

- documents：文档台账（配合 Chroma 作为"账本"，架构 6.6 一致性策略）；
- conversations / messages：会话与消息明细（第2周先落库 messages，第3周会话接口复用）。

线程模型：FastAPI 同步路由在线程池执行，连接 check_same_thread=False + 写锁保护。
"""
from __future__ import annotations

import logging
import sqlite3
import threading
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from ..core.config import settings
from ..core.logging import now_iso

logger = logging.getLogger(__name__)

SCHEMA = """
CREATE TABLE IF NOT EXISTS documents (
    doc_id        TEXT PRIMARY KEY,
    filename      TEXT NOT NULL,
    file_type     TEXT NOT NULL,
    size_bytes    INTEGER NOT NULL,
    upload_time   TEXT NOT NULL,
    chunk_count   INTEGER DEFAULT 0,
    status        TEXT NOT NULL DEFAULT 'processing'
);

CREATE TABLE IF NOT EXISTS conversations (
    session_id    TEXT PRIMARY KEY,
    title         TEXT,
    created_at    TEXT NOT NULL,
    updated_at    TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS messages (
    message_id    TEXT PRIMARY KEY,
    session_id    TEXT NOT NULL,
    role          TEXT NOT NULL,
    content       TEXT NOT NULL,
    citations     TEXT,
    trace_id      TEXT,
    latency_ms    INTEGER,
    created_at    TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS feedback (
    feedback_id   TEXT PRIMARY KEY,
    message_id    TEXT NOT NULL,
    session_id    TEXT NOT NULL,
    rating        TEXT NOT NULL,
    comment       TEXT,
    created_at    TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_messages_session ON messages(session_id, created_at);
CREATE INDEX IF NOT EXISTS idx_feedback_session ON feedback(session_id);
"""


class Repository:
    """SQLite 台账访问层（documents / conversations / messages）"""

    def __init__(self, path: str | Path | None = None) -> None:
        self.path = Path(path) if path is not None else settings.sqlite_file
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._conn = sqlite3.connect(str(self.path), check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        with self._lock:
            self._conn.executescript(SCHEMA)
            self._conn.commit()
        logger.info("SQLite 台账就绪：%s", self.path)

    # ============================================================
    # documents（文档台账）
    # ============================================================
    def upsert_document(
        self,
        *,
        doc_id: str,
        filename: str,
        file_type: str,
        size_bytes: int,
        upload_time: str,
        chunk_count: int = 0,
        status: str = "processing",
    ) -> None:
        """写入/更新一条文档台账（先 processing，成功后 success，失败 failed）"""
        with self._lock:
            self._conn.execute(
                """
                INSERT INTO documents(doc_id, filename, file_type, size_bytes, upload_time, chunk_count, status)
                VALUES(?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(doc_id) DO UPDATE SET
                    filename=excluded.filename,
                    file_type=excluded.file_type,
                    size_bytes=excluded.size_bytes,
                    upload_time=excluded.upload_time,
                    chunk_count=excluded.chunk_count,
                    status=excluded.status
                """,
                (doc_id, filename, file_type, int(size_bytes), upload_time, int(chunk_count), status),
            )
            self._conn.commit()

    def get_document(self, doc_id: str) -> Optional[Dict[str, Any]]:
        """按 doc_id 查询台账"""
        with self._lock:
            row = self._conn.execute("SELECT * FROM documents WHERE doc_id = ?", (doc_id,)).fetchone()
        return dict(row) if row else None

    def list_documents(
        self,
        *,
        page: int = 1,
        page_size: int = 20,
        keyword: Optional[str] = None,
        file_type: Optional[str] = None,
        status: str = "success",
    ) -> Tuple[int, List[Dict[str, Any]]]:
        """分页查询台账：返回 (total, items)，items 按 upload_time 倒序（接口文档 2.4）"""
        where: List[str] = []
        params: List[Any] = []
        if status and status != "all":
            where.append("status = ?")
            params.append(status)
        if keyword:
            where.append("filename LIKE ?")
            params.append(f"%{keyword}%")
        if file_type:
            where.append("file_type = ?")
            params.append(file_type)
        clause = f" WHERE {' AND '.join(where)}" if where else ""

        with self._lock:
            total = int(self._conn.execute(f"SELECT COUNT(*) FROM documents{clause}", params).fetchone()[0])
            rows = self._conn.execute(
                f"SELECT * FROM documents{clause} ORDER BY upload_time DESC, doc_id DESC LIMIT ? OFFSET ?",
                [*params, int(page_size), (int(page) - 1) * int(page_size)],
            ).fetchall()
        return total, [dict(row) for row in rows]

    def count_documents(self, status: str = "success") -> int:
        """指定状态的文档数（健康检查/统计用）"""
        with self._lock:
            row = self._conn.execute("SELECT COUNT(*) FROM documents WHERE status = ?", (status,)).fetchone()
        return int(row[0])

    def sum_chunks(self, status: str = "success") -> int:
        """指定状态文档的切片总数（与 Chroma count 对账，架构 6.6）"""
        with self._lock:
            row = self._conn.execute(
                "SELECT COALESCE(SUM(chunk_count), 0) FROM documents WHERE status = ?", (status,)
            ).fetchone()
        return int(row[0])

    def delete_document_row(self, doc_id: str) -> None:
        """删除台账行（第3周删除接口预留，接口文档 2.5）"""
        with self._lock:
            self._conn.execute("DELETE FROM documents WHERE doc_id = ?", (doc_id,))
            self._conn.commit()

    def set_document_status(self, doc_id: str, status: str) -> None:
        """更新台账状态（删除接口用：status='deleted'，记录保留以便审计，接口文档 2.5）"""
        with self._lock:
            self._conn.execute("UPDATE documents SET status = ? WHERE doc_id = ?", (status, doc_id))
            self._conn.commit()

    def delete_all_documents(self) -> int:
        """清空文档台账（脚本 --rebuild 时与向量库同步重建），返回删除行数"""
        with self._lock:
            cursor = self._conn.execute("DELETE FROM documents")
            self._conn.commit()
        return int(cursor.rowcount)

    # ============================================================
    # conversations / messages（会话与消息）
    # ============================================================
    def ensure_conversation(self, session_id: str, title: Optional[str] = None) -> None:
        """确保会话存在（不覆盖已有标题），并刷新 updated_at"""
        timestamp = now_iso()
        with self._lock:
            self._conn.execute(
                """
                INSERT INTO conversations(session_id, title, created_at, updated_at)
                VALUES(?, ?, ?, ?)
                ON CONFLICT(session_id) DO UPDATE SET updated_at = excluded.updated_at
                """,
                (session_id, title, timestamp, timestamp),
            )
            self._conn.commit()

    def add_message(
        self,
        *,
        message_id: str,
        session_id: str,
        role: str,
        content: str,
        citations: Optional[str] = None,
        trace_id: Optional[str] = None,
        latency_ms: Optional[int] = None,
        created_at: Optional[str] = None,
    ) -> None:
        """写入一条消息（assistant 消息含 citations JSON，架构 7.2）"""
        with self._lock:
            self._conn.execute(
                """
                INSERT OR REPLACE INTO messages(message_id, session_id, role, content, citations, trace_id, latency_ms, created_at)
                VALUES(?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (message_id, session_id, role, content, citations, trace_id, latency_ms, created_at or now_iso()),
            )
            self._conn.commit()

    def list_messages(self, session_id: str) -> List[Dict[str, Any]]:
        """按时间顺序读取会话消息（第3周会话详情接口复用，接口文档 2.9）"""
        with self._lock:
            rows = self._conn.execute(
                "SELECT * FROM messages WHERE session_id = ? ORDER BY created_at, rowid", (session_id,)
            ).fetchall()
        return [dict(row) for row in rows]

    # ============================================================
    # 会话查询 / 反馈（W3：接口文档 2.7~2.10）
    # ============================================================
    def list_conversations(
        self,
        *,
        page: int = 1,
        page_size: int = 20,
        keyword: Optional[str] = None,
    ) -> Tuple[int, List[Dict[str, Any]]]:
        """会话列表（含消息数），按 updated_at 倒序（接口文档 2.8）"""
        where: List[str] = []
        params: List[Any] = []
        if keyword:
            where.append("c.title LIKE ?")
            params.append(f"%{keyword}%")
        clause = f" WHERE {' AND '.join(where)}" if where else ""

        with self._lock:
            total = int(self._conn.execute(f"SELECT COUNT(*) FROM conversations c{clause}", params).fetchone()[0])
            rows = self._conn.execute(
                f"""
                SELECT c.session_id, c.title, c.created_at, c.updated_at,
                       COUNT(m.message_id) AS message_count
                FROM conversations c
                LEFT JOIN messages m ON m.session_id = c.session_id
                {clause}
                GROUP BY c.session_id
                ORDER BY c.updated_at DESC, c.session_id DESC
                LIMIT ? OFFSET ?
                """,
                [*params, int(page_size), (int(page) - 1) * int(page_size)],
            ).fetchall()
        return total, [dict(row) for row in rows]

    def get_conversation(self, session_id: str) -> Optional[Dict[str, Any]]:
        """会话一行（不存在返回 None；接口文档 2.9 的 1005 判断用）"""
        with self._lock:
            row = self._conn.execute("SELECT * FROM conversations WHERE session_id = ?", (session_id,)).fetchone()
        return dict(row) if row else None

    def get_message(self, message_id: str) -> Optional[Dict[str, Any]]:
        """按 message_id 查消息（反馈接口校验用，接口文档 2.7）"""
        with self._lock:
            row = self._conn.execute("SELECT * FROM messages WHERE message_id = ?", (message_id,)).fetchone()
        return dict(row) if row else None

    def clear_messages(self, session_id: str) -> int:
        """清空会话消息（保留会话行），返回删除条数（接口文档 2.10；Q-01 决议）"""
        with self._lock:
            cursor = self._conn.execute("DELETE FROM messages WHERE session_id = ?", (session_id,))
            self._conn.commit()
        return int(cursor.rowcount)

    def add_feedback(
        self,
        *,
        feedback_id: str,
        message_id: str,
        session_id: str,
        rating: str,
        comment: Optional[str] = None,
        created_at: Optional[str] = None,
    ) -> None:
        """写入一条反馈（UC-08 / US-12，架构 7.2 feedback 表）"""
        with self._lock:
            self._conn.execute(
                "INSERT INTO feedback(feedback_id, message_id, session_id, rating, comment, created_at) VALUES(?,?,?,?,?,?)",
                (feedback_id, message_id, session_id, rating, comment, created_at or now_iso()),
            )
            self._conn.commit()


_repository: Optional[Repository] = None


def get_repository() -> Repository:
    """获取全局台账实例（懒加载单例）"""
    global _repository
    if _repository is None:
        _repository = Repository()
    return _repository
