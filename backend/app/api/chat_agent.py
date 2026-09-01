"""
聊天代理 —— MYRAG 的半智能体 SSE 流式输出
====================================================

提供 SSE 流式端点，由 LLM 决定是调用 ``search_documents`` 还是直接回答，
并实时流式输出思考与 token。

SSE 事件类型：
  - status:         {"step": str, "detail": str}
  - thinking:       {"text": str}
  - sources:        {"sources": [...]}
  - images:         {"image_refs": [...]}
  - token:          {"text": str}
  - token_rollback: {}
  - complete:       {"answer": str, "sources": [...], ...}
  - error:          {"message": str}
"""
from __future__ import annotations

import asyncio
import json
import logging
import random
import re
import string
import uuid
from typing import AsyncGenerator, Optional

from fastapi import Depends, HTTPException, status
from fastapi.responses import StreamingResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import get_db
from app.models.knowledge_base import KnowledgeBase
from app.models.document import DocumentImage
from app.schemas.rag import (
    ChatRequest,
    ChatSourceChunk,
    ChatImageRef,
)
from app.services.llm.types import LLMMessage, LLMImagePart, StreamChunk

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# 常量
# ---------------------------------------------------------------------------

MAX_AGENT_ITERATIONS = 3
MAX_VISION_IMAGES = 3
SSE_HEARTBEAT_INTERVAL = 15  # 秒

_CITATION_ID_CHARS = string.ascii_lowercase + string.digits


def _generate_citation_id(existing: set[str]) -> str:
    """生成唯一的 4 位字母数字引用 ID。"""
    while True:
        cid = "".join(random.choices(_CITATION_ID_CHARS, k=4))
        if any(c.isalpha() for c in cid) and cid not in existing:
            return cid


# ---------------------------------------------------------------------------
# 工具定义
# ---------------------------------------------------------------------------

# Gemini 原生函数调用
def _get_gemini_tool():
    """延迟创建 Gemini Tool，避免在模块顶层导入。"""
    from google.genai import types
    return types.Tool(function_declarations=[
        types.FunctionDeclaration(
            name="search_documents",
            description=(
                "Search the knowledge base for relevant document sections. "
                "Use this tool when the user asks about document content, data, or facts. "
                "IMPORTANT: Rewrite the user's question as a detailed, specific search query "
                "to get better retrieval results. "
                "Do NOT use this tool for greetings, chitchat, or non-document questions."
            ),
            parameters={
                "type": "OBJECT",
                "properties": {
                    "query": {
                        "type": "STRING",
                        "description": (
                            "A rewritten, detailed search query based on the user's question. "
                            "Examples: 'revenue?' → 'total revenue figures and financial performance metrics'. "
                            "'AI là gì?' → 'định nghĩa trí tuệ nhân tạo, lịch sử và ứng dụng'"
                        ),
                    },
                    "top_k": {
                        "type": "INTEGER",
                        "description": "Number of relevant chunks to retrieve (default: 5, max: 10)",
                    },
                },
                "required": ["query"],
            },
        ),
    ])



# ---------------------------------------------------------------------------
# Ollama 基于提示词的工具调用 —— 回答前必须搜索
# ---------------------------------------------------------------------------

OLLAMA_TOOL_SYSTEM = """\
## TOOL: search_documents

You have ONE tool: search_documents.  You call it by outputting EXACTLY:

<tool_call>{"name": "search_documents", "arguments": {"query": "<rewritten query>"}}</tool_call>

### ABSOLUTE RULES (violations are FATAL errors)

1. **Except for simple conversational messages, ALWAYS CALL search_documents FIRST.**
   Simple conversational messages that do NOT require a tool call:
   - Greetings: "hello", "xin chào", "hi", "hey", "good morning", etc.
   - Acknowledgements: "cảm ơn", "thank you", "thanks", "ok", "got it", etc.
   - Farewells: "bye", "goodbye", "tạm biệt", etc.
   For ALL other messages — questions, requests, factual queries, analysis — you MUST
   call search_documents before answering. Your knowledge is UNRELIABLE; only document
   sources are trustworthy. If you are unsure whether a message needs a search, SEARCH.

2. **Your ENTIRE first response to a searchable query must be ONLY the <tool_call> block.**
   No text before it. No text after it. No explanation. Just the tool call.

3. **NEVER say "the documents do not contain this information" UNLESS you have already
   called search_documents in THIS turn.** Even if previous context seems sufficient,
   you MUST search again — previous results may be incomplete.

4. **Rewrite the query** to be specific and detailed.
   "doanh thu" → "doanh thu thuần, tổng doanh thu theo năm, tăng trưởng doanh thu"
   "AI model" → "AI model architecture, performance benchmarks, training details"

5. After receiving search results, answer using ONLY those sources with citations.
   Format: claim text[source_id]. Example: Doanh thu đạt 4.850 tỷ VNĐ[a3x9].

6. **ALWAYS include relevant rich content from sources:**
   - Images/Diagrams/Charts: reference as [IMG-xxxx]
   - Tables: reproduce key data preserving structure
   - Math formulas: include LaTeX exactly as in sources
   - Code snippets: include with language tags
"""

