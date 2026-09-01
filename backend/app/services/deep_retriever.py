"""
深度检索器
===============

结合知识图谱（LightRAG）+ 向量检索（ChromaDB）
+ 交叉编码器重排序（bge-reranker-v2-m3）的混合检索。

流水线：
  1. 知识图谱查询（并行）→ 实体 / 关系摘要
  2. 向量检索 → 超额召回前 N 个候选（MYRAG_VECTOR_PREFETCH）
  3. 交叉编码器重排序 → 精确过滤到前 K 个（MYRAG_RERANKER_TOP_K）
  4. 与引用及可选图片引用合并
"""
from __future__ import annotations

import asyncio
import logging
from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models.document import Document, DocumentImage, DocumentTable
from app.services.embedder import EmbeddingService
from app.services.vector_store import VectorStore
from app.services.knowledge_graph_service import KnowledgeGraphService
from app.services.reranker import RerankerService, get_reranker_service
from app.services.models.parsed_document import (
    Citation,
    DeepRetrievalResult,
    EnrichedChunk,
    ExtractedImage,
    ExtractedTable,
)

logger = logging.getLogger(__name__)


class DeepRetriever:
    """
    混合检索器：知识图谱遍历 + 向量相似度 + 交叉编码器重排序。
    """

    def __init__(
        self,
        workspace_id: int,
        kg_service: Optional[KnowledgeGraphService],
        vector_store: VectorStore,
        embedder: EmbeddingService,
        db: Optional[AsyncSession] = None,
        reranker: Optional[RerankerService] = None,
    ):
        self.workspace_id = workspace_id
        self.kg_service = kg_service
        self.vector_store = vector_store
        self.embedder = embedder
        self.db = db
        self.reranker = reranker or get_reranker_service()

    async def query(
        self,
        question: str,
        mode: str = "hybrid",
        top_k: int = 5,
        document_ids: Optional[list[int]] = None,
        include_images: bool = True,
        metadata_filter: dict | None = None,
    ) -> DeepRetrievalResult:
        """
        执行带重排序的混合检索。

        流程：
          1. [并行] 知识图谱查询 + 向量超额召回（MYRAG_VECTOR_PREFETCH）
          2. 交叉编码器对向量结果重排序 → 最终 top_k
          3. 可选地从分块所在页面查找相关图片
          4. 为 LLM 组装结构化上下文

        参数：
            question: 自然语言查询
            mode: "hybrid"（默认）、"naive"、"local"、"global"、"vector_only"
            top_k: 最终返回的分块数量（重排序之后）
            document_ids: 可选，按指定文档过滤
            include_images: 是否查找相关图片

        返回：
            包含分块、引用、上下文及可选图片的 DeepRetrievalResult
        """
        # 并行执行知识图谱与向量检索
        kg_task = None
        if self.kg_service and mode != "vector_only":
            kg_task = asyncio.create_task(
                self._kg_query(question, mode)
            )

        # 从向量库超额召回，供重排序使用
        prefetch_k = max(settings.MYRAG_VECTOR_PREFETCH, top_k * 3)
        vector_task = asyncio.create_task(
            asyncio.to_thread(
                self._vector_query, question, prefetch_k, document_ids, metadata_filter
            )
        )

        # 等待结果
        kg_summary = ""
        if kg_task:
            try:
                kg_summary = await kg_task
            except Exception as e:
                logger.warning(f"KG query failed, continuing with vector only: {e}")

        raw_chunks, raw_citations = await vector_task

        # 重排序：用交叉编码器打分提升精度
        chunks, citations = await asyncio.to_thread(
            self._rerank_chunks, question, raw_chunks, raw_citations, top_k
        )

        # 查找相关图片和表格
        image_refs = []
        table_refs = []
        if include_images and self.db and chunks:
            page_nos = {(c.document_id, c.page_no) for c in chunks if c.page_no > 0}
            if page_nos:
                image_refs, table_refs = await asyncio.gather(
                    self._find_related_images(page_nos),
                    self._find_related_tables(page_nos),
                )

        # 组装上下文
        context = self._assemble_context(chunks, citations, kg_summary, image_refs, table_refs)

        return DeepRetrievalResult(
            chunks=chunks,
            citations=citations,
            context=context,
            query=question,
            mode=mode,
            knowledge_graph_summary=kg_summary,
            image_refs=image_refs,
            table_refs=table_refs,
        )

    async def _kg_query(self, question: str, mode: str) -> str:
        """获取与问题相关的原始知识图谱上下文（实体 + 关系）。

        使用事实性的图谱数据而非 LLM 生成的叙述，
        以避免 LightRAG aquery() 产生幻觉。
        """
        if not self.kg_service:
            return ""
        try:
            return await asyncio.wait_for(
                self.kg_service.get_relevant_context(question),
                timeout=settings.MYRAG_KG_QUERY_TIMEOUT,
            )
        except asyncio.TimeoutError:
            logger.warning("KG raw context retrieval timed out")
            return ""
        except Exception as e:
            logger.warning(f"KG raw context failed: {e}")
            return ""

    def _vector_query(
        self,
        question: str,
        top_k: int,
        document_ids: Optional[list[int]],
        metadata_filter: dict | None = None,
    ) -> tuple[list[EnrichedChunk], list[Citation]]:
        """通过 ChromaDB 执行同步向量检索（超额召回阶段）。"""
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
        citations = []

        for i, doc_text in enumerate(results.get("documents", [])):
            meta = results["metadatas"][i] if results.get("metadatas") else {}

            heading_path = []
            heading_str = meta.get("heading_path", "")
            if heading_str:
                heading_path = heading_str.split(" > ") if isinstance(heading_str, str) else []

            image_refs = []
            image_ids_str = meta.get("image_ids", "")
            if image_ids_str and isinstance(image_ids_str, str):
                image_refs = [iid for iid in image_ids_str.split("|") if iid]

            table_refs = []
            table_ids_str = meta.get("table_ids", "")
            if table_ids_str and isinstance(table_ids_str, str):
                table_refs = [tid for tid in table_ids_str.split("|") if tid]

            chunk = EnrichedChunk(
                content=doc_text,
                chunk_index=meta.get("chunk_index", i),
                source_file=meta.get("source", ""),
                document_id=meta.get("document_id", 0),
                page_no=meta.get("page_no", 0),
                heading_path=heading_path,
                image_refs=image_refs,
                table_refs=table_refs,
                has_table=meta.get("has_table", False),
                has_code=meta.get("has_code", False),
            )
            chunks.append(chunk)

            citations.append(Citation(
                source_file=meta.get("source", "Unknown"),
                document_id=meta.get("document_id", 0),
                page_no=meta.get("page_no", 0),
                heading_path=heading_path,
            ))

        return chunks, citations

    def _rerank_chunks(
        self,
        question: str,
        chunks: list[EnrichedChunk],
        citations: list[Citation],
        top_k: int,
    ) -> tuple[list[EnrichedChunk], list[Citation]]:
        """
        交叉编码器重排序：对每个（查询，分块）对联合打分，
        再按相关性阈值过滤并返回 top_k。
        """
        if not chunks:
            return [], []

        # 提取用于重排序的文本
        doc_texts = [c.content for c in chunks]

        reranked = self.reranker.rerank(
            query=question,
            documents=doc_texts,
            top_k=top_k,
            min_score=settings.MYRAG_MIN_RELEVANCE_SCORE,
        )

        if not reranked:
            # 兜底：如果重排序器把所有分块都过滤掉，按原顺序保留前 3 个
            logger.warning(
                f"Reranker filtered all {len(chunks)} chunks below threshold "
                f"{settings.MYRAG_MIN_RELEVANCE_SCORE}, falling back to top 3"
            )
            return chunks[:min(3, len(chunks))], citations[:min(3, len(citations))]

        # 将重排序结果映射回原始分块 / 引用
        reranked_chunks = [chunks[r.index] for r in reranked]
        reranked_citations = [citations[r.index] for r in reranked]

        logger.info(
            f"Reranked {len(chunks)} → {len(reranked)} chunks "
            f"(scores: {reranked[0].score:.3f} → {reranked[-1].score:.3f})"
        )

        return reranked_chunks, reranked_citations

    async def _find_related_images(
        self,
        page_refs: set[tuple[int, int]],  # (文档 ID, 页码)
    ) -> list[ExtractedImage]:
        """查找与检索分块同页的图片。"""
        if not self.db:
            return []

        images = []
        for doc_id, page_no in page_refs:
            result = await self.db.execute(
                select(DocumentImage).where(
                    DocumentImage.document_id == doc_id,
                    DocumentImage.page_no == page_no,
                )
            )
            for img in result.scalars().all():
                images.append(ExtractedImage(
                    image_id=img.image_id,
                    document_id=img.document_id,
                    page_no=img.page_no,
                    file_path=img.file_path,
                    caption=img.caption,
                    width=img.width,
                    height=img.height,
                    mime_type=img.mime_type,
                ))

        # 按 image_id 去重
        seen = set()
        unique = []
        for img in images:
            if img.image_id not in seen:
                seen.add(img.image_id)
                unique.append(img)

        return unique

    async def _find_related_tables(
        self,
        page_refs: set[tuple[int, int]],
    ) -> list[ExtractedTable]:
        """查找与检索分块同页的表格。"""
        if not self.db:
            return []

        tables = []
        for doc_id, page_no in page_refs:
            result = await self.db.execute(
                select(DocumentTable).where(
                    DocumentTable.document_id == doc_id,
                    DocumentTable.page_no == page_no,
                )
            )
            for tbl in result.scalars().all():
                tables.append(ExtractedTable(
                    table_id=tbl.table_id,
                    document_id=tbl.document_id,
                    page_no=tbl.page_no,
                    content_markdown=tbl.content_markdown,
                    caption=tbl.caption,
                    num_rows=tbl.num_rows,
                    num_cols=tbl.num_cols,
                ))

        # 按 table_id 去重
        seen = set()
        unique = []
        for tbl in tables:
            if tbl.table_id not in seen:
                seen.add(tbl.table_id)
                unique.append(tbl)

        return unique

    @staticmethod
    def _assemble_context(
        chunks: list[EnrichedChunk],
        citations: list[Citation],
        kg_summary: str,
        image_refs: list[ExtractedImage],
        table_refs: list[ExtractedTable] | None = None,
    ) -> str:
        """为 LLM 组装结构化上下文字符串。"""
        parts = []

        # 知识图谱洞见
        if kg_summary:
            parts.append("## Knowledge Graph Insights")
            parts.append(kg_summary)
            parts.append("")

        # 带引用的检索分块
        if chunks:
            parts.append("## Retrieved Document Sections")
            for i, (chunk, citation) in enumerate(zip(chunks, citations)):
                parts.append(f"### [{i + 1}] {citation.format()}")
                parts.append(chunk.content)
                parts.append("")

        # 可用图片
        if image_refs:
            parts.append("## Available Document Images")
            for img in image_refs:
                caption_str = f': "{img.caption}"' if img.caption else ""
                parts.append(
                    f"- Image p.{img.page_no}{caption_str} (id: {img.image_id})"
                )
            parts.append("")

        # 可用表格
        if table_refs:
            parts.append("## Available Document Tables")
            for tbl in table_refs:
                caption_str = f': "{tbl.caption}"' if tbl.caption else ""
                parts.append(
                    f"- Table p.{tbl.page_no} ({tbl.num_rows}x{tbl.num_cols}){caption_str}"
                )
            parts.append("")

        if not parts:
            return "No relevant documents found for this query."

        return "\n".join(parts)
