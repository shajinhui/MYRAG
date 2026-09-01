"""
深度 RAG 服务
=================

MYRAG 流水线的编排器：
  文档 → Docling 解析 → ChromaDB 索引 + LightRAG 知识图谱 → 混合检索

向后兼容：暴露与旧版 RAGService 相同的 `process_document()`、`query()`、
`delete_document()`、`get_chunk_count()` 接口。
"""
from __future__ import annotations

import logging
import time
from datetime import datetime
from typing import Optional

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, delete

from app.core.config import settings
from app.models.document import Document, DocumentImage, DocumentTable, DocumentStatus
from app.services.document_parser import get_document_parser
from app.services.knowledge_graph_service import KnowledgeGraphService
from app.services.deep_retriever import DeepRetriever
from app.services.embedder import EmbeddingService, get_embedding_service
from app.services.vector_store import VectorStore, get_vector_store
from app.services.reranker import get_reranker_service
from app.services.rag_service import RAGQueryResult, RetrievedChunk
from app.services.models.parsed_document import DeepRetrievalResult
from app.services.chunk_dedup import deduplicate_chunks
from app.services.index_version import file_hash, index_fingerprint

logger = logging.getLogger(__name__)


class MYRAGService:
    """
    完整的 MYRAG 流水线编排器。

    阶段：
      1. PARSING（解析）—— Docling 解析 → markdown + 分块 + 图片
      2. INDEXING（索引）—— 向量化分块 → ChromaDB + 写入 markdown → LightRAG 知识图谱
      3. INDEXED（已索引）—— 更新数据库中的文档元数据

    查询：
      - query()       —— 向后兼容的同步纯向量检索
      - query_deep()  —— 完整的异步混合检索（知识图谱 + 向量 + 图片）
    """

    def __init__(
        self,
        db: AsyncSession,
        workspace_id: int,
        kg_language: str | None = None,
        kg_entity_types: list[str] | None = None,
    ):
        self.db = db
        self.workspace_id = workspace_id

        # 服务
        self.parser = get_document_parser(workspace_id=workspace_id)
        self.embedder = get_embedding_service()
        self.vector_store = get_vector_store(workspace_id)

        # 知识图谱服务（可选，由配置控制）
        self.kg_service: Optional[KnowledgeGraphService] = None
        if settings.MYRAG_ENABLE_KG:
            self.kg_service = KnowledgeGraphService(
                workspace_id=workspace_id,
                kg_language=kg_language,
                kg_entity_types=kg_entity_types,
            )

        # 检索器（带交叉编码器重排序）
        self.retriever = DeepRetriever(
            workspace_id=workspace_id,
            kg_service=self.kg_service,
            vector_store=self.vector_store,
            embedder=self.embedder,
            db=db,
            reranker=get_reranker_service(),
        )

    # ------------------------------------------------------------------
    # 文档处理
    # ------------------------------------------------------------------

    async def process_document(self, document_id: int, file_path: str) -> int:
        """
        通过完整的 MYRAG 流水线处理文档。

        返回：
            创建的分块数量
        """
        result = await self.db.execute(
            select(Document).where(Document.id == document_id)
        )
        document = result.scalar_one_or_none()
        if document is None:
            raise ValueError(f"Document {document_id} not found")

        previous_markdown = document.markdown_content
        start_time = time.time()
        new_content_hash = file_hash(file_path)
        new_index_fingerprint = index_fingerprint()

        try:
            # 两个指纹都一样还重新跑？那不是增量更新，那是拿风扇给 CPU 做理疗。
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

            # 阶段 1：解析
            document.status = DocumentStatus.PARSING
            await self.db.commit()

            import asyncio
            parsed = await asyncio.to_thread(
                self.parser.parse,
                file_path=file_path,
                document_id=document_id,
                original_filename=document.original_filename,
            )

            # 将 markdown 与图片信息保存到数据库
            document.markdown_content = parsed.markdown
            document.page_count = parsed.page_count
            document.table_count = parsed.tables_count
            document.parser_version = self.parser.parser_name
            await self.db.commit()

            # 保存新记录前清理旧图片记录（处理重新处理的情况）
            await self.db.execute(
                delete(DocumentImage).where(DocumentImage.document_id == document_id)
            )
            await self.db.commit()

            # 将提取的图片保存到数据库
            for img in parsed.images:
                db_image = DocumentImage(
                    document_id=document_id,
                    image_id=img.image_id,
                    page_no=img.page_no,
                    file_path=img.file_path,
                    caption=img.caption,
                    width=img.width,
                    height=img.height,
                    mime_type=img.mime_type,
                )
                self.db.add(db_image)
            document.image_count = len(parsed.images)
            if parsed.images:
                await self.db.commit()

            # 保存新记录前清理旧表格记录（处理重新处理的情况）
            await self.db.execute(
                delete(DocumentTable).where(DocumentTable.document_id == document_id)
            )
            await self.db.commit()

            # 将提取的表格保存到数据库
            for tbl in parsed.tables:
                db_table = DocumentTable(
                    document_id=document_id,
                    table_id=tbl.table_id,
                    page_no=tbl.page_no,
                    content_markdown=tbl.content_markdown,
                    caption=tbl.caption,
                    num_rows=tbl.num_rows,
                    num_cols=tbl.num_cols,
                )
                self.db.add(db_table)
            if parsed.tables:
                await self.db.commit()

            # 阶段 1.5：入库前去重
            if parsed.chunks:
                parsed.chunks, dedup_stats = deduplicate_chunks(parsed.chunks)
                if dedup_stats["input"] != dedup_stats["output"]:
                    logger.info(
                        f"Dedup for doc {document_id}: "
                        f"{dedup_stats['input']}→{dedup_stats['output']} chunks "
                        f"(noise={dedup_stats['noise_removed']}, "
                        f"exact={dedup_stats['exact_removed']}, "
                        f"near={dedup_stats['near_removed']})"
                    )

            # 阶段 2：索引
            document.status = DocumentStatus.INDEXING
            await self.db.commit()

            chunk_count = 0
            old_ids = set(await asyncio.to_thread(
                self.vector_store.get_ids_by_document_id,
                document_id,
            ))
            if parsed.chunks:
                def _index_sync():
                    # 向量化并存入 ChromaDB
                    chunk_texts = [c.content for c in parsed.chunks]
                    embeddings = self.embedder.embed_texts(chunk_texts)

                    ids = [
                        f"doc_{document_id}_chunk_{i}"
                        for i in range(len(parsed.chunks))
                    ]
                    # 构建 image_id→URL 的元数据查询表
                    _img_url_map = {
                        img.image_id: f"/static/doc-images/kb_{self.workspace_id}/images/{img.image_id}.png"
                        for img in parsed.images
                    }

                    metadatas = []
                    for c in parsed.chunks:
                        meta = {
                            "document_id": document_id,
                            "chunk_index": c.chunk_index,
                            "source": c.source_file,
                            "file_type": document.file_type,
                            "page_no": c.page_no,
                            "heading_path": " > ".join(c.heading_path) if c.heading_path else "",
                            "has_table": c.has_table,
                            "has_code": c.has_code,
                            # 图片感知元数据：以竖线分隔的 ID 与 URL
                            "image_ids": "|".join(c.image_refs) if c.image_refs else "",
                            "table_ids": "|".join(c.table_refs) if c.table_refs else "",
                            "image_urls": "|".join(
                                _img_url_map.get(iid, "") for iid in c.image_refs
                            ) if c.image_refs else "",
                        }
                        if document.custom_metadata:
                            meta.update(document.custom_metadata)
                        metadatas.append(meta)

                    # upsert 先把同 ID 的旧块顶掉，再删掉文档变短后残留的旧尾巴。
                    # 比“先全删再慢慢算向量”靠谱，至少向量化失败时旧索引还活着。
                    self.vector_store.upsert_documents(
                        ids=ids,
                        embeddings=embeddings,
                        documents=chunk_texts,
                        metadatas=metadatas,
                    )
                    stale_ids = old_ids - set(ids)
                    self.vector_store.delete_by_ids(list(stale_ids))
                await asyncio.to_thread(_index_sync)
                chunk_count = len(parsed.chunks)
            else:
                # 新文件是空的，旧块也得收走，不然用户搜到的是“前任文档”。
                self.vector_store.delete_by_ids(list(old_ids))

            # 知识图谱写入（异步，失败不阻塞主流程）
            if self.kg_service:
                try:
                    if parsed.markdown:
                        await self.kg_service.ingest(
                            parsed.markdown,
                            document_id=document_id,
                            previous_content=previous_markdown,
                        )
                    elif previous_markdown:
                        await self.kg_service.delete_document(
                            document_id,
                            previous_content=previous_markdown,
                        )
                except Exception as e:
                    logger.error(
                        f"KG ingest failed for document {document_id}, "
                        f"continuing without KG: {e}"
                    )

            # 阶段 3：已索引
            elapsed_ms = int((time.time() - start_time) * 1000)
            document.status = DocumentStatus.INDEXED
            document.chunk_count = chunk_count
            document.processing_time_ms = elapsed_ms
            document.content_hash = new_content_hash
            document.index_fingerprint = new_index_fingerprint
            document.indexed_at = datetime.utcnow()
            document.error_message = None
            await self.db.commit()

            logger.info(
                f"MYRAG processed document {document_id}: "
                f"{chunk_count} chunks, {len(parsed.images)} images, "
                f"{parsed.tables_count} tables in {elapsed_ms}ms"
            )
            return chunk_count

        except Exception as e:
            logger.error(f"MYRAG failed for document {document_id}: {e}")
            document.status = DocumentStatus.FAILED
            document.error_message = str(e)[:500]
            await self.db.commit()
            raise

    # ------------------------------------------------------------------
    # 查询
    # ------------------------------------------------------------------

    def query(
        self,
        question: str,
        top_k: int = 5,
        document_ids: Optional[list[int]] = None,
        metadata_filter: dict | None = None,
    ) -> RAGQueryResult:
        """
        向后兼容的同步查询（仅向量）。
        返回与旧版 RAGService 相同的 RAGQueryResult。
        """
        query_embedding = self.embedder.embed_query(question)

        # 合并 metadata_filter 与 document_ids
        where = metadata_filter.copy() if metadata_filter else {}
        if document_ids:
            where["document_id"] = {"$in": document_ids}
            
        if not where:
            where = None

        results = self.vector_store.query(
            query_embedding=query_embedding,
            n_results=top_k,
            where=where,
        )

        chunks = []
        for i, doc in enumerate(results.get("documents", [])):
            meta = results["metadatas"][i] if results.get("metadatas") else {}
            chunks.append(RetrievedChunk(
                content=doc,
                metadata=meta,
                score=results["distances"][i] if results.get("distances") else 0.0,
                chunk_id=results["ids"][i] if results.get("ids") else "",
            ))

        chunks.sort(key=lambda x: x.score)

        # 组装带引用的上下文
        context_parts = []
        for i, chunk in enumerate(chunks):
            source = chunk.metadata.get("source", "Unknown")
            page = chunk.metadata.get("page_no", 0)
            heading = chunk.metadata.get("heading_path", "")
            citation = source
            if page:
                citation += f" | p.{page}"
            if heading:
                citation += f" | {heading}"
            context_parts.append(f"[{i + 1}] {citation}\n{chunk.content}")

        context = "\n\n---\n\n".join(context_parts)

        return RAGQueryResult(
            chunks=chunks,
            context=context,
            query=question,
        )

    async def query_deep(
        self,
        question: str,
        top_k: int = 5,
        document_ids: Optional[list[int]] = None,
        mode: str = "hybrid",
        include_images: bool = True,
        metadata_filter: dict | None = None,
    ) -> DeepRetrievalResult:
        """
        包含知识图谱、向量、图片和引用的完整异步混合检索。
        """
        return await self.retriever.query(
            question=question,
            mode=mode,
            top_k=top_k,
            document_ids=document_ids,
            include_images=include_images,
            metadata_filter=metadata_filter,
        )

    # ------------------------------------------------------------------
    # 管理
    # ------------------------------------------------------------------

    async def delete_document(self, document_id: int) -> None:
        """删除文档在向量存储和知识图谱中的数据。"""
        self.vector_store.delete_by_document_id(document_id)

        if self.kg_service:
            doc_result = await self.db.execute(
                select(Document).where(Document.id == document_id)
            )
            document = doc_result.scalar_one_or_none()
            try:
                await self.kg_service.delete_document(
                    document_id,
                    previous_content=document.markdown_content if document else None,
                )
            except Exception as exc:
                # 向量删除不能被图谱服务拖着陪葬，失败状态记日志，后面还能重试。
                logger.warning(f"Failed to delete KG data for document {document_id}: {exc}")

        # 从数据库删除图片记录（级联会处理，但仍清理文件）
        result = await self.db.execute(
            select(DocumentImage).where(DocumentImage.document_id == document_id)
        )
        for img in result.scalars().all():
            from pathlib import Path
            img_path = Path(img.file_path)
            if img_path.exists():
                img_path.unlink()

        logger.info(f"Deleted document {document_id} from MYRAG stores")

    def get_chunk_count(self) -> int:
        """返回知识库向量存储中的分块总数。"""
        return self.vector_store.count()
