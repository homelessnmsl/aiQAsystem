"""应用配置：.env → Settings（架构设计 9.5；W1-13）

约定（架构 4.3-2）：业务代码不得散落 os.getenv，统一 `from app.core.config import settings`。

说明：与接口文档 SM-04 对齐——未配置 DEEPSEEK_API_KEY 时服务仍可启动（启动打印警告），
调用 /api/chat 时返回 code=3003「服务未配置模型密钥，请联系管理员」。
"""
from pathlib import Path
from typing import List

from pydantic_settings import BaseSettings, SettingsConfigDict

# 仓库根目录（app/ 的上一级），.env 放在这里
BASE_DIR = Path(__file__).resolve().parent.parent.parent
ENV_FILE = BASE_DIR / ".env"


class Settings(BaseSettings):
    """全局配置（字段与环境变量一一对应；完整清单见 .env.example / 架构设计 9.5）"""

    model_config = SettingsConfigDict(
        env_file=str(ENV_FILE),
        env_file_encoding="utf-8",
        extra="ignore",  # 第2周起的变量（Embedding/RAG/切片等）先忽略
    )

    # ---------- 服务（架构 9.5「服务」组） ----------
    API_HOST: str = "127.0.0.1"
    API_PORT: int = 8000
    LOG_LEVEL: str = "INFO"
    DEMO_MODE: bool = False

    # ---------- LLM（架构 9.5「LLM」组） ----------
    LLM_PROVIDER: str = "deepseek"
    DEEPSEEK_API_KEY: str = ""
    DEEPSEEK_BASE_URL: str = "https://api.deepseek.com"
    LLM_MODEL: str = "deepseek-chat"
    LLM_TIMEOUT_SECONDS: int = 60
    LLM_MAX_RETRIES: int = 1
    LLM_TEMPERATURE: float = 0.3
    LLM_MAX_TOKENS: int = 1024

    # ---------- 应用信息 ----------
    APP_VERSION: str = "0.1.0"

    @property
    def llm_configured(self) -> bool:
        """是否已配置模型密钥（健康检查与 /api/chat 前置判断用）"""
        return bool(self.DEEPSEEK_API_KEY.strip())

    def validate_warnings(self) -> List[str]:
        """启动自检：返回需要打印的中文警告（不阻止启动，见接口文档 SM-04）"""
        warnings: List[str] = []
        if not self.llm_configured:
            warnings.append(
                "未检测到 DEEPSEEK_API_KEY：/api/chat 将返回错误码 3003。"
                "请在仓库根目录 .env 中配置（可参考 .env.example）。"
            )
        return warnings


# 全局配置实例（全组唯一入口）
settings = Settings()
