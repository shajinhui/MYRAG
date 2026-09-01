"""
重排序服务
================
用于提升检索精度的交叉编码器重排序器。

默认模型：BAAI/bge-reranker-v2-m3（多语言、支持 100+ 种语言）。
可通过设置中的 MYRAG_RERANKER_MODEL 配置。

用法：
    reranker = get_reranker_service()
    ranked = reranker.rerank("用户问题", ["chunk1", "chunk2", ...], top_k=5)
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Optional, Sequence

from app.core.config import settings

logger = logging.getLogger(__name__)


@dataclass
class RerankResult:
    """带原始索引和相关性分数的单个重排序结果。"""
    index: int          # 在输入列表中的原始位置
    score: float        # 交叉编码器相关性分数（越高越相关）
    text: str           # 分块文本


class RerankerService:
    """
    交叉编码器重排序服务。
    通过 Transformer 对（查询，文档）对进行联合打分，
    得到比双编码器余弦相似度准确得多的相关性分数。
    """

    def __init__(self, model_name: Optional[str] = None):
        self.model_name = model_name or settings.MYRAG_RERANKER_MODEL
        self._model = None

    @property
    def model(self):
        """延迟加载交叉编码器模型。"""
        if self._model is None:
            from sentence_transformers import CrossEncoder
            logger.info(f"Loading reranker model: {self.model_name}")
            self._model = CrossEncoder(self.model_name)
            logger.info(f"Reranker model loaded: {self.model_name}")
        return self._model

    def rerank(
        self,
        query: str,
        documents: Sequence[str],
        top_k: Optional[int] = None,
        min_score: Optional[float] = None,
    ) -> list[RerankResult]:
        """
        按与查询的相关性对文档进行重排序。

        参数：
            query: 用户的搜索查询
            documents: 需要重排序的文档文本列表
            top_k: 最多返回的结果数（None = 全部）
            min_score: 最小相关性分数阈值（None = 不过滤）

        返回：
            按分数降序排列的 RerankResult 列表，
            并受 top_k 与 min_score 过滤。
        """
        if not documents:
            return []

        # 为交叉编码器构建（查询，文档）对
        pairs = [(query, doc) for doc in documents]

        # 在单个批次中为所有配对打分
        scores = self.model.predict(pairs, batch_size=32).tolist()

        # 使用原始索引构建结果
        results = [
            RerankResult(index=i, score=s, text=doc)
            for i, (s, doc) in enumerate(zip(scores, documents))
        ]

        # 按分数降序排序（最相关的排在最前）
        results.sort(key=lambda r: r.score, reverse=True)

        # 应用 min_score 过滤
        if min_score is not None:
            results = [r for r in results if r.score >= min_score]

        # 应用 top_k 限制
        if top_k is not None:
            results = results[:top_k]

        return results


# 单例实例
_default_service: Optional[RerankerService] = None


def get_reranker_service() -> RerankerService:
    """获取或创建默认的重排序服务。"""
    global _default_service
    if _default_service is None:
        _default_service = RerankerService()
    return _default_service
