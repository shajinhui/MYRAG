"""
用于文档查询与检索的 RAG API 端点。
"""
from fastapi import APIRouter, Depends, HTTPException, status, BackgroundTasks
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func

from app.core.deps import get_db
from app.core.exceptions import NotFoundError
from app.models.knowledge_base import KnowledgeBase
from app.models.document import Document, DocumentImage, DocumentStatus
import logging

from app.schemas.rag import (
    RAGQueryRequest,
    RAGQueryResponse,
    RetrievedChunkResponse,
    CitationResponse,
    DocumentImageResponse,
    DocumentProcessRequest,
    DocumentProcessResponse,
    BatchProcessRequest,
    ProjectRAGStatsResponse,
    KGEntityResponse,
    KGRelationshipResponse,
    KGGraphResponse,
    KGGraphNodeResponse,
    KGGraphEdgeResponse,
    KGAnalyticsResponse,
    DocumentBreakdownItem,
    ProjectAnalyticsResponse,
    ChatRequest,
    ChatResponse,
    ChatSourceChunk,
    ChatImageRef,
    PersistedChatMessage,
    ChatHistoryResponse,
    LLMCapabilitiesResponse,
    DebugRetrievedSource,
    DebugChatResponse,
    RateSourceRequest,
)

logger = logging.getLogger(__name__)
import string, random
from app.services.rag_service import get_rag_service

# ---------------------------------------------------------------------------
# 引用 ID 生成 —— 与 PageIndex 格式一致的 4 位字母数字 ID
# ---------------------------------------------------------------------------
_CITATION_ID_CHARS = string.ascii_lowercase + string.digits


def _generate_citation_id(existing: set[str]) -> str:
    """生成唯一的 4 位字母数字引用 ID。

    始终包含至少一个字母，避免与旧版数字索引（例如 "1"、"23"）混淆。
    """
    while True:
        cid = "".join(random.choices(_CITATION_ID_CHARS, k=4))
        if any(c.isalpha() for c in cid) and cid not in existing:
            return cid

router = APIRouter(prefix="/rag", tags=["rag"])

UPLOAD_DIR = "uploads"

# 提示词常量 —— 完整文档见 chat_prompt.py
from app.api.chat_prompt import DEFAULT_SYSTEM_PROMPT, HARD_SYSTEM_PROMPT


async def verify_workspace_access(
    workspace_id: int,
    db: AsyncSession,
) -> KnowledgeBase:
    """确认知识库存在。"""
    result = await db.execute(select(KnowledgeBase).where(KnowledgeBase.id == workspace_id))
    kb = result.scalar_one_or_none()

    if kb is None:
        raise NotFoundError("KnowledgeBase", workspace_id)

    return kb


@router.post("/query/{workspace_id}", response_model=RAGQueryResponse)
async def query_documents(
    workspace_id: int,
    request: RAGQueryRequest,
    db: AsyncSession = Depends(get_db),
):
    """使用语义搜索（+ 可选知识图谱）查询已索引文档。"""
    await verify_workspace_access(workspace_id, db)

    rag_service = get_rag_service(db, workspace_id)

    # 可用时优先尝试深度查询
    from app.services.my_rag_service import MYRAGService
    if isinstance(rag_service, MYRAGService) and request.mode != "vector_only":
        result = await rag_service.query_deep(
            question=request.question,
            top_k=request.top_k,
            document_ids=request.document_ids,
            mode=request.mode,
            metadata_filter=request.metadata_filter,
        )

        chunks_response = []
        for i, chunk in enumerate(result.chunks):
            citation = result.citations[i] if i < len(result.citations) else None
            citation_resp = None
            if citation:
                citation_resp = CitationResponse(
                    source_file=citation.source_file,
                    document_id=citation.document_id,
                    page_no=citation.page_no,
                    heading_path=citation.heading_path,
                    formatted=citation.format(),
                )
            chunks_response.append(RetrievedChunkResponse(
                content=chunk.content,
                chunk_id=f"doc_{chunk.document_id}_chunk_{chunk.chunk_index}",
                score=0.0,
                metadata={
                    "source": chunk.source_file,
                    "page_no": chunk.page_no,
                    "heading_path": " > ".join(chunk.heading_path),
                },
                citation=citation_resp,
            ))

        image_refs = [
            DocumentImageResponse(
                image_id=img.image_id,
                document_id=img.document_id,
                page_no=img.page_no,
                caption=img.caption,
                width=img.width,
                height=img.height,
                url=f"/static/doc-images/kb_{workspace_id}/images/{img.image_id}.png",
            )
            for img in result.image_refs
        ]

        citations = [
            CitationResponse(
                source_file=c.source_file,
                document_id=c.document_id,
                page_no=c.page_no,
                heading_path=c.heading_path,
                formatted=c.format(),
            )
            for c in result.citations
        ]

        return RAGQueryResponse(
            query=result.query,
            chunks=chunks_response,
            context=result.context,
            total_chunks=len(result.chunks),
            knowledge_graph_summary=result.knowledge_graph_summary,
            citations=citations,
            image_refs=image_refs,
        )

    # 兜底：旧版同步查询
    result = rag_service.query(
        question=request.question,
        top_k=request.top_k,
        document_ids=request.document_ids
    )

    return RAGQueryResponse(
        query=result.query,
        chunks=[
            RetrievedChunkResponse(
                content=chunk.content,
                chunk_id=chunk.chunk_id,
                score=chunk.score,
                metadata=chunk.metadata
            )
            for chunk in result.chunks
        ],
        context=result.context,
        total_chunks=len(result.chunks)
    )