OLLAMA_TOOL_REMINDER = (
    "\n\n[SYSTEM REMINDER] If this is a question or request, you MUST call search_documents FIRST. "
    "Output ONLY: <tool_call>{\"name\": \"search_documents\", \"arguments\": {\"query\": \"...\"}}</tool_call> "
    "Exception: simple greetings, thanks, or farewells do NOT require a tool call — respond directly. "
    "For everything else, searching is MANDATORY."
)

# ---------------------------------------------------------------------------
# Gemini 系统提示词强化 —— 强制问题类请求使用工具调用
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# Ollama 原生工具调用（Gemma 4、Qwen 3.5、Llama 4 等）
# ---------------------------------------------------------------------------

def _get_ollama_native_tool() -> list[dict]:
    """面向 Ollama 原生工具调用的 OpenAI 兼容格式工具定义。"""
    return [{
        "type": "function",
        "function": {
            "name": "search_documents",
            "description": (
                "Search the knowledge base for relevant document sections. "
                "Use this tool when the user asks about document content, data, or facts. "
                "IMPORTANT: Rewrite the user's question as a detailed, specific search query "
                "to get better retrieval results. "
                "Do NOT use this tool for greetings, chitchat, or non-document questions."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": (
                            "A rewritten, detailed search query based on the user's question. "
                            "Examples: 'revenue?' -> 'total revenue figures and financial performance metrics'. "
                            "'AI la gi?' -> 'dinh nghia tri tue nhan tao, lich su va ung dung'"
                        ),
                    },
                    "top_k": {
                        "type": "integer",
                        "description": "Number of relevant chunks to retrieve (default: 5, max: 10)",
                    },
                },
                "required": ["query"],
            },
        },
    }]


OLLAMA_NATIVE_TOOL_SYSTEM = """\

## Tool Usage (MANDATORY)

You have a tool called `search_documents` that searches the knowledge base.

### ABSOLUTE RULES:
1. For ALL user questions, requests, factual queries, or analysis — you MUST call \
`search_documents` FIRST before answering. Your knowledge is UNRELIABLE; only \
document sources are trustworthy.
2. Only skip the tool call for simple conversational messages:
   - Greetings: "hello", "xin chào", "hi", "hey", etc.
   - Acknowledgements: "cảm ơn", "thank you", "thanks", "ok", etc.
   - Farewells: "bye", "goodbye", "tạm biệt", etc.
3. NEVER say "the documents do not contain this information" or similar UNLESS you \
have already called `search_documents` in THIS turn. Even if previous context \
seems sufficient, you MUST search again — previous results may be incomplete.
4. Rewrite the user's query to be specific and detailed for better retrieval.
5. After receiving search results, answer using ONLY those sources with citations.
   Format: claim text[source_id]. Example: Doanh thu đạt 4.850 tỷ VNĐ[a3x9].
6. ALWAYS include relevant rich content from sources in your answer:
   - **Images/Diagrams/Charts**: Reference as [IMG-xxxx] when sources mention them.
   - **Tables**: Reproduce key data from tables, preserving structure.
   - **Math formulas**: Include LaTeX formulas exactly as they appear in sources.
   - **Code snippets**: Include code blocks with language tags.
   Do NOT omit these — they are essential parts of the answer.
"""

GEMINI_TOOL_SYSTEM = """\

## Tool Usage (MANDATORY)

You have a tool called `search_documents` that searches the knowledge base.

### ABSOLUTE RULES:
1. For ALL user questions, requests, factual queries, or analysis — you MUST call \
`search_documents` FIRST before answering. Even if the conversation history \
contains relevant information, you MUST search again to get fresh, accurate sources.
2. Only skip the tool call for simple conversational messages:
   - Greetings: "hello", "xin chào", "hi", "hey", etc.
   - Acknowledgements: "cảm ơn", "thank you", "thanks", "ok", etc.
   - Farewells: "bye", "goodbye", "tạm biệt", etc.
3. NEVER answer a question using information from previous turns without searching. \
Your previous answers may contain outdated or incomplete information.
4. NEVER say "the documents do not contain this information" or similar UNLESS you \
have already called `search_documents` in THIS turn.
5. NEVER reuse citation IDs from previous answers. Each answer must have its own \
fresh sources from a new search.
6. Rewrite the user's query to be specific and detailed for better retrieval.
7. ALWAYS include relevant rich content from sources in your answer:
   - **Images/Diagrams/Charts**: Reference as [IMG-xxxx] when sources mention them.
   - **Tables**: Reproduce key data from tables, preserving structure.
   - **Math formulas**: Include LaTeX formulas exactly as they appear in sources.
   - **Code snippets**: Include code blocks with language tags.
   Do NOT omit these — they are essential parts of the answer.
"""


