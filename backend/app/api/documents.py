from __future__ import annotations

import os
import re
import uuid
import logging
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, status, UploadFile, File, BackgroundTasks, Form
from fastapi.responses import PlainTextResponse
from sqlalchemy.ext.asyncio import AsyncSession
import json
from sqlalchemy import select

from app.core.config import settings
from app.core.deps import get_db
from app.core.exceptions import NotFoundError
from app.models.knowledge_base import KnowledgeBase
from app.models.document import Document, DocumentImage, DocumentStatus
from app.schemas.document import (
    DocumentReplaceResponse,
    DocumentResponse,
    DocumentUploadResponse,
)
from app.schemas.rag import DocumentImageResponse
from app.services.index_version import content_hash, index_fingerprint

logger = logging.getLogger(__name__)


def _inject_images_from_db(
    markdown: str,
    images: list[DocumentImage],
    workspace_id: int,
) -> str:
    """将剩余的 <!-- image --> 占位符替换为真实的 markdown 图片。

    当解析器在处理过程中没有注入图片时，作为安全网使用。
    图片按插入顺序（主键）匹配，与原始 Docling 文档中的图片顺序一致。
    """
    img_iter = iter(images)

    def _replacer(match):
        try:
            img = next(img_iter)
            url = f"/static/doc-images/kb_{workspace_id}/images/{img.image_id}.png"
            caption = (img.caption or "").replace("[", "").replace("]", "")
            return f"\n![{caption}]({url})\n"
        except StopIteration:
            return ""

    return re.sub(r"<!--\s*image\s*-->", _replacer, markdown)

router = APIRouter(prefix="/documents", tags=["documents"])

UPLOAD_DIR = settings.BASE_DIR / "uploads"
UPLOAD_DIR.mkdir(exist_ok=True)

ALLOWED_EXTENSIONS = {".pdf", ".txt", ".md", ".docx", ".pptx"}
MAX_FILE_SIZE = 50 * 1024 * 1024  # 50MB


@router.get("/workspace/{workspace_id}", response_model=list[DocumentResponse])
async def list_documents(
    workspace_id: int,
    db: AsyncSession = Depends(get_db),
):
    """列出知识库中的所有文档。"""
    result = await db.execute(select(KnowledgeBase).where(KnowledgeBase.id == workspace_id))
    kb = result.scalar_one_or_none()

    if kb is None:
        raise NotFoundError("KnowledgeBase", workspace_id)

    result = await db.execute(
        select(Document).where(Document.workspace_id == workspace_id).order_by(Document.created_at.desc())
    )
    return result.scalars().all()


async def process_document_background(document_id: int, file_path: str, workspace_id: int):
    """后台任务：处理文档以进行 RAG 索引。"""
    from app.core.database import async_session_maker
    from app.services.rag_service import get_rag_service

    async with async_session_maker() as db:
        try:
            # 加载工作区级别的知识图谱设置
            from sqlalchemy import select as sa_select
            from app.models.knowledge_base import KnowledgeBase
            ws_result = await db.execute(
                sa_select(KnowledgeBase.kg_language, KnowledgeBase.kg_entity_types)
                .where(KnowledgeBase.id == workspace_id)
            )
            ws_row = ws_result.one_or_none()
            kg_language = ws_row.kg_language if ws_row else None
            kg_entity_types = ws_row.kg_entity_types if ws_row else None

            rag_service = get_rag_service(
                db, workspace_id,
                kg_language=kg_language,
                kg_entity_types=kg_entity_types,
            )
            await rag_service.process_document(document_id, file_path)
            logger.info(f"Document {document_id} processed successfully")
        except Exception as e:
            logger.error(f"Failed to process document {document_id}: {e}")
            # 即使 process_document 自身的异常处理失败，也保证状态为 FAILED
            try:
                from sqlalchemy import select, update
                from app.models.document import Document, DocumentStatus
                result = await db.execute(
                    select(Document.status).where(Document.id == document_id)
                )
                current_status = result.scalar_one_or_none()
                if current_status and current_status != DocumentStatus.FAILED:
                    await db.execute(
                        update(Document)
                        .where(Document.id == document_id)
                        .values(
                            status=DocumentStatus.FAILED,
                            error_message=str(e)[:500],
                        )
                    )
                    await db.commit()
            except Exception as recovery_err:
                logger.error(f"Failed to set FAILED status for doc {document_id}: {recovery_err}")


