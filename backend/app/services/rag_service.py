"""
RAG（检索增强生成）服务
负责编排文档处理、索引与检索的主服务。
"""
from __future__ import annotations

import logging
import uuid
from datetime import datetime
from pathlib import Path
from dataclasses import dataclass
from typing import Optional

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.models.document import Document, DocumentStatus
from app.services.document_loader import load_document, LoadedDocument
from app.services.chunker import DocumentChunker, TextChunk
from app.services.embedder import EmbeddingService, get_embedding_service
from app.services.vector_store import VectorStore, get_vector_store
from app.services.index_version import file_hash, index_fingerprint

logger = logging.getLogger(__name__)


@dataclass
class RetrievedChunk:
    """表示带相关性分数的检索分块。"""
    content: str
    metadata: dict
    score: float  # 分数越低越相似（距离）
    chunk_id: str


@dataclass
class RAGQueryResult:
    """RAG 查询结果。"""
    chunks: list[RetrievedChunk]
    context: str  # 拼接后的分块，供 LLM 作为上下文
    query: str


class RAGService:
    """
    处理文档处理与检索的主 RAG 服务。
    """

    def __init__(
        self,
        db: AsyncSession,
        workspace_id: int,
        chunk_size: int = 500,
        chunk_overlap: int = 50
    ):
        """
        初始化 RAG 服务。

        参数：
            db: 数据库会话
            workspace_id: 用于隔离的知识库 ID
            chunk_size: 文本分块大小
            chunk_overlap: 分块之间的重叠
        """
        self.db = db
        self.workspace_id = workspace_id
        self.chunker = DocumentChunker(chunk_size=chunk_size, chunk_overlap=chunk_overlap)
        self.embedder = get_embedding_service()
        self.vector_store = get_vector_store(workspace_id)

    async def process_document(self, document_id: int, file_path: str) -> int:
        """
        处理文档：加载、切分、向量化并存储。

        参数：
            document_id: 数据库中的文档 ID
            file_path: 文档文件路径

        返回：
            创建的分块数量

        抛出：
            ValueError: 文档处理失败时
        """
        # 从数据库获取文档
        result = await self.db.execute(
            select(Document).where(Document.id == document_id)
        )
        document = result.scalar_one_or_none()

        if document is None:
            raise ValueError(f"Document {document_id} not found")

        new_content_hash = file_hash(file_path)
        new_index_fingerprint = index_fingerprint()

        try:
            if (
                document.content_hash == new_content_hash
                and document.index_fingerprint == new_index_fingerprint
                and document.indexed_at is not None
            ):
                document.status = DocumentStatus.INDEXED
                document.error_message = None
                await self.db.commit()
                logger.info(f"Document {document_id} unchanged; skipped indexing")
                return document.chunk_count

            # 将状态更新为处理中
            document.status = DocumentStatus.PROCESSING
            await self.db.commit()

            import asyncio

            old_ids = set(await asyncio.to_thread(
                self.vector_store.get_ids_by_document_id,
                document_id,
            ))

            def _process_sync():
                # 加载文档
                logger.info(f"Loading document {document_id} from {file_path}")
                loaded = load_document(file_path)

                # 切分文本
                logger.info(f"Chunking document {document_id}")
                chunks = self.chunker.split_text(
                    text=loaded.content,
                    source=document.original_filename,
                    extra_metadata={
                        "document_id": document_id,
                        "file_type": loaded.file_type,
                        "page_count": loaded.page_count
                    }
                )

                if not chunks:
                    self.vector_store.delete_by_ids(list(old_ids))
                    return []

                # 生成向量
                logger.info(f"Generating embeddings for {len(chunks)} chunks")
                chunk_texts = [c.content for c in chunks]
                embeddings = self.embedder.embed_texts(chunk_texts)

                # 为向量存储准备数据
                ids = [f"doc_{document_id}_chunk_{i}" for i in range(len(chunks))]
                metadatas = []
                for c in chunks:
                    meta = {
                        "document_id": document_id,
                        "chunk_index": c.chunk_index,
                        "char_start": c.char_start,
                        "char_end": c.char_end,
                        "source": c.metadata.get("source", ""),
                        "file_type": c.metadata.get("file_type", "")
                    }
                    if document.custom_metadata:
                        meta.update(document.custom_metadata)
                    metadatas.append(meta)

                # 存入向量数据库
                logger.info(f"Storing {len(chunks)} chunks in vector store")
                self.vector_store.upsert_documents(
                    ids=ids,
                    embeddings=embeddings,
                    documents=chunk_texts,
                    metadatas=metadatas
                )
                self.vector_store.delete_by_ids(list(old_ids - set(ids)))
                return chunks

            # 在线程池中运行同步的 CPU / IO 阻塞代码
            chunks = await asyncio.to_thread(_process_sync)

            if not chunks:
                document.status = DocumentStatus.INDEXED
                document.chunk_count = 0
                document.content_hash = new_content_hash
                document.index_fingerprint = new_index_fingerprint
                document.indexed_at = datetime.utcnow()
                document.error_message = None
                await self.db.commit()
                logger.warning(f"Document {document_id} produced no chunks (empty content)")
                return 0


            # 更新文档状态
            document.status = DocumentStatus.INDEXED
            document.chunk_count = len(chunks)
            document.content_hash = new_content_hash
            document.index_fingerprint = new_index_fingerprint
            document.indexed_at = datetime.utcnow()
            document.error_message = None
            await self.db.commit()

            logger.info(f"Successfully processed document {document_id}: {len(chunks)} chunks")
            return len(chunks)

        except Exception as e:
            logger.error(f"Failed to process document {document_id}: {e}")
            document.status = DocumentStatus.FAILED
            document.error_message = str(e)[:500]
            await self.db.commit()
            raise

    async def delete_document(self, document_id: int) -> None:
        """
        从向量存储中删除文档的分块。

        参数：
            document_id: 数据库中的文档 ID
        """
        self.vector_store.delete_by_document_id(document_id)
        logger.info(f"Deleted document {document_id} from vector store")

    def query(
        self,
        question: str,
        top_k: int = 5,
        document_ids: list[int] | None = None
    ) -> RAGQueryResult:
        """
        查询向量存储以获取相关分块。

        参数：
            question: 查询问题
            top_k: 需要检索的分块数量
            document_ids: 可选，按指定文档过滤

        返回：
            包含检索分块与组装上下文的 RAGQueryResult
        """
        # 生成查询向量
        query_embedding = self.embedder.embed_query(question)

        # 构建过滤条件
        where = None
        if document_ids:
            where = {"document_id": {"$in": document_ids}}

        # 查询向量存储
        results = self.vector_store.query(
            query_embedding=query_embedding,
            n_results=top_k,
            where=where
        )

        # 构建检索分块
        chunks = []
        for i, doc in enumerate(results["documents"]):
            chunks.append(RetrievedChunk(
                content=doc,
                metadata=results["metadatas"][i] if results["metadatas"] else {},
                score=results["distances"][i] if results["distances"] else 0.0,
                chunk_id=results["ids"][i] if results["ids"] else ""
            ))

        # 按分数排序（距离越小越相似）
        chunks.sort(key=lambda x: x.score)

        # 组装上下文
        context_parts = []
        for i, chunk in enumerate(chunks):
            source = chunk.metadata.get("source", "Unknown")
            context_parts.append(f"[Source: {source}, Chunk {i+1}]\n{chunk.content}")

        context = "\n\n---\n\n".join(context_parts)

        return RAGQueryResult(
            chunks=chunks,
            context=context,
            query=question
        )

    def get_chunk_count(self) -> int:
        """返回知识库向量存储中的分块总数。"""
        return self.vector_store.count()


def get_rag_service(
    db: AsyncSession,
    workspace_id: int,
    kg_language: str | None = None,
    kg_entity_types: list[str] | None = None,
) -> "RAGService | MYRAGService":
    """工厂函数：根据配置路由到 MYRAGService 或旧版 RAGService。"""
    from app.core.config import settings

    if settings.MYRAG_ENABLED:
        from app.services.my_rag_service import MYRAGService
        return MYRAGService(
            db=db,
            workspace_id=workspace_id,
            kg_language=kg_language,
            kg_entity_types=kg_entity_types,
        )

    return RAGService(db=db, workspace_id=workspace_id)