@router.post("/process/{document_id}", response_model=DocumentProcessResponse)
async def process_document(
    document_id: int,
    db: AsyncSession = Depends(get_db),
):
    """以后台任务形式触发文档处理（解析 + 索引）。"""
    result = await db.execute(select(Document).where(Document.id == document_id))
    document = result.scalar_one_or_none()

    if document is None:
        raise NotFoundError("Document", document_id)

    if document.status in (DocumentStatus.PROCESSING, DocumentStatus.PARSING, DocumentStatus.INDEXING):
        # 检查是否超时（超过处理超时时间）——自动恢复
        from datetime import datetime, timedelta
        from app.core.config import settings
        timeout = settings.MYRAG_PROCESSING_TIMEOUT_MINUTES
        cutoff = datetime.utcnow() - timedelta(minutes=timeout)
        if document.updated_at < cutoff:
            # 已超时 —— 重置状态以允许重新处理
            document.status = DocumentStatus.FAILED
            document.error_message = f"Processing timeout ({timeout}min). Retrying..."
            await db.commit()
        else:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Document is already being analyzed"
            )

    if document.status == DocumentStatus.INDEXED:
        return DocumentProcessResponse(
            document_id=document_id,
            status=document.status.value,
            chunk_count=document.chunk_count,
            message="Document is already indexed"
        )

    from pathlib import Path
    file_path = Path(UPLOAD_DIR) / document.filename

    if not file_path.exists():
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Document file not found on disk"
        )

    # 立即标记为处理中，让界面及时更新
    document.status = DocumentStatus.PROCESSING
    document.error_message = None
    await db.commit()

    # 启动后台任务
    from app.api.documents import process_document_background
    import asyncio
    asyncio.get_event_loop().create_task(
        process_document_background(document_id, str(file_path), document.workspace_id)
    )

    return DocumentProcessResponse(
        document_id=document_id,
        status="processing",
        chunk_count=0,
        message="Processing started. Document will be parsed and indexed in the background."
    )


@router.post("/process-batch")
async def process_batch(
    request: BatchProcessRequest,
    db: AsyncSession = Depends(get_db),
):
    """
    在后台按顺序处理多个文档。
    先将全部文档标记为 PROCESSING，再逐个处理，以避免资源竞争
    （每个文档都会使用 Docling、向量化和知识图谱写入）。
    """
    from pathlib import Path as _P

    accepted_ids = []
    skipped_ids = []

    for doc_id in request.document_ids:
        result = await db.execute(select(Document).where(Document.id == doc_id))
        doc = result.scalar_one_or_none()
        if doc is None:
            skipped_ids.append(doc_id)
            continue

        # 跳过正在处理或已索引的文档
        if doc.status in (
            DocumentStatus.PROCESSING, DocumentStatus.PARSING, DocumentStatus.INDEXING,
        ):
            skipped_ids.append(doc_id)
            continue

        file_path = _P(UPLOAD_DIR) / doc.filename
        if not file_path.exists():
            skipped_ids.append(doc_id)
            continue

        # 立即标记为处理中，让界面及时更新
        doc.status = DocumentStatus.PROCESSING
        doc.error_message = None
        accepted_ids.append((doc_id, str(file_path), doc.workspace_id))

    await db.commit()

    if accepted_ids:
        import asyncio
        asyncio.get_event_loop().create_task(
            _process_batch_background(accepted_ids)
        )

    return {
        "message": f"Processing {len(accepted_ids)} document(s)",
        "accepted": [aid[0] for aid in accepted_ids],
        "skipped": skipped_ids,
    }


async def _process_batch_background(
    items: list[tuple[int, str, int]],
):
    """按顺序处理文档，以避免资源竞争。"""
    from app.api.documents import process_document_background

    for doc_id, file_path, workspace_id in items:
        try:
            await process_document_background(doc_id, file_path, workspace_id)
            logger.info(f"Batch: document {doc_id} processed")
        except Exception as e:
            logger.error(f"Batch: document {doc_id} failed: {e}")


@router.post("/reindex/{document_id}", response_model=DocumentProcessResponse)
async def reindex_document(
    document_id: int,
    db: AsyncSession = Depends(get_db),
):
    """通过 MYRAG 流水线重新处理已有文档。"""
    result = await db.execute(select(Document).where(Document.id == document_id))
    document = result.scalar_one_or_none()

    if document is None:
        raise NotFoundError("Document", document_id)

    if document.status in (DocumentStatus.PROCESSING, DocumentStatus.PARSING, DocumentStatus.INDEXING):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Document is currently being processed"
        )

    from pathlib import Path
    file_path = Path(UPLOAD_DIR) / document.filename

    if not file_path.exists():
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Document file not found on disk"
        )

    rag_service = get_rag_service(db, document.workspace_id)

    # 先删除已有数据
    try:
        await rag_service.delete_document(document_id)
    except Exception as e:
        logging.getLogger(__name__).warning(f"Failed to delete old data for reindex: {e}")

    # 重置文档元数据
    document.status = DocumentStatus.PENDING
    document.chunk_count = 0
    document.markdown_content = None
    document.image_count = 0
    document.table_count = 0
    document.parser_version = None
    # 强制重建就是强制重建，别让指纹判断自作聪明地跳过去。
    document.index_fingerprint = None
    document.error_message = None
    await db.commit()

    try:
        chunk_count = await rag_service.process_document(
            document_id=document_id,
            file_path=str(file_path)
        )
        return DocumentProcessResponse(
            document_id=document_id,
            status=DocumentStatus.INDEXED.value,
            chunk_count=chunk_count,
            message=f"Re-indexed with MYRAG: {chunk_count} chunks created"
        )
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to reindex document: {str(e)}"
        )


