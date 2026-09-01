"""
MYRAG 数据模型
===================

用于 MYRAG 流水线的数据类：文档解析、增强分块、引用与检索结果。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional


@dataclass
class ExtractedImage:
    """由 Docling 从文档中提取的图片。"""
    image_id: str
    document_id: int
    page_no: int
    file_path: str
    caption: str = ""
    width: int = 0
    height: int = 0
    bbox: Optional[tuple[float, float, float, float]] = None  # 坐标 x0, y0, x1, y1
    mime_type: str = "image/png"


@dataclass
class ExtractedTable:
    """由 Docling 从文档中提取的表格。"""
    table_id: str
    document_id: int
    page_no: int
    content_markdown: str  # table.export_to_markdown(doc)
    caption: str = ""      # LLM 生成的描述
    num_rows: int = 0
    num_cols: int = 0


@dataclass
class EnrichedChunk:
    """带有结构元数据的文档分块。"""
    content: str
    chunk_index: int
    source_file: str
    document_id: int
    page_no: int = 0
    heading_path: list[str] = field(default_factory=list)
    image_refs: list[str] = field(default_factory=list)  # 附近的 image_id
    table_refs: list[str] = field(default_factory=list)  # 附近的 table_id
    has_table: bool = False
    has_code: bool = False
    contextualized: str = ""  # 拼接后的 heading_path，用于提供上下文


@dataclass
class ParsedDocument:
    """使用 Docling 解析文档后的结果。"""
    document_id: int
    original_filename: str
    markdown: str
    page_count: int
    chunks: list[EnrichedChunk] = field(default_factory=list)
    images: list[ExtractedImage] = field(default_factory=list)
    tables: list[ExtractedTable] = field(default_factory=list)
    tables_count: int = 0


@dataclass
class Citation:
    """指向文档中具体位置的来源引用。"""
    source_file: str
    document_id: int
    page_no: int = 0
    heading_path: list[str] = field(default_factory=list)

    def format(self) -> str:
        """将引用格式化为人类可读的字符串。"""
        parts = [self.source_file]
        if self.page_no > 0:
            parts.append(f"p.{self.page_no}")
        if self.heading_path:
            parts.append(" > ".join(self.heading_path))
        return " | ".join(parts)


@dataclass
class DeepRetrievalResult:
    """带引用和知识图谱洞见的深度 RAG 查询结果。"""
    chunks: list[EnrichedChunk]
    citations: list[Citation]
    context: str  # 为 LLM 组装好的上下文
    query: str
    mode: str = "hybrid"
    knowledge_graph_summary: str = ""
    image_refs: list[ExtractedImage] = field(default_factory=list)
    table_refs: list[ExtractedTable] = field(default_factory=list)
