from pydantic_settings import BaseSettings
from pydantic import Field
from functools import lru_cache
from pathlib import Path

# 查找 .env 文件 - 先检查项目根目录，Docker 环境则回退到当前目录
_candidate = Path(__file__).resolve().parent.parent.parent.parent / ".env"
ENV_FILE = str(_candidate) if _candidate.exists() else ".env"


class Settings(BaseSettings):
    # 应用
    APP_NAME: str = "MYRAG"
    DEBUG: bool = False
    API_V1_PREFIX: str = "/api/v1"

    # 基础目录（backend 文件夹）
    BASE_DIR: Path = Path(__file__).resolve().parent.parent.parent

    # 数据库
    DATABASE_URL: str = Field(default="postgresql+asyncpg://postgres:postgres@localhost:5433/myrag")

    # LLM 提供商："gemini" | "ollama"
    LLM_PROVIDER: str = Field(default="gemini")

    # Google AI
    GOOGLE_AI_API_KEY: str = Field(default="")

    # Ollama
    OLLAMA_HOST: str = Field(default="http://localhost:11434")
    OLLAMA_MODEL: str = Field(default="gemma3:12b")
    OLLAMA_ENABLE_THINKING: bool = Field(default=False)

    # LLM（用于对话 + 知识图谱抽取的快速模型——在 provider=gemini 时使用）
    LLM_MODEL_FAST: str = Field(default="gemini-2.5-flash")

    # Gemini 3.x+ 模型的思考级别："minimal" | "low" | "medium" | "high"
    # Gemini 2.5 改用 thinking_budget_tokens（自动检测）
    LLM_THINKING_LEVEL: str = Field(default="medium")

    # LLM 对话响应的最大输出 token 数（包含思考 token）
    # Gemini 3.1 Flash-Lite 最高支持 65536
    LLM_MAX_OUTPUT_TOKENS: int = Field(default=8192)

    # KG 嵌入提供商（可以与 LLM 提供商不同）
    KG_EMBEDDING_PROVIDER: str = Field(default="gemini")
    KG_EMBEDDING_MODEL: str = Field(default="gemini-embedding-001")
    KG_EMBEDDING_DIMENSION: int = Field(default=3072)

    # ChromaDB
    CHROMA_HOST: str = Field(default="localhost")
    CHROMA_PORT: int = Field(default=8002)

    # MYRAG 流水线
    MYRAG_ENABLED: bool = True
    MYRAG_ENABLE_KG: bool = True
    MYRAG_ENABLE_IMAGE_EXTRACTION: bool = True
    MYRAG_ENABLE_IMAGE_CAPTIONING: bool = True
    MYRAG_ENABLE_TABLE_CAPTIONING: bool = True
    MYRAG_MAX_TABLE_MARKDOWN_CHARS: int = 8000
    MYRAG_CHUNK_MAX_TOKENS: int = 512
    MYRAG_KG_QUERY_TIMEOUT: float = 30.0
    MYRAG_KG_CHUNK_TOKEN_SIZE: int = 1200
    MYRAG_KG_LANGUAGE: str = "English"
    MYRAG_KG_ENTITY_TYPES: list[str] = [
        "Organization", "Person", "Product", "Location", "Event",
        "Financial_Metric", "Technology", "Date", "Regulation",
    ]
    MYRAG_DEFAULT_QUERY_MODE: str = "hybrid"
    MYRAG_DOCLING_IMAGES_SCALE: float = 2.0
    MYRAG_MAX_IMAGES_PER_DOC: int = 50
    MYRAG_ENABLE_FORMULA_ENRICHMENT: bool = True

    # 文档解析器提供商："docling"（默认）或 "marker"（更轻量、数学公式更好）
    MYRAG_DOCUMENT_PARSER: str = "docling"
    MYRAG_MARKER_USE_LLM: bool = False

    # 处理超时（分钟）——超时的文档自动恢复为 FAILED
    MYRAG_PROCESSING_TIMEOUT_MINUTES: int = 10

    # 入库前去重
    MYRAG_DEDUP_ENABLED: bool = True
    MYRAG_DEDUP_MIN_CHUNK_LENGTH: int = 50       # 有意义字符的最小数量
    MYRAG_DEDUP_NEAR_THRESHOLD: float = 0.85     # Jaccard 相似度阈值

    # MYRAG 检索质量
    MYRAG_EMBEDDING_MODEL: str = "BAAI/bge-m3"
    MYRAG_RERANKER_MODEL: str = "BAAI/bge-reranker-v2-m3"
    MYRAG_VECTOR_PREFETCH: int = 20
    MYRAG_RERANKER_TOP_K: int = 8
    MYRAG_MIN_RELEVANCE_SCORE: float = 0.15

    # CORS 跨域配置
    CORS_ORIGINS: list[str] = ["http://localhost:5174", "http://localhost:3000"]

    model_config = {
        "env_file": str(ENV_FILE),
        "env_file_encoding": "utf-8",
        "extra": "ignore"
    }


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