@router.post("/reindex-workspace/{workspace_id}")
async def reindex_workspace(
    workspace_id: int,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
):
    """
    重建工作区内所有文档的索引。
    删除旧向量集合（以处理向量维度变化），
    并通过 MYRAG 流水线重新处理每个文档。
    在后台运行——立即返回文档数量。
    """
    await verify_workspace_access(workspace_id, db)

    # 查找该工作区内的全部文档
    result = await db.execute(
        select(Document).where(
            Document.workspace_id == workspace_id,
            Document.status.notin_([
                DocumentStatus.PROCESSING,
                DocumentStatus.PARSING,
                DocumentStatus.INDEXING,
            ]),
        )
    )
    documents = list(result.scalars().all())

    if not documents:
        return {"message": "No documents to reindex", "document_count": 0}

    # 删除旧向量集合（向量维度变化时需要）
    try:
        from app.services.vector_store import get_vector_store
        vs = get_vector_store(workspace_id)
        vs.delete_collection()
        logger.info(f"Deleted old vector collection for workspace {workspace_id}")
    except Exception as e:
        logger.warning(f"Failed to delete old collection: {e}")

    async def _reindex_all(doc_ids: list[int], ws_id: int):
        """后台任务：逐个重建文档索引。"""
        from app.core.database import AsyncSessionLocal
        async with AsyncSessionLocal() as session:
            rag_service = get_rag_service(session, ws_id)
            for did in doc_ids:
                try:
                    res = await session.execute(
                        select(Document).where(Document.id == did)
                    )
                    doc = res.scalar_one_or_none()
                    if not doc:
                        continue

                    from pathlib import Path
                    file_path = Path(UPLOAD_DIR) / doc.filename
                    if not file_path.exists():
                        logger.warning(f"Skipping doc {did}: file not found")
                        continue

                    # 删除该文档的旧分块数据
                    try:
                        await rag_service.delete_document(did)
                    except Exception:
                        pass

                    # 重置元数据
                    doc.status = DocumentStatus.PENDING
                    doc.chunk_count = 0
                    doc.image_count = 0
                    doc.error_message = None
                    await session.commit()

                    # 重新处理
                    await rag_service.process_document(
                        document_id=did, file_path=str(file_path)
                    )
                    logger.info(f"Reindexed document {did} in workspace {ws_id}")
                except Exception as e:
                    logger.error(f"Failed to reindex document {did}: {e}")

    doc_ids = [d.id for d in documents]
    background_tasks.add_task(_reindex_all, doc_ids, workspace_id)

    return {
        "message": f"Reindexing {len(doc_ids)} documents in background",
        "document_count": len(doc_ids),
        "document_ids": doc_ids,
    }


@router.get("/stats/{workspace_id}", response_model=ProjectRAGStatsResponse)
async def get_workspace_rag_stats(
    workspace_id: int,
    db: AsyncSession = Depends(get_db),
):
    """获取知识库的 RAG 统计信息。"""
    await verify_workspace_access(workspace_id, db)

    total_result = await db.execute(
        select(func.count(Document.id)).where(Document.workspace_id == workspace_id)
    )
    total_documents = total_result.scalar() or 0

    indexed_result = await db.execute(
        select(func.count(Document.id)).where(
            Document.workspace_id == workspace_id,
            Document.status == DocumentStatus.INDEXED
        )
    )
    indexed_documents = indexed_result.scalar() or 0

    # 统计 MYRAG 文档数量（parser_version = 'docling'）
    myrag_result = await db.execute(
        select(func.count(Document.id)).where(
            Document.workspace_id == workspace_id,
            Document.parser_version == "docling"
        )
    )
    myrag_documents = myrag_result.scalar() or 0

    # 统计图片总数
    image_result = await db.execute(
        select(func.count(DocumentImage.id))
        .join(Document, DocumentImage.document_id == Document.id)
        .where(Document.workspace_id == workspace_id)
    )
    image_count = image_result.scalar() or 0

    rag_service = get_rag_service(db, workspace_id)
    try:
        total_chunks = rag_service.get_chunk_count()
    except Exception:
        total_chunks = 0

    return ProjectRAGStatsResponse(
        workspace_id=workspace_id,
        total_documents=total_documents,
        indexed_documents=indexed_documents,
        total_chunks=total_chunks,
        image_count=image_count,
        myrag_documents=myrag_documents,
    )


@router.get("/chunks/{document_id}")
async def get_document_chunks(
    document_id: int,
    db: AsyncSession = Depends(get_db),
):
    """获取指定文档的全部切块。"""
    result = await db.execute(select(Document).where(Document.id == document_id))
    document = result.scalar_one_or_none()

    if document is None:
        raise NotFoundError("Document", document_id)

    if document.status != DocumentStatus.INDEXED:
        return {
            "document_id": document_id,
            "status": document.status.value,
            "chunks": [],
            "message": "Document is not yet indexed"
        }

    rag_service = get_rag_service(db, document.workspace_id)

    chunk_ids = [f"doc_{document_id}_chunk_{i}" for i in range(document.chunk_count)]

    try:
        results = rag_service.vector_store.get_by_ids(chunk_ids)

        chunks = []
        for i in range(len(results.get("ids", []))):
            chunks.append({
                "chunk_id": results["ids"][i],
                "content": results["documents"][i] if results.get("documents") else None,
                "metadata": results["metadatas"][i] if results.get("metadatas") else {}
            })

        return {
            "document_id": document_id,
            "status": document.status.value,
            "chunk_count": document.chunk_count,
            "chunks": chunks
        }
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to retrieve chunks: {str(e)}"
        )


# ---------------------------------------------------------------------------
# 知识图谱探索端点（第 9 阶段）
# ---------------------------------------------------------------------------

async def _get_kg_service(workspace_id: int):
    """为知识库获取 KnowledgeGraphService（当 MYRAG 激活时）。"""
    from app.services.knowledge_graph_service import KnowledgeGraphService
    return KnowledgeGraphService(workspace_id)


