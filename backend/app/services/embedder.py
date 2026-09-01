"""
向量化服务
=================
使用 sentence-transformers 生成向量嵌入。

默认模型：BAAI/bge-m3（1024 维、多语言、支持 100+ 种语言）。
可通过设置中的 MYRAG_EMBEDDING_MODEL 配置。
"""
from __future__ import annotations

import logging
from typing import Sequence, Optional

from app.core.config import settings

logger = logging.getLogger(__name__)


class EmbeddingService:
    """
    用于生成文本向量的服务。
    使用 sentence-transformers 在本地生成向量。
    """

    # 常见模型的维度查询表（在模型加载前使用）
    _KNOWN_DIMS = {
        "BAAI/bge-m3": 1024,
        "all-MiniLM-L6-v2": 384,
        "all-mpnet-base-v2": 768,
        "paraphrase-multilingual-MiniLM-L12-v2": 384,
        "intfloat/multilingual-e5-large-instruct": 1024,
    }

    def __init__(self, model_name: Optional[str] = None):
        self.model_name = model_name or settings.MYRAG_EMBEDDING_MODEL
        self._model = None

    @property
    def model(self):
        """延迟加载模型。"""
        if self._model is None:
            from sentence_transformers import SentenceTransformer
            logger.info(f"Loading embedding model: {self.model_name}")
            self._model = SentenceTransformer(self.model_name)
            logger.info(
                f"Embedding model loaded: {self.model_name} "
                f"(dim={self._model.get_sentence_embedding_dimension()})"
            )
        return self._model

    @property
    def dimension(self) -> int:
        """返回向量维度大小。"""
        if self._model is not None:
            return self._model.get_sentence_embedding_dimension()
        return self._KNOWN_DIMS.get(self.model_name, 1024)

    def embed_text(self, text: str) -> list[float]:
        """为单段文本生成向量。"""
        if not text.strip():
            raise ValueError("Cannot embed empty text")
        embedding = self.model.encode(
            text,
            convert_to_numpy=True,
            normalize_embeddings=True,
        )
        return embedding.tolist()

    def embed_texts(self, texts: Sequence[str]) -> list[list[float]]:
        """批量生成多段文本的向量。"""
        if not texts:
            return []
        valid_texts = [t for t in texts if t.strip()]
        if not valid_texts:
            raise ValueError("All texts are empty")
        embeddings = self.model.encode(
            valid_texts,
            convert_to_numpy=True,
            normalize_embeddings=True,
            batch_size=32,
        )
        return embeddings.tolist()

    def embed_query(self, query: str) -> list[float]:
        """为搜索查询生成向量。"""
        return self.embed_text(query)


# 默认服务实例（单例）
_default_service: Optional[EmbeddingService] = None


def get_embedding_service() -> EmbeddingService:
    """获取或创建默认的向量化服务。"""
    global _default_service
    if _default_service is None:
        _default_service = EmbeddingService()
    return _default_service


def embed_text(text: str) -> list[float]:
    """为单段文本生成向量的便捷函数。"""
    return get_embedding_service().embed_text(text)


def embed_texts(texts: Sequence[str]) -> list[list[float]]:
    """为多段文本生成向量的便捷函数。"""
    return get_embedding_service().embed_texts(texts)
