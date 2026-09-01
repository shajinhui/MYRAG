"""
与 RAG 相关的 Pydantic 请求 / 响应校验模式。
"""
from typing import Literal
from pydantic import BaseModel, Field, field_validator


class RAGQueryRequest(BaseModel):
    """RAG 查询端点的请求模式。"""
    question: str = Field(..., min_length=1, max_length=1000, description="The question to query")
    top_k: int = Field(default=5, ge=1, le=20, description="Number of chunks to retrieve")
    document_ids: list[int] | None = Field(default=None, description="Filter to specific document IDs")
    metadata_filter: dict | None = Field(default=None, description="Optional metadata filter for vector search")
    mode: str = Field(
        default="hybrid",
        description="Search mode: hybrid (default), vector_only, naive, local, global"
    )


class CitationResponse(BaseModel):
    """一条来源引用。"""
    source_file: str
    document_id: int
    page_no: int = 0
    heading_path: list[str] = []
    formatted: str = ""


class RetrievedChunkResponse(BaseModel):
    """单个检索分块的响应模式。"""
    content: str
    chunk_id: str
    score: float
    metadata: dict
    citation: CitationResponse | None = None

    model_config = {"from_attributes": True}


class DocumentImageResponse(BaseModel):
    """文档图片的响应模式。"""
    image_id: str
    document_id: int
    page_no: int
    caption: str = ""
    width: int = 0
    height: int = 0
    url: str = ""


class RAGQueryResponse(BaseModel):
    """RAG 查询的响应模式。"""
    query: str
    chunks: list[RetrievedChunkResponse]
    context: str
    total_chunks: int
    knowledge_graph_summary: str = ""
    citations: list[CitationResponse] = []
    image_refs: list[DocumentImageResponse] = []


class DocumentProcessRequest(BaseModel):
    """文档处理的请求模式。"""
    document_id: int


class DocumentProcessResponse(BaseModel):
    """文档处理的响应模式。"""
    document_id: int
    status: str
    chunk_count: int
    message: str


class BatchProcessRequest(BaseModel):
    """批量文档处理的请求模式。"""
    document_ids: list[int] = Field(..., min_length=1, description="List of document IDs to process")


class ProjectRAGStatsResponse(BaseModel):
    """工作区 RAG 统计的响应模式。"""
    workspace_id: int
    total_documents: int
    indexed_documents: int
    total_chunks: int
    image_count: int = 0
    myrag_documents: int = 0


# ---------------------------------------------------------------------------
# 知识图谱模式
# ---------------------------------------------------------------------------

class KGEntityResponse(BaseModel):
    """知识图谱实体（节点）。"""
    name: str
    entity_type: str = "Unknown"
    description: str = ""
    degree: int = 0  # 关系数量


class KGRelationshipResponse(BaseModel):
    """知识图谱关系（边）。"""
    source: str
    target: str
    description: str = ""
    keywords: str = ""
    weight: float = 1.0


class KGGraphNodeResponse(BaseModel):
    """图谱可视化载荷中的节点。"""
    id: str
    label: str
    entity_type: str = "Unknown"
    degree: int = 0


class KGGraphEdgeResponse(BaseModel):
    """图谱可视化载荷中的边。"""
    source: str
    target: str
    label: str = ""
    weight: float = 1.0


class KGGraphResponse(BaseModel):
    """供前端可视化的完整图谱导出。"""
    nodes: list[KGGraphNodeResponse] = []
    edges: list[KGGraphEdgeResponse] = []
    is_truncated: bool = False


class KGAnalyticsResponse(BaseModel):
    """知识图谱分析摘要。"""
    entity_count: int = 0
    relationship_count: int = 0
    entity_types: dict[str, int] = {}  # 类型 → 数量
    top_entities: list[KGEntityResponse] = []  # 按度排序的前 N 个实体
    avg_degree: float = 0.0


class DocumentBreakdownItem(BaseModel):
    """分析用的按文档拆分明细。"""
    document_id: int
    filename: str
    chunk_count: int = 0
    image_count: int = 0
    page_count: int = 0
    file_size: int = 0
    status: str = "pending"


class ProjectAnalyticsResponse(BaseModel):
    """扩展的项目分析。"""
    stats: ProjectRAGStatsResponse
    kg_analytics: KGAnalyticsResponse | None = None
    document_breakdown: list[DocumentBreakdownItem] = []