@router.get("/entities/{workspace_id}", response_model=list[KGEntityResponse])
async def get_kg_entities(
    workspace_id: int,
    search: str | None = None,
    entity_type: str | None = None,
    limit: int = 200,
    offset: int = 0,
    db: AsyncSession = Depends(get_db),
):
    """列出工作区知识图谱中的实体。"""
    await verify_workspace_access(workspace_id, db)
    kg = await _get_kg_service(workspace_id)
    try:
        entities = await kg.get_entities(
            search=search, entity_type=entity_type, limit=limit, offset=offset
        )
        return [KGEntityResponse(**e) for e in entities]
    except Exception as e:
        logger.error(f"Failed to get KG entities for workspace {workspace_id}: {e}")
        return []


@router.get("/relationships/{workspace_id}", response_model=list[KGRelationshipResponse])
async def get_kg_relationships(
    workspace_id: int,
    entity: str | None = None,
    limit: int = 500,
    db: AsyncSession = Depends(get_db),
):
    """列出工作区知识图谱中的关系。"""
    await verify_workspace_access(workspace_id, db)
    kg = await _get_kg_service(workspace_id)
    try:
        rels = await kg.get_relationships(entity_name=entity, limit=limit)
        return [KGRelationshipResponse(**r) for r in rels]
    except Exception as e:
        logger.error(f"Failed to get KG relationships for workspace {workspace_id}: {e}")
        return []


@router.get("/graph/{workspace_id}", response_model=KGGraphResponse)
async def get_kg_graph(
    workspace_id: int,
    center: str | None = None,
    max_depth: int = 3,
    max_nodes: int = 150,
    db: AsyncSession = Depends(get_db),
):
    """导出供前端可视化的知识图谱数据。"""
    await verify_workspace_access(workspace_id, db)
    kg = await _get_kg_service(workspace_id)
    try:
        data = await kg.get_graph_data(
            center_entity=center, max_depth=max_depth, max_nodes=max_nodes
        )
        return KGGraphResponse(
            nodes=[KGGraphNodeResponse(**n) for n in data["nodes"]],
            edges=[KGGraphEdgeResponse(**e) for e in data["edges"]],
            is_truncated=data.get("is_truncated", False),
        )
    except Exception as e:
        logger.error(f"Failed to export KG graph for workspace {workspace_id}: {e}")
        return KGGraphResponse()


@router.get("/analytics/{workspace_id}", response_model=ProjectAnalyticsResponse)
async def get_workspace_analytics(
    workspace_id: int,
    db: AsyncSession = Depends(get_db),
):
    """获取知识库的扩展分析（统计 + 知识图谱 + 按文档拆解）。"""
    await verify_workspace_access(workspace_id, db)

    # 基础统计
    total_result = await db.execute(
        select(func.count(Document.id)).where(Document.workspace_id == workspace_id)
    )
    total_documents = total_result.scalar() or 0

    indexed_result = await db.execute(
        select(func.count(Document.id)).where(
            Document.workspace_id == workspace_id,
            Document.status == DocumentStatus.INDEXED,
        )
    )
    indexed_documents = indexed_result.scalar() or 0

    myrag_result = await db.execute(
        select(func.count(Document.id)).where(
            Document.workspace_id == workspace_id,
            Document.parser_version == "docling",
        )
    )
    myrag_documents = myrag_result.scalar() or 0

    image_result = await db.execute(
        select(func.count(DocumentImage.id))
        .join(Document, DocumentImage.document_id == Document.id)
        .where(Document.workspace_id == workspace_id)
    )
    image_count = image_result.scalar() or 0

    rag_service = get_rag_service(db, workspace_id)
    try:
        total_chunks = rag_service.get_chunk_count()
    except Exception:
        total_chunks = 0

    stats = ProjectRAGStatsResponse(
        workspace_id=workspace_id,
        total_documents=total_documents,
        indexed_documents=indexed_documents,
        total_chunks=total_chunks,
        image_count=image_count,
        myrag_documents=myrag_documents,
    )

    # 知识图谱分析（可选 —— 仅在 MYRAG 激活时）
    kg_analytics = None
    if myrag_documents > 0:
        try:
            kg = await _get_kg_service(workspace_id)
            analytics_data = await kg.get_analytics()
            kg_analytics = KGAnalyticsResponse(
                entity_count=analytics_data["entity_count"],
                relationship_count=analytics_data["relationship_count"],
                entity_types=analytics_data["entity_types"],
                top_entities=[KGEntityResponse(**e) for e in analytics_data["top_entities"]],
                avg_degree=analytics_data["avg_degree"],
            )
        except Exception as e:
            logger.warning(f"Failed to get KG analytics for workspace {workspace_id}: {e}")

    # 按文档拆解
    doc_result = await db.execute(
        select(Document)
        .where(Document.workspace_id == workspace_id)
        .order_by(Document.created_at.desc())
    )
    documents = doc_result.scalars().all()
    breakdown = [
        DocumentBreakdownItem(
            document_id=d.id,
            filename=d.original_filename,
            chunk_count=d.chunk_count,
            image_count=d.image_count or 0,
            page_count=d.page_count or 0,
            file_size=d.file_size,
            status=d.status.value if hasattr(d.status, "value") else str(d.status),
        )
        for d in documents
    ]

    return ProjectAnalyticsResponse(
        stats=stats,
        kg_analytics=kg_analytics,
        document_breakdown=breakdown,
    )


# ---------------------------------------------------------------------------
# 聊天历史持久化
# ---------------------------------------------------------------------------

