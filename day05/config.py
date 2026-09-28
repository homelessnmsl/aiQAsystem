"""第5天：配置集中管理

统一从仓库根目录 .env 读取配置；其他模块 `from .config import config` 使用，
不再散落 os.getenv。变量命名兼容团队 .env（LLM_MODEL / DEEPSEEK_BASE_URL / API_HOST / API_PORT）。
"""
import os
from pathlib import Path

from dotenv import load_dotenv

# 仓库根目录（day05/ 的上一级），.env 放在这里
BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR / ".env")


class Config:
    """应用配置类 - 集中管理所有配置项"""

    # ---------- 大模型 ----------
    DEEPSEEK_API_KEY = os.getenv("DEEPSEEK_API_KEY", "")
    DEEPSEEK_MODEL = os.getenv("LLM_MODEL") or os.getenv("DEEPSEEK_MODEL", "deepseek-chat")
    BASE_URL = os.getenv("DEEPSEEK_BASE_URL") or os.getenv("BASE_URL", "https://api.deepseek.com/v1")

    # ---------- 服务器 ----------
    HOST = os.getenv("API_HOST") or os.getenv("HOST", "127.0.0.1")
    PORT = int(os.getenv("API_PORT") or os.getenv("PORT", "8005"))

    # ---------- 对话 ----------
    MAX_HISTORY = int(os.getenv("MAX_HISTORY", "3"))
    DEFAULT_TEMPERATURE = float(os.getenv("DEFAULT_TEMPERATURE", "0.7"))

    @classmethod
    def validate(cls) -> bool:
        """验证必要的配置是否已设置"""
        if not cls.DEEPSEEK_API_KEY:
            print("[警告] DEEPSEEK_API_KEY 未设置，/api/chat 暂不可用；请检查 .env 文件")
            return False
        return True


# 全局配置实例
config = Config()