# ---------------------------------------------------------------------------
# SSE 辅助函数（移植自 PageIndex backend/app/api/v1/chat.py）
# ---------------------------------------------------------------------------

def format_sse_event(event: str, data: dict) -> str:
    """将数据格式化为 SSE 事件字符串。"""
    json_data = json.dumps(data, default=str, ensure_ascii=False)
    return f"event: {event}\ndata: {json_data}\n\n"


async def sse_with_heartbeat(
    source: AsyncGenerator[str, None],
) -> AsyncGenerator[str, None]:
    """用周期性心跳注释包装 SSE 生成器。

    SSE 规范允许以 ':' 开头的行作为注释——浏览器 / 客户端会静默忽略，
    但它们能保持 TCP 连接存活，避免上游 LLM 响应较慢时超时。
    """
    queue: asyncio.Queue[str | None] = asyncio.Queue()

    async def _pump():
        try:
            async for event in source:
                await queue.put(event)
        except Exception:
            pass
        finally:
            await queue.put(None)  # 哨兵值

    task = asyncio.create_task(_pump())
    try:
        while True:
            try:
                event = await asyncio.wait_for(
                    queue.get(), timeout=SSE_HEARTBEAT_INTERVAL
                )
                if event is None:
                    break
                yield event
            except asyncio.TimeoutError:
                yield ": heartbeat\n\n"
    finally:
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass


# ---------------------------------------------------------------------------
# 工具执行器 —— 通过 MYRAG 检索
# ---------------------------------------------------------------------------