@router.post("/upload/{workspace_id}", response_model=DocumentUploadResponse)
async def upload_document(
    workspace_id: int,
    file: UploadFile = File(...),
    custom_metadata: str | None = Form(None),
    db: AsyncSession = Depends(get_db),
):
    """向知识库上传文档。处理需要单独触发。"""
    
    parsed_metadata = None
    if custom_metadata:
        try:
            raw_metadata = json.loads(custom_metadata)
            if not isinstance(raw_metadata, list):
                raise ValueError("Metadata must be a list of key-value objects")
            
            parsed_metadata = {}
            for item in raw_metadata:
                if not isinstance(item, dict) or "key" not in item or "value" not in item:
                    raise ValueError("Each metadata item must contain 'key' and 'value' fields")
                parsed_metadata[item["key"]] = item["value"]
        except (json.JSONDecodeError, ValueError) as e:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Invalid custom_metadata format: {e}"
            )
            
    result = await db.execute(select(KnowledgeBase).where(KnowledgeBase.id == workspace_id))
    kb = result.scalar_one_or_none()

    if kb is None:
        raise NotFoundError("KnowledgeBase", workspace_id)

    ext = Path(file.filename).suffix.lower()
    if ext not in ALLOWED_EXTENSIONS:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"File type {ext} not allowed. Allowed: {ALLOWED_EXTENSIONS}"
        )

    content = await file.read()
    if len(content) > MAX_FILE_SIZE:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"File too large. Max size: {MAX_FILE_SIZE // 1024 // 1024}MB"
        )

    filename = f"{uuid.uuid4()}{ext}"
    file_path = UPLOAD_DIR / filename

    import aiofiles
    async with aiofiles.open(file_path, "wb") as f:
        await f.write(content)

    document = Document(
        workspace_id=workspace_id,
        filename=filename,
        original_filename=file.filename,
        file_type=ext[1:],
        file_size=len(content),
        status=DocumentStatus.PENDING,
        custom_metadata=parsed_metadata,
    )
    db.add(document)
    await db.commit()
    await db.refresh(document)

    return DocumentUploadResponse(
        id=document.id,
        filename=document.original_filename,
        status=document.status,
        message="Document uploaded. Click 'Process' to extract and index content."
    )


@router.put("/{document_id}/file", response_model=DocumentReplaceResponse)
async def replace_document_file(
    document_id: int,
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
):
    """替换一篇文档；内容没变就跳过，变了只重建这一篇。"""
    result = await db.execute(select(Document).where(Document.id == document_id))
    document = result.scalar_one_or_none()
    if document is None:
        raise NotFoundError("Document", document_id)

    if document.status in (
        DocumentStatus.PROCESSING,
        DocumentStatus.PARSING,
        DocumentStatus.INDEXING,
    ):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Document is currently being analyzed",
        )

    original_filename = file.filename or document.original_filename
    ext = Path(original_filename).suffix.lower()
    if ext not in ALLOWED_EXTENSIONS:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"File type {ext} not allowed. Allowed: {ALLOWED_EXTENSIONS}",
        )

    content = await file.read()
    if len(content) > MAX_FILE_SIZE:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"File too large. Max size: {MAX_FILE_SIZE // 1024 // 1024}MB",
        )

    new_hash = content_hash(content)
    if (
        document.status == DocumentStatus.INDEXED
        and document.content_hash == new_hash
        and document.index_fingerprint == index_fingerprint()
    ):
        # 真没变就别演“正在更新”了，用户和 CPU 都挺忙的。
        return DocumentReplaceResponse(
            document_id=document.id,
            status=document.status,
            chunk_count=document.chunk_count,
            changed=False,
            message="文件内容和索引配置都没变，已跳过重复处理。",
        )

    new_filename = f"{uuid.uuid4()}{ext}"
    new_file_path = UPLOAD_DIR / new_filename
    old_file_path = UPLOAD_DIR / document.filename

    import aiofiles
    try:
        async with aiofiles.open(new_file_path, "wb") as output:
            await output.write(content)

        document.filename = new_filename
        document.original_filename = original_filename
        document.file_type = ext[1:]
        document.file_size = len(content)
        document.status = DocumentStatus.PROCESSING
        document.error_message = None
        await db.commit()
    except Exception:
        await db.rollback()
        if new_file_path.exists():
            new_file_path.unlink()
        raise

    # 新文件已经落盘并提交成功，旧文件这才可以安心退休。
    if old_file_path != new_file_path and old_file_path.exists():
        try:
            old_file_path.unlink()
        except OSError as exc:
            logger.warning(f"Failed to remove replaced file {old_file_path}: {exc}")

    import asyncio
    asyncio.get_event_loop().create_task(
        process_document_background(
            document.id,
            str(new_file_path),
            document.workspace_id,
        )
    )

    return DocumentReplaceResponse(
        document_id=document.id,
        status=DocumentStatus.PROCESSING,
        chunk_count=document.chunk_count,
        changed=True,
        message="文件已替换，正在增量更新这篇文档。",
    )


