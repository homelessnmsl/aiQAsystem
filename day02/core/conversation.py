"""对话历史管理（第2天课程核心）

多 Session 隔离：每个用户（session_id）有独立的对话历史；
按轮数截断：只保留最近 max_history 轮（user + assistant 成对）。
"""
from typing import Dict, List


class ConversationManager:
    """对话历史管理器"""

    def __init__(self, max_history: int = 3):
        """
        Args:
            max_history: 最大保留轮数（每轮 = user + assistant 两条消息）
        """
        self.sessions: Dict[str, List[Dict[str, str]]] = {}
        self.max_history = max_history

    def get_or_create_session(self, session_id: str) -> List[Dict[str, str]]:
        """获取或创建会话"""
        if session_id not in self.sessions:
            self.sessions[session_id] = []
        return self.sessions[session_id]

    def add_message(self, session_id: str, role: str, content: str):
        """添加消息并限制历史长度（保留最近 max_history 轮）"""
        history = self.get_or_create_session(session_id)
        history.append({"role": role, "content": content})
        if len(history) > self.max_history * 2:
            self.sessions[session_id] = history[-self.max_history * 2:]

    def get_history(self, session_id: str) -> List[Dict[str, str]]:
        """获取会话历史"""
        return self.get_or_create_session(session_id)

    def clear_session(self, session_id: str):
        """清空会话（保留 session_id）"""
        if session_id in self.sessions:
            self.sessions[session_id] = []

    def get_history_length(self, session_id: str) -> int:
        """会话消息条数"""
        return len(self.get_history(session_id))

    def get_session_count(self) -> int:
        """当前活跃会话数"""
        return len(self.sessions)
