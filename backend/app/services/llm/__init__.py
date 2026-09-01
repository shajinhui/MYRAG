"""
LLM 提供商包
=====================
根据配置创建 LLM 与向量提供商对象的工厂函数。

用法::

    from app.services.llm import get_llm_provider, get_embedding_provider

    llm = get_llm_provider()          # 使用 .env 中的 LLM_PROVIDER
    emb = get_embedding_provider()    # 使用 .env 中的 KG_EMBEDDING_PROVIDER
"""
from __future__ import annotations

from functools import lru_cache

from app.services.llm.base import EmbeddingProvider, LLMProvider


@lru_cache
def get_llm_provider() -> LLMProvider:
    """创建（并缓存）由 ``LLM_PROVIDER`` 配置的 LLM 提供商。"""
    from app.core.config import settings

    provider = settings.LLM_PROVIDER.lower()

    if provider == "gemini":
        from app.services.llm.gemini import GeminiLLMProvider

        if not settings.GOOGLE_AI_API_KEY:
            raise ValueError("GOOGLE_AI_API_KEY is required when LLM_PROVIDER=gemini")
        return GeminiLLMProvider(
            api_key=settings.GOOGLE_AI_API_KEY,
            model=settings.LLM_MODEL_FAST,
            thinking_level=settings.LLM_THINKING_LEVEL,
        )

    if provider == "ollama":
        from app.services.llm.ollama import OllamaLLMProvider

        return OllamaLLMProvider(
            host=settings.OLLAMA_HOST,
            model=settings.OLLAMA_MODEL,
        )

    raise ValueError(f"Unknown LLM_PROVIDER: {provider!r}. Supported: gemini, ollama")


@lru_cache
def get_embedding_provider() -> EmbeddingProvider:
    """创建（并缓存）供知识图谱（LightRAG）使用的向量提供商。"""
    from app.core.config import settings

    provider = settings.KG_EMBEDDING_PROVIDER.lower()

    if provider == "gemini":
        from app.services.llm.gemini import GeminiEmbeddingProvider

        if not settings.GOOGLE_AI_API_KEY:
            raise ValueError("GOOGLE_AI_API_KEY is required when KG_EMBEDDING_PROVIDER=gemini")
        return GeminiEmbeddingProvider(
            api_key=settings.GOOGLE_AI_API_KEY,
            model=settings.KG_EMBEDDING_MODEL,
        )

    if provider == "ollama":
        from app.services.llm.ollama import OllamaEmbeddingProvider

        return OllamaEmbeddingProvider(
            host=settings.OLLAMA_HOST,
            model=settings.KG_EMBEDDING_MODEL,
        )

    if provider == "sentence_transformers":
        from app.services.llm.sentence_transformer import SentenceTransformerEmbeddingProvider

        return SentenceTransformerEmbeddingProvider(
            model=settings.KG_EMBEDDING_MODEL,
        )

    raise ValueError(
        f"Unknown KG_EMBEDDING_PROVIDER: {provider!r}. "
        "Supported: gemini, ollama, sentence_transformers"
    )


__all__ = [
    "get_llm_provider",
    "get_embedding_provider",
    "LLMProvider",
    "EmbeddingProvider",
]
