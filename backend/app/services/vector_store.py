"""
向量存储服务
负责 ChromaDB 中文档向量的存储与检索。
"""
from __future__ import annotations

import logging
from typing import Sequence, Optional, TYPE_CHECKING
import chromadb
from chromadb.config import Settings as ChromaSettings

from app.core.config import settings

if TYPE_CHECKING:
    pass

logger = logging.getLogger(__name__)

# 全局 ChromaDB 客户端
_chroma_client: Optional[chromadb.HttpClient] = None


def get_chroma_client() -> chromadb.HttpClient:
    """获取或创建 ChromaDB 客户端单例。"""
    global _chroma_client

    if _chroma_client is None:
        logger.info(f"Connecting to ChromaDB at {settings.CHROMA_HOST}:{settings.CHROMA_PORT}")
        _chroma_client = chromadb.HttpClient(
            host=settings.CHROMA_HOST,
            port=settings.CHROMA_PORT,
            settings=ChromaSettings(
                anonymized_telemetry=False,
            )
        )
        # 测试连接
        _chroma_client.heartbeat()
        logger.info("Connected to ChromaDB successfully")

    return _chroma_client


class VectorStore:
    """
    用于在 ChromaDB 中管理文档向量的向量存储服务。
    每个知识库拥有独立的集合，以实现命名空间隔离。
    """

    COLLECTION_PREFIX = "kb_"

    def __init__(self, workspace_id: int):
        self.workspace_id = workspace_id
        self.collection_name = f"{self.COLLECTION_PREFIX}{workspace_id}"
        self._collection = None

    @property
    def collection(self) -> chromadb.Collection:
        """获取或创建集合。"""
        if self._collection is None:
            client = get_chroma_client()
            self._collection = client.get_or_create_collection(
                name=self.collection_name,
                metadata={"hnsw:space": "cosine"},
            )
        return self._collection

    def _recreate_collection(self) -> None:
        """删除并重建集合（重置缓存的引用）。"""
        client = get_chroma_client()
        try:
            client.delete_collection(self.collection_name)
            logger.info(f"Deleted collection {self.collection_name} for dimension migration")
        except Exception:
            pass
        self._collection = None
        # 强制重建
        _ = self.collection

    def add_documents(
        self,
        ids: Sequence[str],
        embeddings: Sequence[list[float]],
        documents: Sequence[str],
        metadatas: Sequence[dict] | None = None
    ) -> None:
        """
        向集合中添加文档及其向量。
        自动处理维度不匹配：如果集合创建时使用了不同的向量维度，
        则删除并重建集合。
        """
        if not ids:
            return

        try:
            self.collection.add(
                ids=list(ids),
                embeddings=list(embeddings),
                documents=list(documents),
                metadatas=list(metadatas) if metadatas else None
            )
        except Exception as e:
            error_msg = str(e).lower()
            if "dimension" in error_msg:
                # 维度不匹配 —— 集合是用旧向量模型创建的
                logger.warning(
                    f"Dimension mismatch in {self.collection_name}: {e}. "
                    f"Recreating collection for new embedding model."
                )
                self._recreate_collection()
                # 使用新集合重试
                self.collection.add(
                    ids=list(ids),
                    embeddings=list(embeddings),
                    documents=list(documents),
                    metadatas=list(metadatas) if metadatas else None
                )
            else:
                raise

        logger.info(f"Added {len(ids)} documents to collection {self.collection_name}")

    def upsert_documents(
        self,
        ids: Sequence[str],
        embeddings: Sequence[list[float]],
        documents: Sequence[str],
        metadatas: Sequence[dict] | None = None,
    ) -> None:
        """新增或覆盖分块。重复跑一次也不会因为 ID 已存在就当场翻脸。"""
        if not ids:
            return

        try:
            self.collection.upsert(
                ids=list(ids),
                embeddings=list(embeddings),
                documents=list(documents),
                metadatas=list(metadatas) if metadatas else None,
            )
        except Exception as e:
            if "dimension" not in str(e).lower():
                raise

            # 换了向量维度，旧集合本来就没法混用。这里沿用项目原来的重建策略。
            logger.warning(
                f"Dimension mismatch in {self.collection_name}: {e}. "
                "Recreating collection for the new embedding model."
            )
            self._recreate_collection()
            self.collection.upsert(
                ids=list(ids),
                embeddings=list(embeddings),
                documents=list(documents),
                metadatas=list(metadatas) if metadatas else None,
            )

        logger.info(f"Upserted {len(ids)} documents into collection {self.collection_name}")

    def query(
        self,
        query_embedding: list[float],
        n_results: int = 5,
        where: dict | None = None,
        include: list[str] | None = None
    ) -> dict:
        """查询集合中相似的文档。"""
        if include is None:
            include = ["documents", "metadatas", "distances"]

        try:
            results = self.collection.query(
                query_embeddings=[query_embedding],
                n_results=n_results,
                where=where,
                include=include
            )
        except Exception as e:
            error_msg = str(e).lower()
            if "dimension" in error_msg:
                # 使用新维度向量查询旧集合
                logger.warning(
                    f"Dimension mismatch on query in {self.collection_name}: {e}. "
                    f"Collection needs reindexing."
                )
                return {"ids": [], "documents": [], "metadatas": [], "distances": []}
            raise

        # 展平单条查询结果
        return {
            "ids": results["ids"][0] if results["ids"] else [],
            "documents": results["documents"][0] if results.get("documents") else [],
            "metadatas": results["metadatas"][0] if results.get("metadatas") else [],
            "distances": results["distances"][0] if results.get("distances") else []
        }

    def delete_by_document_id(self, document_id: int) -> None:
        """删除指定文档的所有分块。"""
        self.collection.delete(
            where={"document_id": document_id}
        )
        logger.info(f"Deleted chunks for document {document_id} from collection {self.collection_name}")

    def delete_by_ids(self, ids: Sequence[str]) -> None:
        """只删点名的旧分块，别一激动把整个知识库扬了。"""
        if not ids:
            return
        self.collection.delete(ids=list(ids))
        logger.info(f"Deleted {len(ids)} stale chunks from collection {self.collection_name}")

    def get_ids_by_document_id(self, document_id: int) -> list[str]:
        """拿到某篇文档现在占着的向量 ID，用来清理变短后多出来的尾巴。"""
        result = self.collection.get(
            where={"document_id": document_id},
            include=["metadatas"],
        )
        return list(result.get("ids") or [])

    def delete_collection(self) -> None:
        """删除该知识库的整个集合。"""
        client = get_chroma_client()
        try:
            client.delete_collection(self.collection_name)
            self._collection = None
            logger.info(f"Deleted collection {self.collection_name}")
        except Exception as e:
            logger.warning(f"Failed to delete collection {self.collection_name}: {e}")

    def count(self) -> int:
        """返回集合中的文档数量。"""
        return self.collection.count()

    def get_by_ids(self, ids: Sequence[str]) -> dict:
        """按 ID 获取文档。"""
        return self.collection.get(
            ids=list(ids),
            include=["documents", "metadatas"]
        )


def get_vector_store(workspace_id: int) -> VectorStore:
    """为知识库创建 VectorStore 的工厂函数。"""
    return VectorStore(workspace_id)