@router.get("/chat/{workspace_id}/history", response_model=ChatHistoryResponse)
async def get_chat_history(
    workspace_id: int,
    db: AsyncSession = Depends(get_db),
):
    """加载工作区已持久化的聊天历史。"""
    await verify_workspace_access(workspace_id, db)

    from app.models.chat_message import ChatMessage as ChatMessageModel
    result = await db.execute(
        select(ChatMessageModel)
        .where(ChatMessageModel.workspace_id == workspace_id)
        .order_by(ChatMessageModel.created_at.asc())
    )
    messages = result.scalars().all()

    return ChatHistoryResponse(
        workspace_id=workspace_id,
        messages=[
            PersistedChatMessage(
                id=m.id,
                message_id=m.message_id,
                role=m.role,
                content=m.content,
                sources=m.sources,
                related_entities=m.related_entities,
                image_refs=m.image_refs,
                thinking=m.thinking,
                agent_steps=m.agent_steps,
                created_at=m.created_at.isoformat() if m.created_at else "",
            )
            for m in messages
        ],
        total=len(messages),
    )


@router.delete("/chat/{workspace_id}/history")
async def delete_chat_history(
    workspace_id: int,
    db: AsyncSession = Depends(get_db),
):
    """清空工作区的全部聊天历史。"""
    await verify_workspace_access(workspace_id, db)

    from app.models.chat_message import ChatMessage as ChatMessageModel
    from sqlalchemy import delete
    await db.execute(
        delete(ChatMessageModel).where(ChatMessageModel.workspace_id == workspace_id)
    )
    await db.commit()
    return {"status": "cleared", "workspace_id": workspace_id}


# ---------------------------------------------------------------------------
# 来源评分端点
# ---------------------------------------------------------------------------

@router.post("/chat/{workspace_id}/rate")
async def rate_source(
    workspace_id: int,
    body: RateSourceRequest,
    db: AsyncSession = Depends(get_db),
):
    """对聊天消息中的来源引用进行评分。"""
    await verify_workspace_access(workspace_id, db)

    from app.models.chat_message import ChatMessage as ChatMessageModel

    result = await db.execute(
        select(ChatMessageModel).where(
            ChatMessageModel.workspace_id == workspace_id,
            ChatMessageModel.message_id == body.message_id,
        )
    )
    row = result.scalar_one_or_none()
    if not row:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Message not found",
        )

    current_ratings = row.ratings or {}
    current_ratings[body.source_index] = body.rating
    row.ratings = current_ratings
    from sqlalchemy.orm.attributes import flag_modified
    flag_modified(row, "ratings")
    await db.commit()

    return {"success": True, "message_id": body.message_id, "ratings": current_ratings}


# ---------------------------------------------------------------------------
# 聊天端点 —— 通过 MYRAG 实现基于 LLM 的文档问答
# ---------------------------------------------------------------------------
# SSE 流式聊天端点
# ---------------------------------------------------------------------------

@router.post("/chat/{workspace_id}/stream")
async def chat_stream(
    workspace_id: int,
    request: ChatRequest,
    db: AsyncSession = Depends(get_db),
):
    """带半智能体检索的 SSE 流式聊天。"""
    from app.api.chat_agent import chat_stream_endpoint
    return await chat_stream_endpoint(workspace_id, request, db)


# ---------------------------------------------------------------------------

