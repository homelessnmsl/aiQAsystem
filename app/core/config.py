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
        extra="ignore",  # 容忍 .env 中的额外变量（不报错）
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

    # ---------- Embedding（架构 9.5；W2-03 起使用） ----------
    EMBEDDING_PROVIDER: str = "local"          # local | siliconflow | dashscope
    EMBEDDING_MODEL: str = "BAAI/bge-small-zh-v1.5"
    EMBEDDING_DIM: int = 512
    EMBEDDING_BATCH_SIZE: int = 32
    EMBEDDING_DEVICE: str = "cpu"
    SILICONFLOW_API_KEY: str = ""
    SILICONFLOW_BASE_URL: str = "https://api.siliconflow.cn/v1"
    DASHSCOPE_API_KEY: str = ""

    # ---------- Rerank（架构 9.5；第3周启用） ----------
    RERANK_ENABLED: bool = False
    RERANK_PROVIDER: str = "local"
    RERANK_MODEL: str = "BAAI/bge-reranker-base"

    # ---------- 检索与生成（架构 6.8 / 9.5） ----------
    RETRIEVE_K: int = 20
    TOP_K: int = 5
    SCORE_THRESHOLD: float = 0.35
    MAX_CONTEXT_TOKENS: int = 3000
    ANSWER_MAX_CHARS: int = 200

    # ---------- 切片（架构 6.4；W2-03） ----------
    CHUNK_SIZE: int = 500
    CHUNK_OVERLAP: int = 80
    MIN_CHUNK_CHARS: int = 80
    CHUNK_MERGE_TARGET: int = 300   # 短块合并目标长度（架构 6.4：向 300~600 字靠拢）
    EXCEL_ROWS_PER_CHUNK: int = 20

    # ---------- 存储路径（架构 9.5） ----------
    CHROMA_DIR: str = "./data/chroma"
    CHROMA_COLLECTION: str = "enterprise_kb"
    UPLOAD_DIR: str = "./data/uploads"
    SQLITE_PATH: str = "./data/app.db"

    # ---------- 上传限制（FR-DOC-02 / FR-SEC-03） ----------
    MAX_FILE_SIZE_MB: int = 20
    MAX_FILES_PER_UPLOAD: int = 5

    # ---------- 应用信息 ----------
    APP_VERSION: str = "0.1.0"

    @property
    def llm_configured(self) -> bool:
        """是否已配置模型密钥（健康检查与 /api/chat 前置判断用）"""
        return bool(self.DEEPSEEK_API_KEY.strip())

    # ---------- 路径解析（第2周：相对路径统一相对仓库根目录） ----------
    def _resolve(self, raw: str) -> Path:
        """把 .env 中的相对路径按仓库根目录解析（避免受启动目录影响）"""
        path = Path(raw).expanduser()
        return path if path.is_absolute() else (BASE_DIR / path).resolve()

    @property
    def chroma_dir(self) -> Path:
        """Chroma 持久化目录（架构 6.6）"""
        return self._resolve(self.CHROMA_DIR)

    @property
    def upload_dir(self) -> Path:
        """上传文件存放目录（NFR-S-02）"""
        return self._resolve(self.UPLOAD_DIR)

    @property
    def sqlite_file(self) -> Path:
        """SQLite 数据库文件（DEV 的 repository 使用）"""
        return self._resolve(self.SQLITE_PATH)

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