@router.get("/{document_id}", response_model=DocumentResponse)
async def get_document(
    document_id: int,
    db: AsyncSession = Depends(get_db),
):
    """按 ID 获取文档。"""
    result = await db.execute(select(Document).where(Document.id == document_id))
    document = result.scalar_one_or_none()

    if document is None:
        raise NotFoundError("Document", document_id)

    return document


@router.get("/{document_id}/markdown")
async def get_document_markdown(
    document_id: int,
    db: AsyncSession = Depends(get_db),
):
    """获取文档的完整结构化 markdown 内容（MYRAG 解析）。"""
    result = await db.execute(select(Document).where(Document.id == document_id))
    document = result.scalar_one_or_none()

    if document is None:
        raise NotFoundError("Document", document_id)

    if not document.markdown_content:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No markdown content available. Document may not have been processed with MYRAG."
        )

    markdown = document.markdown_content

    # 安全网：如果仍有图片占位符，即时注入真实引用
    if "<!-- image" in markdown:
        img_result = await db.execute(
            select(DocumentImage)
            .where(DocumentImage.document_id == document_id)
            .order_by(DocumentImage.id)
        )
        images = img_result.scalars().all()
        if images:
            markdown = _inject_images_from_db(markdown, images, document.workspace_id)

    return PlainTextResponse(
        content=markdown,
        media_type="text/markdown",
    )


@router.get("/{document_id}/images", response_model=list[DocumentImageResponse])
async def get_document_images(
    document_id: int,
    db: AsyncSession = Depends(get_db),
):
    """列出文档的全部已提取图片。"""
    result = await db.execute(select(Document).where(Document.id == document_id))
    document = result.scalar_one_or_none()

    if document is None:
        raise NotFoundError("Document", document_id)

    result = await db.execute(
        select(DocumentImage)
        .where(DocumentImage.document_id == document_id)
        .order_by(DocumentImage.page_no)
    )
    images = result.scalars().all()

    return [
        DocumentImageResponse(
            image_id=img.image_id,
            document_id=img.document_id,
            page_no=img.page_no,
            caption=img.caption or "",
            width=img.width,
            height=img.height,
            url=f"/static/doc-images/kb_{document.workspace_id}/images/{img.image_id}.png",
        )
        for img in images
    ]


@router.delete("/{document_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_document(
    document_id: int,
    db: AsyncSession = Depends(get_db),
):
    """删除文档及其在向量存储中的分块。"""
    result = await db.execute(select(Document).where(Document.id == document_id))
    document = result.scalar_one_or_none()

    if document is None:
        raise NotFoundError("Document", document_id)

    if document.status == DocumentStatus.INDEXED:
        try:
            from app.services.rag_service import get_rag_service
            rag_service = get_rag_service(db, document.workspace_id)
            await rag_service.delete_document(document_id)
        except Exception as e:
            logger.warning(f"Failed to delete chunks from vector store: {e}")

    file_path = UPLOAD_DIR / document.filename
    try:
        if file_path.exists():
            os.remove(file_path)
    except OSError as e:
        logger.warning(f"Failed to remove uploaded file {file_path}: {e}")

    await db.delete(document)
    await db.commit()