@router.post("/chat/{workspace_id}", response_model=ChatResponse)
async def chat_with_documents(
    workspace_id: int,
    request: ChatRequest,
    db: AsyncSession = Depends(get_db),
):
    """使用 MYRAG 检索 + LLM 回答生成与文档聊天。"""
    kb = await verify_workspace_access(workspace_id, db)

    rag_service = get_rag_service(db, workspace_id)

    # -- 1. 通过 MYRAG 检索相关分块 --
    chunks = []
    citations = []
    kg_summary = ""

    from app.services.my_rag_service import MYRAGService
    if isinstance(rag_service, MYRAGService):
        result = await rag_service.query_deep(
            question=request.message,
            top_k=8,
            document_ids=request.document_ids,
            mode="hybrid",
            include_images=False,  # 不再需要单独的图片查找
        )
        chunks = result.chunks
        citations = result.citations
        kg_summary = result.knowledge_graph_summary
    else:
        # 兜底：旧版纯向量检索
        legacy = rag_service.query(
            question=request.message,
            top_k=5,
            document_ids=request.document_ids,
        )
        for i, c in enumerate(legacy.chunks):
            from types import SimpleNamespace
            chunks.append(SimpleNamespace(
                content=c.content,
                document_id=int(c.metadata.get("document_id", 0)),
                chunk_index=i,
                page_no=int(c.metadata.get("page_no", 0)),
                heading_path=str(c.metadata.get("heading_path", "")).split(" > ") if c.metadata.get("heading_path") else [],
                source_file=str(c.metadata.get("source", "")),
                image_refs=[],
            ))

    # -- 2. 构建来源列表 --
    # 来源标签使用 "Source [XXXX]" 格式（4 位字母数字 ID）。
    # 不要在括号内加入其他文本——LLM 会照搬该格式。
    used_ids: set[str] = set()
    sources = []
    context_parts = []
    for i, chunk in enumerate(chunks):
        citation = citations[i] if i < len(citations) else None
        cid = _generate_citation_id(used_ids)
        used_ids.add(cid)
        sources.append(ChatSourceChunk(
            index=cid,
            chunk_id=f"doc_{chunk.document_id}_chunk_{chunk.chunk_index}",
            content=chunk.content,
            document_id=chunk.document_id,
            page_no=chunk.page_no,
            heading_path=chunk.heading_path,
            score=0.0,
            source_type="vector",
        ))
        # 构建元数据行（文件名、页码、标题）——放在括号外
        meta_parts = []
        if citation:
            meta_parts.append(citation.source_file)
            if citation.page_no:
                meta_parts.append(f"page {citation.page_no}")
        heading = " > ".join(chunk.heading_path) if chunk.heading_path else ""
        if heading:
            meta_parts.append(heading)
        meta_line = f" ({', '.join(meta_parts)})" if meta_parts else ""

        context_parts.append(f"Source [{cid}]{meta_line}:\n{chunk.content}")

    # 注意：知识图谱摘要不会作为可引用来源加入。
    # LightRAG 的 query() 可能生成文档中不存在的虚假数据。
    # 如果把它作为可引用的 [N] 来源，LLM 会忠实地引用这些虚构数据。
    # 因此知识图谱摘要只作为背景上下文使用（不带来源编号）。
    context = "\n\n---\n\n".join(context_parts)

    # -- 2b. 构建图片引用（分块元数据 → 兜底：按页面查找） --
    from pathlib import Path as _P
    from app.core.config import settings

    # 策略 1：从分块元数据收集 image_id（图片感知分块）
    seen_image_ids: set[str] = set()
    chunk_image_ids: list[str] = []
    for c in chunks:
        for iid in getattr(c, "image_refs", []) or []:
            if iid and iid not in seen_image_ids:
                seen_image_ids.add(iid)
                chunk_image_ids.append(iid)

    # 根据这些 ID 查询 DocumentImage 记录
    resolved_images: list[DocumentImage] = []
    if chunk_image_ids:
        img_result = await db.execute(
            select(DocumentImage).where(DocumentImage.image_id.in_(chunk_image_ids))
        )
        resolved_images = list(img_result.scalars().all())

    # 策略 2（兜底）：如果分块元数据没有图片，
    # 则根据检索分块的页码进行基于页面的查找。
    if not resolved_images:
        source_pages = {
            (getattr(c, "document_id", 0), getattr(c, "page_no", 0))
            for c in chunks
            if getattr(c, "page_no", 0) > 0
        }
        if source_pages:
            from sqlalchemy import or_, and_
            page_filters = [
                and_(
                    DocumentImage.document_id == doc_id,
                    DocumentImage.page_no == page_no,
                )
                for doc_id, page_no in source_pages
            ]
            img_result = await db.execute(
                select(DocumentImage).where(or_(*page_filters))
            )
            resolved_images = list(img_result.scalars().all())
            # 去重
            seen = set()
            deduped = []
            for img in resolved_images:
                if img.image_id not in seen:
                    seen.add(img.image_id)
                    deduped.append(img)
            resolved_images = deduped

    chat_image_refs: list[ChatImageRef] = []
    image_context_parts: list[str] = []
    image_parts = []  # 供多模态使用的 genai.types.Part

    MAX_VISION_IMAGES = 3  # 限制图片数量以控制 token 成本
    for idx, img in enumerate(resolved_images[:MAX_VISION_IMAGES]):
        img_ref_id = _generate_citation_id(used_ids)
        used_ids.add(img_ref_id)
        img_url = f"/static/doc-images/kb_{workspace_id}/images/{img.image_id}.png"
        chat_image_refs.append(ChatImageRef(
            ref_id=img_ref_id,
            image_id=img.image_id,
            document_id=img.document_id,
            page_no=img.page_no,
            caption=img.caption or "",
            url=img_url,
            width=img.width,
            height=img.height,
        ))
        # 用于文本上下文的图片说明 —— [IMG-XXXX] 格式
        cap = f'"{img.caption}"' if img.caption else "no caption"
        image_context_parts.append(
            f"- [IMG-{img_ref_id}] Page {img.page_no}: {cap}"
        )
        # 读取实际图片文件，供 Gemini 视觉使用
        img_path = _P(img.file_path)
        if img_path.exists():
            try:
                img_bytes = img_path.read_bytes()
                mime = img.mime_type or "image/png"
                image_parts.append({
                    "inline_data": {"mime_type": mime, "data": img_bytes},
                    "page_no": img.page_no,
                    "caption": img.caption or "",
                    "img_ref_id": img_ref_id,
                })
            except Exception as e:
                logger.warning(f"Failed to read image {img.image_id}: {e}")

    # -- 3. 使用上下文和图片调用 LLM --
    from app.services.llm import get_llm_provider
    from app.services.llm.types import LLMImagePart, LLMMessage, LLMResult

    provider = get_llm_provider()

    # ── 面向本地模型（gemma3 等）的提示词架构 ──────────
    # 关键洞察：上下文较长时，本地模型会忽略系统提示词。
    # 解决方案：简短系统提示词 + 把来源和规则放进用户消息。
    # 模型对用户消息的关注度最高。

    system_prompt = (kb.system_prompt or DEFAULT_SYSTEM_PROMPT) + HARD_SYSTEM_PROMPT

    # ── 构建用户消息：来源 + 规则 + 问题 ──────────────
    # 结构：上下文 → 规则 → 问题（模型先读取上下文）

    user_parts: list[str] = []

    # 1. 文档来源（模型首先读取这部分）
    user_parts.append("I have retrieved the following document sources for you.\n")
    user_parts.append("=== DOCUMENT SOURCES ===")
    user_parts.append(context)
    user_parts.append("=== END SOURCES ===\n")

    # 2. 图片引用（如果有）
    if image_context_parts:
        user_parts.append("Document Images:")
        user_parts.extend(image_context_parts)
        user_parts.append("")

    # 3. 上下文规则（仅补充系统提示词未覆盖的内容）
    user_parts.append(
        "IMPORTANT:\n"
        "- Read EVERY source above carefully. Answers often require "
        "combining data from MULTIPLE sources.\n"
        "- TABLE DATA: Sources may contain table data as 'Key, Year = Value' pairs. "
        "Example: 'ROE, 2023 = 12,8%' means ROE was 12.8% in 2023. "
        "Extract and report these values.\n"
        "- If no source contains relevant information, say: "
        "\"Tài liệu không chứa thông tin này.\"\n"
    )

    # 4. 对话上下文回顾（如果存在历史）
    if request.history:
        last_exchange = request.history[-2:]  # 最后一轮问答
        recap_parts = []
        for msg in last_exchange:
            prefix = "User" if msg.role == "user" else "Assistant"
            recap_parts.append(f"{prefix}: {msg.content[:300]}")
        user_parts.append(
            "CONVERSATION CONTEXT (previous exchange):\n"
            + "\n".join(recap_parts) + "\n"
        )

    # 5. 实际问题（放在最后 = 最高关注位置）
    user_parts.append(f"My question: {request.message}")

    user_content = "\n".join(user_parts)

    messages: list[LLMMessage] = []
    for msg in request.history[-10:]:  # 保留最近 10 条消息作为上下文
        role = "user" if msg.role == "user" else "assistant"
        messages.append(LLMMessage(role=role, content=msg.content))

    # 将图片附加到用户消息（供多模态模型使用）
    user_images: list[LLMImagePart] = []
    if image_parts:
        for img_data in image_parts:
            user_content += f"\n[IMG-{img_data['img_ref_id']}] (page {img_data['page_no']}):"
            user_images.append(LLMImagePart(
                data=img_data["inline_data"]["data"],
                mime_type=img_data["inline_data"]["mime_type"],
            ))

    messages.append(LLMMessage(role="user", content=user_content, images=user_images))

    thinking_text: str | None = None
    try:
        result = await provider.acomplete(
            messages,
            system_prompt=system_prompt,
            temperature=0.1,
            max_tokens=4096,
            think=request.enable_thinking,
        )
        if isinstance(result, LLMResult):
            answer = result.content
            thinking_text = result.thinking or None
        else:
            answer = result
        if not answer:
            answer = "Unable to generate a response."
        # 清理 Gemini token 残留（例如 <unused778>:）
        import re
        answer = re.sub(r'<unused\d+>:?\s*', '', answer).strip()
    except Exception as e:
        logger.error(f"LLM chat error: {e}")
        answer = f"Sorry, I encountered an error generating the response: {str(e)}"

    # -- 4. 从知识图谱提取相关实体 --
    related_entities: list[str] = []
    if kg_summary:
        try:
            kg = await _get_kg_service(workspace_id)
            entities = await kg.get_entities(limit=200)
            entity_names = {e["name"].lower(): e["name"] for e in entities}
            answer_lower = answer.lower()
            context_lower = context.lower()
            for lower_name, original_name in entity_names.items():
                if len(lower_name) >= 2 and (lower_name in answer_lower or lower_name in context_lower):
                    related_entities.append(original_name)
        except Exception as e:
            logger.warning(f"Failed to extract related entities: {e}")

    # -- 5. 将消息持久化到数据库（尽力而为） --
    try:
        import uuid
        from app.models.chat_message import ChatMessage as ChatMessageModel

        user_row = ChatMessageModel(
            workspace_id=workspace_id,
            message_id=str(uuid.uuid4()),
            role="user",
            content=request.message,
        )
        db.add(user_row)

        assistant_row = ChatMessageModel(
            workspace_id=workspace_id,
            message_id=str(uuid.uuid4()),
            role="assistant",
            content=answer,
            sources=[s.model_dump() for s in sources] if sources else None,
            related_entities=related_entities[:30] if related_entities else None,
            image_refs=[img.model_dump() for img in chat_image_refs] if chat_image_refs else None,
            thinking=thinking_text,
        )
        db.add(assistant_row)
        await db.commit()
    except Exception as e:
        logger.warning(f"Failed to persist chat messages: {e}")
        await db.rollback()

    return ChatResponse(
        answer=answer,
        sources=sources,
        related_entities=related_entities[:30],  # 最多 30 个
        kg_summary=kg_summary or None,
        image_refs=chat_image_refs,
        thinking=thinking_text,
    )