async def _execute_search_documents(
    workspace_id: int,
    query: str,
    top_k: int,
    db: AsyncSession,
    existing_ids: set[str],
) -> tuple[str, list[ChatSourceChunk], list[ChatImageRef], list[dict]]:
    """执行文档搜索并返回格式化上下文与结构化来源。

    返回：
        (context_text, sources, image_refs, image_parts_for_vision)
    """
    from app.services.rag_service import get_rag_service
    from app.services.my_rag_service import MYRAGService
    from pathlib import Path as _P
    from app.core.config import settings

    rag_service = get_rag_service(db, workspace_id)

    chunks = []
    citations = []
    if isinstance(rag_service, MYRAGService):
        result = await rag_service.query_deep(
            question=query,
            top_k=min(top_k, 10),
            mode="hybrid",
            include_images=False,
        )
        chunks = result.chunks
        citations = result.citations
    else:
        from types import SimpleNamespace
        legacy = rag_service.query(question=query, top_k=min(top_k, 10))
        for i, c in enumerate(legacy.chunks):
            chunks.append(SimpleNamespace(
                content=c.content,
                document_id=int(c.metadata.get("document_id", 0)),
                chunk_index=i,
                page_no=int(c.metadata.get("page_no", 0)),
                heading_path=str(c.metadata.get("heading_path", "")).split(" > ") if c.metadata.get("heading_path") else [],
                source_file=str(c.metadata.get("source", "")),
                image_refs=[],
            ))

    # 构建来源
    sources: list[ChatSourceChunk] = []
    context_parts: list[str] = []
    for i, chunk in enumerate(chunks):
        citation = citations[i] if i < len(citations) else None
        cid = _generate_citation_id(existing_ids)
        existing_ids.add(cid)
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

    context = "\n\n---\n\n".join(context_parts)

    # 构建图片引用
    seen_image_ids: set[str] = set()
    chunk_image_ids: list[str] = []
    for c in chunks:
        for iid in getattr(c, "image_refs", []) or []:
            if iid and iid not in seen_image_ids:
                seen_image_ids.add(iid)
                chunk_image_ids.append(iid)

    resolved_images: list[DocumentImage] = []
    if chunk_image_ids:
        img_result = await db.execute(
            select(DocumentImage).where(DocumentImage.image_id.in_(chunk_image_ids))
        )
        resolved_images = list(img_result.scalars().all())

    if not resolved_images:
        source_pages = {
            (getattr(c, "document_id", 0), getattr(c, "page_no", 0))
            for c in chunks if getattr(c, "page_no", 0) > 0
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
            seen = set()
            deduped = []
            for img in resolved_images:
                if img.image_id not in seen:
                    seen.add(img.image_id)
                    deduped.append(img)
            resolved_images = deduped

    chat_image_refs: list[ChatImageRef] = []
    image_context_parts: list[str] = []
    image_parts: list[dict] = []

    for img in resolved_images[:MAX_VISION_IMAGES]:
        img_ref_id = _generate_citation_id(existing_ids)
        existing_ids.add(img_ref_id)
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
        cap = f'"{img.caption}"' if img.caption else "no caption"
        image_context_parts.append(f"- [IMG-{img_ref_id}] Page {img.page_no}: {cap}")

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

    if image_context_parts:
        context += "\n\nDocument Images:\n" + "\n".join(image_context_parts)

    return context, sources, chat_image_refs, image_parts


# ---------------------------------------------------------------------------
# 代理循环 —— 半智能体流式输出
# ---------------------------------------------------------------------------

async def agent_chat_stream(
    workspace_id: int,
    message: str,
    history: list[dict],
    enable_thinking: bool,
    db: AsyncSession,
    system_prompt: str,
    force_search: bool = False,
) -> AsyncGenerator[dict, None]:
    """带流式输出的半智能体聊天循环。

    - force_search=True：调用 LLM 前预先检索，将来源作为上下文注入。
      无论模型工具调用能力如何，都保证每个查询都会执行检索。
    - force_search=False（默认）：智能体工具调用循环。
      Gemini 使用原生函数调用；Ollama 使用基于提示词的工具调用。

    逐个产出带 'event' 和 'data' 键的字典，供 SSE 格式化。
    """
    from app.services.llm import get_llm_provider
    from app.core.config import settings

    provider = get_llm_provider()
    provider_name = settings.LLM_PROVIDER.lower()
    is_gemini = provider_name == "gemini"

    existing_ids: set[str] = set()
    all_sources: list[ChatSourceChunk] = []
    all_images: list[ChatImageRef] = []
    all_image_parts: list[dict] = []

    # 构建对话消息
    messages: list[LLMMessage] = []
    for msg in history[-10:]:
        role = "user" if msg["role"] == "user" else "assistant"
        messages.append(LLMMessage(role=role, content=msg["content"]))

    # 构建用户消息
    messages.append(LLMMessage(role="user", content=message))

    # 工具 / 提示词设置
    tools = None
    effective_system_prompt = system_prompt
    is_ollama_native = False  # 用于处理工具结果

    if force_search:
        # ── 强制搜索模式：在调用 LLM 前预先检索 ──────────────────
        # 立即检索来源并作为上下文注入，无需工具调用。
        yield {"event": "status", "data": {"step": "retrieving", "detail": f"Searching: {message[:80]}..."}}

        context, sources, images, img_parts = await _execute_search_documents(
            workspace_id, message, 8, db, existing_ids,
        )
        all_sources.extend(sources)
        all_images.extend(images)
        all_image_parts.extend(img_parts)

        if sources:
            yield {"event": "sources", "data": {"sources": [s.model_dump() for s in sources]}}
        if images:
            yield {"event": "images", "data": {"image_refs": [i.model_dump() for i in images]}}

        if sources:
            tool_result_parts = [
                "I have retrieved the following document sources for you.\n",
                "=== DOCUMENT SOURCES ===",
                context,
                "=== END SOURCES ===\n",
                "IMPORTANT:\n"
                "- Read EVERY source above carefully. Answers often require "
                "combining data from MULTIPLE sources.\n"
                "- TABLE DATA: Sources may contain table data as 'Key, Year = Value' pairs. "
                "Example: 'ROE, 2023 = 12,8%' means ROE was 12.8% in 2023.\n"
                "- If no source contains relevant information, say: "
                "\"Tài liệu không chứa thông tin này.\"\n",
            ]
            tool_result_content = "\n".join(tool_result_parts)

            user_images_fs: list[LLMImagePart] = []
            if img_parts:
                for img_data in img_parts:
                    tool_result_content += f"\n[IMG-{img_data['img_ref_id']}] (page {img_data['page_no']}):"
                    user_images_fs.append(LLMImagePart(
                        data=img_data["inline_data"]["data"],
                        mime_type=img_data["inline_data"]["mime_type"],
                    ))

            tool_result_content += f"\n\nNow answer the question: {message}"
            messages.append(LLMMessage(
                role="user",
                content=tool_result_content,
                images=user_images_fs,
            ))
        # tools 保持为 None —— 模型直接使用提供的上下文回答
    elif is_gemini:
        tools = [_get_gemini_tool()]
        # 在 Gemini 的系统提示词中强化工具调用义务
        effective_system_prompt = system_prompt + GEMINI_TOOL_SYSTEM
    elif provider.supports_native_tools():
        # 支持原生工具调用的 Ollama（Gemma 4、Qwen 3.5、Llama 4 等）
        is_ollama_native = True
        tools = _get_ollama_native_tool()
        effective_system_prompt = system_prompt + "\n\n" + OLLAMA_NATIVE_TOOL_SYSTEM
    else:
        # Ollama 基于提示词的兜底（不支持原生工具的老模型）
        effective_system_prompt = system_prompt + "\n\n" + OLLAMA_TOOL_SYSTEM
        # 同时在用户消息中追加提醒，让模型在生成前就能看到
        # —— 强化工具调用要求
        messages[-1] = LLMMessage(
            role="user",
            content=messages[-1].content + OLLAMA_TOOL_REMINDER,
        )

    yield {"event": "status", "data": {"step": "analyzing", "detail": "Analyzing your question..."}}

    accumulated_text = ""
    thinking_text = ""

    for iteration in range(MAX_AGENT_ITERATIONS):
        iteration_text = ""
        function_calls: list[dict] = []
        tokens_yielded = False

        async for chunk in provider.astream(
            messages,
            temperature=0.1,
            max_tokens=settings.LLM_MAX_OUTPUT_TOKENS,
            system_prompt=effective_system_prompt,
            think=enable_thinking,
            tools=tools if (is_gemini or is_ollama_native) else None,
        ):
            if chunk.type == "thinking":
                thinking_text += chunk.text
                yield {"event": "thinking", "data": {"text": chunk.text}}
            elif chunk.type == "function_call":
                function_calls.append(chunk.function_call)
            elif chunk.type == "text":
                iteration_text += chunk.text
                # 投机式流式输出 —— 尚未看到工具调用时先发送 token
                if not function_calls:
                    accumulated_text += chunk.text
                    tokens_yielded = True
                    yield {"event": "token", "data": {"text": chunk.text}}

        if function_calls:
            # 回滚投机式 token
            if tokens_yielded:
                accumulated_text = ""
                yield {"event": "token_rollback", "data": {}}

            fc = function_calls[0]
            fc_name = fc.get("name", "")
            fc_args = fc.get("args", {})

            if fc_name == "search_documents":
                query = fc_args.get("query", message)
                top_k = int(fc_args.get("top_k", 8))

                yield {"event": "status", "data": {
                    "step": "retrieving",
                    "detail": f"Searching: {query[:80]}..."
                }}

                context, sources, images, img_parts = await _execute_search_documents(
                    workspace_id, query, top_k, db, existing_ids,
                )
                all_sources.extend(sources)
                all_images.extend(images)
                all_image_parts.extend(img_parts)

                if sources:
                    yield {"event": "sources", "data": {
                        "sources": [s.model_dump() for s in sources]
                    }}
                if images:
                    yield {"event": "images", "data": {
                        "image_refs": [i.model_dump() for i in images]
                    }}

                # 将工具结果作为带来源的用户消息构建
                tool_result_parts = [
                    "I have retrieved the following document sources for you.\n",
                    "=== DOCUMENT SOURCES ===",
                    context,
                    "=== END SOURCES ===\n",
                    "IMPORTANT:\n"
                    "- Read EVERY source above carefully. Answers often require "
                    "combining data from MULTIPLE sources.\n"
                    "- TABLE DATA: Sources may contain table data as 'Key, Year = Value' pairs. "
                    "Example: 'ROE, 2023 = 12,8%' means ROE was 12.8% in 2023.\n"
                    "- RICH CONTENT: Include ALL relevant images [IMG-xxxx], tables, "
                    "math formulas (LaTeX), diagrams, and code snippets from sources. "
                    "These are essential — do NOT omit them.\n"
                    "- If no source contains relevant information, say: "
                    "\"Tài liệu không chứa thông tin này.\"\n",
                ]
                tool_result_content = "\n".join(tool_result_parts)

                # 为视觉模型添加内联图片引用
                user_images: list[LLMImagePart] = []
                if img_parts:
                    for img_data in img_parts:
                        tool_result_content += f"\n[IMG-{img_data['img_ref_id']}] (page {img_data['page_no']}):"
                        user_images.append(LLMImagePart(
                            data=img_data["inline_data"]["data"],
                            mime_type=img_data["inline_data"]["mime_type"],
                        ))

                tool_result_content += f"\n\nNow answer the question: {message}"

                if is_gemini:
                    # Gemini：使用原生 Content（带 thought_signature）
                    # （Gemini 3 正确进行多轮推理所需）
                    # 以及用于工具结果的原生 FunctionResponse。
                    from google.genai import types as _gtypes

                    raw_content = getattr(provider, "last_response_content", None)
                    if raw_content:
                        # 保留模型原始响应（带 thought_signature）
                        messages.append(LLMMessage(
                            role="assistant",
                            content="",
                            _raw_provider_content=raw_content,
                        ))
                    else:
                        messages.append(LLMMessage(
                            role="assistant",
                            content=f"[Called search_documents(query=\"{query}\")]",
                        ))

                    # 构建带来源上下文的原生 FunctionResponse
                    func_resp_parts = [_gtypes.Part.from_function_response(
                        name="search_documents",
                        response={"result": tool_result_content},
                    )]
                    func_resp_content = _gtypes.Content(
                        role="user",
                        parts=func_resp_parts,
                    )
                    messages.append(LLMMessage(
                        role="user",
                        content="",
                        _raw_provider_content=func_resp_content,
                    ))

                    # 为视觉功能以独立用户消息发送图片
                    if img_parts:
                        img_llm_parts: list[LLMImagePart] = []
                        img_text = "Referenced document images:\n"
                        for img_data in img_parts:
                            img_text += f"[IMG-{img_data['img_ref_id']}] (page {img_data['page_no']})\n"
                            img_llm_parts.append(LLMImagePart(
                                data=img_data["inline_data"]["data"],
                                mime_type=img_data["inline_data"]["mime_type"],
                            ))
                        messages.append(LLMMessage(
                            role="user",
                            content=img_text,
                            images=img_llm_parts,
                        ))

                    # 搜索已完成，移除工具调用指令；
                    # 保留工具，使思考与工具感知仍然生效。
                    effective_system_prompt = system_prompt
                elif is_ollama_native:
                    # Ollama 原生：保留 assistant 的原始 tool_call 响应，
                    # 并通过原生 "tool" 角色消息发送工具结果。
                    raw_msg = getattr(provider, "last_response_message", None)
                    if raw_msg:
                        messages.append(LLMMessage(
                            role="assistant",
                            content="",
                            _raw_provider_content=raw_msg,
                        ))
                    else:
                        messages.append(LLMMessage(
                            role="assistant",
                            content=f"[Called search_documents(query=\"{query}\")]",
                        ))

                    # 使用 Ollama 原生工具消息格式发送工具结果
                    messages.append(LLMMessage(
                        role="tool",
                        content="",
                        _raw_provider_content={
                            "role": "tool",
                            "content": tool_result_content,
                        },
                    ))

                    # 为视觉功能以独立用户消息发送图片
                    if img_parts:
                        img_llm_parts: list[LLMImagePart] = []
                        img_text = "Referenced document images:\n"
                        for img_data in img_parts:
                            img_text += f"[IMG-{img_data['img_ref_id']}] (page {img_data['page_no']})\n"
                            img_llm_parts.append(LLMImagePart(
                                data=img_data["inline_data"]["data"],
                                mime_type=img_data["inline_data"]["mime_type"],
                            ))
                        messages.append(LLMMessage(
                            role="user",
                            content=img_text,
                            images=img_llm_parts,
                        ))

                    # 移除工具调用指令；保留工具以便感知。
                    effective_system_prompt = system_prompt
                else:
                    # Ollama 基于提示词：添加基于文本的 assistant + user 消息，
                    # 以保持正确的 user/assistant 交替
                    # （避免连续两条 user 消息，那会干扰 qwen3.5 等小模型）。
                    messages.append(LLMMessage(
                        role="assistant",
                        content=f"[Called search_documents(query=\"{query}\")]",
                    ))
                    messages.append(LLMMessage(
                        role="user",
                        content=tool_result_content,
                        images=user_images,
                    ))
                    # 从系统提示词中移除工具提示，
                    # 让模型基于来源回答而不是再次调用工具。
                    effective_system_prompt = system_prompt

                yield {"event": "status", "data": {
                    "step": "generating",
                    "detail": "Generating answer..."
                }}
            else:
                # 未知工具 —— 将累积文本作为回答
                logger.warning(f"Unknown tool call: {fc_name}")
                break
        else:
            # 模型没有调用工具 —— 回答已在 accumulated_text 中，结束。
            break

    # ── 兜底：模型未产生文本且未执行搜索 ──────────
    # qwen3.5:4b 等小型 Ollama 模型可能只在思考中表示需要搜索，
    # 却始终没有输出 <tool_call> 标签或任何文本。
    # 自动搜索并重试一次，避免返回“无法生成响应”。
    if not accumulated_text and not all_sources and not is_gemini:
        logger.warning(
            "Ollama produced no text and no tool call — fallback to auto-search"
        )
        yield {"event": "status", "data": {
            "step": "retrieving",
            "detail": f"Searching: {message[:80]}..."
        }}

        context, sources, images, img_parts = await _execute_search_documents(
            workspace_id, message, 8, db, existing_ids,
        )
        all_sources.extend(sources)
        all_images.extend(images)
        all_image_parts.extend(img_parts)

        if sources:
            yield {"event": "sources", "data": {
                "sources": [s.model_dump() for s in sources]
            }}
        if images:
            yield {"event": "images", "data": {
                "image_refs": [i.model_dump() for i in images]
            }}

        if sources:
            fallback_parts = [
                "I have retrieved the following document sources for you.\n",
                "=== DOCUMENT SOURCES ===",
                context,
                "=== END SOURCES ===\n",
                "IMPORTANT:\n"
                "- Read EVERY source above carefully.\n"
                "- Include ALL relevant images [IMG-xxxx], tables, math formulas, "
                "and code snippets from sources.\n"
                "- If no source contains relevant information, say: "
                "\"Tài liệu không chứa thông tin này.\"\n",
            ]
            fallback_content = "\n".join(fallback_parts)
            fallback_content += f"\n\nNow answer the question: {message}"

            # 为重试构建干净的消息 —— 只保留最近历史
            # 和带来源的用户问题。丢弃已经失败的
            # 工具调用提示词，让模型专注于回答。
            fallback_msgs: list[LLMMessage] = []
            for msg in history[-6:]:
                role = "user" if msg["role"] == "user" else "assistant"
                fallback_msgs.append(LLMMessage(role=role, content=msg["content"]))
            fallback_msgs.append(LLMMessage(role="user", content=fallback_content))

            yield {"event": "status", "data": {
                "step": "generating", "detail": "Generating answer..."
            }}

            async for chunk in provider.astream(
                fallback_msgs,
                temperature=0.1,
                max_tokens=settings.LLM_MAX_OUTPUT_TOKENS,
                system_prompt=system_prompt,  # 不带工具指令的原始提示词
                think=enable_thinking,
                tools=None,
            ):
                if chunk.type == "thinking":
                    thinking_text += chunk.text
                    yield {"event": "thinking", "data": {"text": chunk.text}}
                elif chunk.type == "text":
                    accumulated_text += chunk.text
                    yield {"event": "token", "data": {"text": chunk.text}}

    # 从知识图谱提取相关实体（尽力而为）
    related_entities: list[str] = []
    try:
        from app.api.rag import _get_kg_service
        kg = await _get_kg_service(workspace_id)
        entities = await kg.get_entities(limit=200)
        entity_names = {e["name"].lower(): e["name"] for e in entities}
        text_lower = accumulated_text.lower()
        for lower_name, original_name in entity_names.items():
            if len(lower_name) >= 2 and lower_name in text_lower:
                related_entities.append(original_name)
    except Exception:
        pass

    # 清理残留 token
    if accumulated_text:
        accumulated_text = re.sub(r'<unused\d+>:?\s*', '', accumulated_text).strip()

    yield {"event": "complete", "data": {
        "answer": accumulated_text or "Unable to generate a response.",
        "sources": [s.model_dump() for s in all_sources],
        "image_refs": [i.model_dump() for i in all_images],
        "thinking": thinking_text or None,
        "related_entities": related_entities[:30],
    }}


# ---------------------------------------------------------------------------
# SSE 流式端点
# ---------------------------------------------------------------------------

async def chat_stream_endpoint(
    workspace_id: int,
    request: ChatRequest,
    db: AsyncSession,
):
    """SSE 流式聊天端点。

    由 rag.py 路由调用——不是独立路由，以避免循环导入。
    """
    # 校验工作区
    result = await db.execute(
        select(KnowledgeBase).where(KnowledgeBase.id == workspace_id)
    )
    kb = result.scalar_one_or_none()
    if not kb:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Knowledge base not found",
        )

    # 构建系统提示词
    from app.api.chat_prompt import DEFAULT_SYSTEM_PROMPT, HARD_SYSTEM_PROMPT
    system_prompt = (kb.system_prompt or DEFAULT_SYSTEM_PROMPT) + HARD_SYSTEM_PROMPT

    # 构建历史
    history = [{"role": m.role, "content": m.content} for m in request.history]

    # 立即持久化用户消息
    try:
        from app.models.chat_message import ChatMessage as ChatMessageModel
        user_row = ChatMessageModel(
            workspace_id=workspace_id,
            message_id=str(uuid.uuid4()),
            role="user",
            content=request.message,
        )
        db.add(user_row)
        await db.commit()
    except Exception as e:
        logger.warning(f"Failed to persist user message: {e}")
        await db.rollback()

    async def event_generator() -> AsyncGenerator[str, None]:
        final_answer = ""
        final_sources = []
        final_images = []
        final_thinking = None
        final_entities = []

        # 收集代理步骤用于持久化（刷新后 ThinkingTimeline 仍可恢复）
        collected_steps: list[dict] = []
        step_counter = 0
        # 跟踪陆续到达的来源 / 图片，使 sources_found 在 generating 之前插入
        streaming_sources: list[dict] = []
        streaming_images: list[dict] = []

        try:
            async for event in agent_chat_stream(
                workspace_id=workspace_id,
                message=request.message,
                history=history,
                enable_thinking=request.enable_thinking,
                db=db,
                system_prompt=system_prompt,
                force_search=request.force_search,
            ):
                event_type = event["event"]
                event_data = event["data"]

                # 收集状态步骤；在 "generating" 之前插入 sources_found
                if event_type == "status":
                    step_name = event_data.get("step", "analyzing")

                    # 当生成开始时，先插入 sources_found（保证顺序正确）
                    if step_name == "generating" and streaming_sources:
                        step_counter += 1
                        badges = list(dict.fromkeys(
                            s.get("index", "") for s in streaming_sources[:6]
                        ))
                        collected_steps.append({
                            "id": f"step-{step_counter}",
                            "step": "sources_found",
                            "detail": f"Found {len(streaming_sources)} source{'s' if len(streaming_sources) != 1 else ''}",
                            "status": "completed",
                            "timestamp": 0,
                            "sourceCount": len(streaming_sources),
                            "imageCount": len(streaming_images),
                            "sourceBadges": badges,
                        })
                        streaming_sources.clear()
                        streaming_images.clear()

                    step_counter += 1
                    collected_steps.append({
                        "id": f"step-{step_counter}",
                        "step": step_name,
                        "detail": event_data.get("detail", ""),
                        "status": "completed",
                        "timestamp": 0,
                    })

                # 跟踪陆续到达的来源 / 图片
                elif event_type == "sources":
                    streaming_sources.extend(event_data.get("sources", []))

                elif event_type == "images":
                    streaming_images.extend(event_data.get("image_refs", []))

                # 将思考文本附加到 analyzing 步骤
                elif event_type == "thinking":
                    thinking_fragment = event_data.get("text", "")
                    for s in collected_steps:
                        if s["step"] == "analyzing":
                            s["thinkingText"] = (s.get("thinkingText") or "") + thinking_fragment
                            break

                elif event_type == "complete":
                    final_answer = event_data.get("answer", "")
                    final_sources = event_data.get("sources", [])
                    final_images = event_data.get("image_refs", [])
                    final_thinking = event_data.get("thinking")
                    final_entities = event_data.get("related_entities", [])

                    # 兜底：如果来源已到达，但 generating 步骤从未发出
                    if streaming_sources and not any(s["step"] == "sources_found" for s in collected_steps):
                        step_counter += 1
                        badges = list(dict.fromkeys(
                            s.get("index", "") for s in streaming_sources[:6]
                        ))
                        collected_steps.append({
                            "id": f"step-{step_counter}",
                            "step": "sources_found",
                            "detail": f"Found {len(streaming_sources)} source{'s' if len(streaming_sources) != 1 else ''}",
                            "status": "completed",
                            "timestamp": 0,
                            "sourceCount": len(streaming_sources),
                            "imageCount": len(streaming_images),
                            "sourceBadges": badges,
                        })

                    # 完成步骤
                    step_counter += 1
                    collected_steps.append({
                        "id": f"step-{step_counter}",
                        "step": "done",
                        "detail": "Done",
                        "status": "completed",
                        "timestamp": 0,
                    })

                yield format_sse_event(event_type, event_data)

        except Exception as e:
            logger.error(f"Stream error: {e}", exc_info=True)
            yield format_sse_event("error", {"message": str(e)})
        finally:
            # 持久化助手消息
            if final_answer:
                try:
                    from app.models.chat_message import ChatMessage as ChatMessageModel
                    assistant_row = ChatMessageModel(
                        workspace_id=workspace_id,
                        message_id=str(uuid.uuid4()),
                        role="assistant",
                        content=final_answer,
                        sources=final_sources if final_sources else None,
                        related_entities=final_entities[:30] if final_entities else None,
                        image_refs=final_images if final_images else None,
                        thinking=final_thinking,
                        agent_steps=collected_steps if collected_steps else None,
                    )
                    db.add(assistant_row)
                    await db.commit()
                except Exception as e:
                    logger.warning(f"Failed to persist assistant message: {e}")
                    await db.rollback()

    return StreamingResponse(
        sse_with_heartbeat(event_generator()),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
            "Connection": "keep-alive",
        },
    )
