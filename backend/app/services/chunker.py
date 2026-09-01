"""
文本切分服务
负责把文档拆分成更小的分块，用于向量化与检索。
"""
from __future__ import annotations

from typing import NamedTuple, Optional
from langchain_text_splitters import RecursiveCharacterTextSplitter


class TextChunk(NamedTuple):
    """表示带元数据的一段文本分块。"""
    content: str
    chunk_index: int
    char_start: int
    char_end: int
    metadata: dict


class DocumentChunker:
    """
    使用基于字符的递归切分方式将文档拆分为分块。
    """

    def __init__(
        self,
        chunk_size: int = 500,
        chunk_overlap: int = 50,
        separators: list[str] | None = None
    ):
        """
        初始化切分器。

        参数：
            chunk_size: 每个分块的最大字符数
            chunk_overlap: 分块之间重叠的字符数
            separators: 自定义切分分隔符（可选）
        """
        self.chunk_size = chunk_size
        self.chunk_overlap = chunk_overlap
        self.separators = separators or ["\n\n", "\n", ". ", " ", ""]

        self._splitter = RecursiveCharacterTextSplitter(
            chunk_size=chunk_size,
            chunk_overlap=chunk_overlap,
            length_function=len,
            separators=self.separators,
        )

    def split_text(
        self,
        text: str,
        source: str = "",
        extra_metadata: dict | None = None
    ) -> list[TextChunk]:
        """
        将文本拆分为带元数据的分块。

        参数：
            text: 需要切分的文本内容
            source: 来源标识（例如文件名）
            extra_metadata: 需要附加到每个分块的其他元数据

        返回：
            包含内容和元数据的 TextChunk 对象列表
        """
        if not text.strip():
            return []

        # 使用 LangChain 切分器
        chunks = self._splitter.split_text(text)

        result = []
        current_pos = 0

        for i, chunk_content in enumerate(chunks):
            # 在原始文本中查找实际位置
            # 由于重叠处理，该位置是近似值
            start_pos = text.find(chunk_content[:50], current_pos)
            if start_pos == -1:
                start_pos = current_pos

            end_pos = start_pos + len(chunk_content)

            metadata = {
                "source": source,
                "chunk_index": i,
                "total_chunks": len(chunks),
                **(extra_metadata or {})
            }

            result.append(TextChunk(
                content=chunk_content,
                chunk_index=i,
                char_start=start_pos,
                char_end=end_pos,
                metadata=metadata
            ))

            # 为下一次查找更新位置（考虑重叠）
            current_pos = max(start_pos + len(chunk_content) - self.chunk_overlap, current_pos + 1)

        return result

    def estimate_chunk_count(self, text: str) -> int:
        """
        在不真正切分的情况下估算分块数量。

        参数：
            text: 需要估算的文本

        返回：
            估算得到的分块数量
        """
        if not text:
            return 0

        text_length = len(text)
        effective_chunk = self.chunk_size - self.chunk_overlap

        if effective_chunk <= 0:
            return 1

        return max(1, (text_length + effective_chunk - 1) // effective_chunk)


# 默认切分器实例
default_chunker = DocumentChunker(chunk_size=500, chunk_overlap=50)


def chunk_text(
    text: str,
    source: str = "",
    chunk_size: int = 500,
    chunk_overlap: int = 50
) -> list[TextChunk]:
    """
    使用默认或自定义设置切分文本的便捷函数。

    参数：
        text: 需要切分的文本
        source: 来源标识
        chunk_size: 每个分块的最大字符数
        chunk_overlap: 分块之间的重叠字符数

    返回：
        TextChunk 对象列表
    """
    if chunk_size == 500 and chunk_overlap == 50:
        return default_chunker.split_text(text, source)

    chunker = DocumentChunker(chunk_size=chunk_size, chunk_overlap=chunk_overlap)
    return chunker.split_text(text, source)