# ---------------------------------------------------------------------------
# 聊天模式
# ---------------------------------------------------------------------------

class ChatMessageSchema(BaseModel):
    """对话历史中的单条聊天消息。"""
    role: str = Field(..., description="user or assistant")
    content: str


class ChatRequest(BaseModel):
    """聊天端点的请求。"""
    message: str = Field(..., min_length=1, max_length=5000)
    history: list[ChatMessageSchema] = []
    document_ids: list[int] | None = None
    enable_thinking: bool = False
    force_search: bool = False  # 在调用 LLM 前预先检索，直接将来源作为上下文注入


class ChatSourceChunk(BaseModel):
    """聊天回答中引用的来源分块。"""
    index: str  # 4 位字母数字 ID，例如 "a3x9"（原为整数）
    chunk_id: str

    @field_validator("index", mode="before")
    @classmethod
    def coerce_index_to_str(cls, v):
        return str(v) if not isinstance(v, str) else v
    content: str
    document_id: int
    page_no: int = 0
    heading_path: list[str] = []
    score: float = 0.0
    source_type: str = "vector"  # "vector" | "kg"


class ChatImageRef(BaseModel):
    """聊天回答中引用的图片。"""
    ref_id: str | None = None  # 4 位字母数字 ID，例如 "p4f2"
    image_id: str
    document_id: int
    page_no: int = 0
    caption: str = ""
    url: str = ""
    width: int = 0
    height: int = 0


class ChatResponse(BaseModel):
    """聊天端点的响应。"""
    answer: str
    sources: list[ChatSourceChunk] = []
    related_entities: list[str] = []
    kg_summary: str | None = None
    image_refs: list[ChatImageRef] = []
    thinking: str | None = None


class PersistedChatMessage(BaseModel):
    """来自数据库的已持久化聊天消息。"""
    id: int
    message_id: str
    role: str
    content: str
    sources: list[ChatSourceChunk] | None = None
    related_entities: list[str] | None = None
    image_refs: list[ChatImageRef] | None = None
    thinking: str | None = None
    agent_steps: list | None = None
    created_at: str  # ISO 格式

    model_config = {"from_attributes": True}


class ChatHistoryResponse(BaseModel):
    """获取聊天历史的响应。"""
    workspace_id: int
    messages: list[PersistedChatMessage]
    total: int


class RateSourceRequest(BaseModel):
    """对来源引用进行评分的请求。"""
    message_id: str = Field(..., description="The message_id containing the source")
    source_index: str = Field(..., description="Source citation ID, e.g. 'a3x9'")
    rating: Literal["relevant", "partial", "not_relevant"] = Field(
        ..., description="Source rating"
    )


class RateSourceResponse(BaseModel):
    """来源评分后的响应。"""
    success: bool
    message_id: str
    ratings: dict[str, str]


class LLMCapabilitiesResponse(BaseModel):
    """LLM 能力检查的响应。"""
    provider: str
    model: str
    supports_thinking: bool
    supports_vision: bool
    thinking_default: bool = True


# ---------------------------------------------------------------------------
# 调试 / QA 模式
# ---------------------------------------------------------------------------

class DebugRetrievedSource(BaseModel):
    """A retrieved source for debug inspection."""
    index: str  # 4-char alphanumeric ID (was: int)
    document_id: int

    @field_validator("index", mode="before")
    @classmethod
    def coerce_index_to_str(cls, v):
        return str(v) if not isinstance(v, str) else v
    page_no: int
    heading_path: list[str] = []
    source_file: str = ""
    content_preview: str = ""  # 前 500 个字符
    score: float = 0.0
    source_type: str = "vector"


class DebugChatResponse(BaseModel):
    """Full debug response — retrieval + LLM answer for quality inspection."""
    # 查询
    question: str
    workspace_id: int

    # 检索
    retrieved_sources: list[DebugRetrievedSource] = []
    kg_summary: str = ""
    total_sources: int = 0

    # LLM
    system_prompt: str = ""
    answer: str = ""
    thinking: str | None = None

    # 图片
    image_count: int = 0

    # 元数据
    provider: str = ""
    model: str = ""