# ---------------------------------------------------------------------------
# LLM 能力端点
# ---------------------------------------------------------------------------

@router.get("/capabilities", response_model=LLMCapabilitiesResponse)
async def get_llm_capabilities():
    """检查 LLM 提供商能力（思考、视觉）。"""
    from app.services.llm import get_llm_provider
    from app.core.config import settings

    provider = get_llm_provider()
    provider_name = settings.LLM_PROVIDER.lower()

    # 各提供商的思考模式默认值：
    # Gemini：默认开启思考（快速、云端）
    # Ollama：默认关闭思考（本地硬件较慢），可通过 OLLAMA_ENABLE_THINKING 配置
    if provider_name == "ollama":
        thinking_default = settings.OLLAMA_ENABLE_THINKING
    else:
        thinking_default = provider.supports_thinking()

    return LLMCapabilitiesResponse(
        provider=settings.LLM_PROVIDER,
        model=settings.OLLAMA_MODEL if provider_name == "ollama" else settings.LLM_MODEL_FAST,
        supports_thinking=provider.supports_thinking(),
        supports_vision=provider.supports_vision(),
        thinking_default=thinking_default,
    )


# ---------------------------------------------------------------------------
# 调试接口 —— 检查检索与 LLM 回答质量
# ---------------------------------------------------------------------------

