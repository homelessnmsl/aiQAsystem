"""对话历史管理（沿用第2天）"""
from typing import Dict, List


class ConversationManager:
    """对话历史管理器：多 Session 隔离、按轮数截断"""

    def __init__(self, max_history: int = 3):
        self.sessions: Dict[str, List[Dict[str, str]]] = {}
        self.max_history = max_history

    def get_or_create_session(self, session_id: str) -> List[Dict[str, str]]:
        if session_id not in self.sessions:
            self.sessions[session_id] = []
        return self.sessions[session_id]

    def add_message(self, session_id: str, role: str, content: str):
        history = self.get_or_create_session(session_id)
        history.append({"role": role, "content": content})
        if len(history) > self.max_history * 2:
            self.sessions[session_id] = history[-self.max_history * 2:]

    def get_history(self, session_id: str) -> List[Dict[str, str]]:
        return self.get_or_create_session(session_id)

    def clear_session(self, session_id: str):
        if session_id in self.sessions:
            self.sessions[session_id] = []

    def get_history_length(self, session_id: str) -> int:
        return len(self.get_history(session_id))

    def get_session_count(self) -> int:
        return len(self.sessions)