@router.post("/debug-chat/{workspace_id}", response_model=DebugChatResponse)
async def debug_chat(
    workspace_id: int,
    request: ChatRequest,
    db: AsyncSession = Depends(get_db),
):
    """
    Debug version of chat — returns retrieval details + system prompt + answer
    so you can inspect what the LLM received vs what it answered.
    """
    kb = await verify_workspace_access(workspace_id, db)

    rag_service = get_rag_service(db, workspace_id)

    # -- 1. 检索 --
    chunks = []
    citations = []
    kg_summary = ""

    from app.services.my_rag_service import MYRAGService
    if isinstance(rag_service, MYRAGService):
        result = await rag_service.query_deep(
            question=request.message,
            top_k=8,
            document_ids=request.document_ids,
            mode="hybrid",
            include_images=False,
        )
        chunks = result.chunks
        citations = result.citations
        kg_summary = result.knowledge_graph_summary

    # -- 2. 构建来源 + 上下文（与聊天接口逻辑一致） --
    debug_used_ids: set[str] = set()
    debug_sources: list[DebugRetrievedSource] = []
    context_parts = []
    for i, chunk in enumerate(chunks):
        citation = citations[i] if i < len(citations) else None
        cid = _generate_citation_id(debug_used_ids)
        debug_used_ids.add(cid)
        debug_sources.append(DebugRetrievedSource(
            index=cid,
            document_id=chunk.document_id,
            page_no=chunk.page_no,
            heading_path=chunk.heading_path,
            source_file=citation.source_file if citation else "",
            content_preview=chunk.content[:500],
            score=0.0,
            source_type="vector",
        ))
        meta_parts = []
        if citation:
            meta_parts.append(citation.source_file)
            if citation.page_no:
                meta_parts.append(f"page {citation.page_no}")
        heading = " > ".join(chunk.heading_path) if chunk.heading_path else ""
        if heading:
            meta_parts.append(heading)
        meta_line = f" ({', '.join(meta_parts)})" if meta_parts else ""
        context_parts.append(f"Source [{cid}]{meta_line}:\n{chunk.content}")

    # 注意：知识图谱摘要不作为可引用来源（可能包含幻觉数据）
    context = "\n\n---\n\n".join(context_parts)

    # -- 3. 构建提示词（与聊天接口架构一致） --
    # 简短系统提示词 + 将来源/规则放入用户消息
    sys_prompt = (kb.system_prompt or DEFAULT_SYSTEM_PROMPT) + HARD_SYSTEM_PROMPT

    # 构建用户消息：上下文 → 规则 → 问题
    user_parts: list[str] = []
    user_parts.append("I have retrieved the following document sources for you.\n")
    user_parts.append("=== DOCUMENT SOURCES ===")
    user_parts.append(context)
    user_parts.append("=== END SOURCES ===\n")

    user_parts.append(
        "IMPORTANT INSTRUCTIONS:\n"
        "- CRITICAL: Read EVERY source carefully before answering. The answer often "
        "requires combining data from MULTIPLE sources. Do NOT skip any source.\n"
        "- TABLE DATA: Sources contain table data as 'Key, Year = Value' pairs. "
        "You MUST extract the actual values. "
        "Example: 'ROE, 2023 = 12,8%. ROE, 2024 = 15,6%' means ROE was 12.8% in 2023 "
        "and 15.6% in 2024. Report these numbers in your answer.\n"
        "- Use the DOCUMENT SOURCES above to answer. Do NOT add outside knowledge.\n"
        "- You MAY compare, synthesize, and reason across multiple sources.\n"
        "- Cite every fact using the source IDs shown in brackets, e.g. [a3x9][b2m7] — one ID per bracket.\n"
        "- For images: [IMG-p4f2][IMG-q7r3] — use the IDs shown in the image list.\n"
        "- NEVER say 'không có thông tin' or 'no information' for data that IS present "
        "in any source. If a source contains 'Key = Value', report that value.\n"
        "- Only say information is unavailable when you have checked ALL sources "
        "and none contains the answer.\n"
        "- If no source is relevant at all, say: "
        "\"Tài liệu không chứa thông tin này.\" without any citations.\n"
        "- Answer in the same language as my question.\n"
    )

    # 对话上下文回顾（如果存在历史）
    if request.history:
        last_exchange = request.history[-2:]
        recap_parts = []
        for msg in last_exchange:
            prefix = "User" if msg.role == "user" else "Assistant"
            recap_parts.append(f"{prefix}: {msg.content[:300]}")
        user_parts.append(
            "CONVERSATION CONTEXT (previous exchange):\n"
            + "\n".join(recap_parts) + "\n"
        )

    user_parts.append(f"My question: {request.message}")
    user_content = "\n".join(user_parts)

    # -- 4. 调用 LLM --
    from app.services.llm import get_llm_provider
    from app.services.llm.types import LLMMessage, LLMResult

    provider = get_llm_provider()

    messages: list[LLMMessage] = []
    for msg in request.history[-10:]:
        role = "user" if msg.role == "user" else "assistant"
        messages.append(LLMMessage(role=role, content=msg.content))
    messages.append(LLMMessage(role="user", content=user_content))

    answer = ""
    thinking_text: str | None = None
    try:
        llm_result = await provider.acomplete(
            messages,
            system_prompt=sys_prompt,
            temperature=0.1,
            max_tokens=4096,
            think=request.enable_thinking,
        )
        if isinstance(llm_result, LLMResult):
            answer = llm_result.content
            thinking_text = llm_result.thinking or None
        else:
            answer = llm_result
        # 去除 Gemini 令牌残留（例如 <unused778>:）
        import re
        answer = re.sub(r'<unused\d+>:?\s*', '', answer).strip()
    except Exception as e:
        answer = f"LLM error: {e}"

    from app.core.config import settings as _s
    return DebugChatResponse(
        question=request.message,
        workspace_id=workspace_id,
        retrieved_sources=debug_sources,
        kg_summary=kg_summary,
        total_sources=len(debug_sources),
        system_prompt=f"[SYSTEM]: {sys_prompt}\n\n[USER MESSAGE]:\n{user_content}",
        answer=answer,
        thinking=thinking_text,
        image_count=0,
        provider=_s.LLM_PROVIDER,
        model=_s.OLLAMA_MODEL if _s.LLM_PROVIDER == "ollama" else _s.LLM_MODEL_FAST,
    )
