"""
文档加载服务
负责从多种文档格式中加载并提取文本。
"""
from __future__ import annotations

from pathlib import Path
from typing import NamedTuple
import logging

logger = logging.getLogger(__name__)


class LoadedDocument(NamedTuple):
    """表示已加载文档及其内容和元数据。"""
    content: str
    source: str
    file_type: str
    page_count: int = 1


def load_txt_file(file_path: Path) -> LoadedDocument:
    """加载纯文本文件。"""
    try:
        content = file_path.read_text(encoding="utf-8")
        return LoadedDocument(
            content=content,
            source=str(file_path),
            file_type="txt",
            page_count=1
        )
    except UnicodeDecodeError:
        # 尝试使用其他编码
        content = file_path.read_text(encoding="latin-1")
        return LoadedDocument(
            content=content,
            source=str(file_path),
            file_type="txt",
            page_count=1
        )


def load_pdf_file(file_path: Path) -> LoadedDocument:
    """加载 PDF 文件并提取文本。"""
    try:
        from pypdf import PdfReader

        reader = PdfReader(str(file_path))
        pages_text = []

        for page in reader.pages:
            text = page.extract_text()
            if text:
                pages_text.append(text)

        content = "\n\n".join(pages_text)

        return LoadedDocument(
            content=content,
            source=str(file_path),
            file_type="pdf",
            page_count=len(reader.pages)
        )
    except Exception as e:
        logger.error(f"Error loading PDF {file_path}: {e}")
        raise ValueError(f"Failed to load PDF: {e}")


def load_markdown_file(file_path: Path) -> LoadedDocument:
    """加载 Markdown 文件。"""
    content = file_path.read_text(encoding="utf-8")
    return LoadedDocument(
        content=content,
        source=str(file_path),
        file_type="md",
        page_count=1
    )


def load_document(file_path: str | Path) -> LoadedDocument:
    """
    根据文件类型加载文档。

    支持的格式：.txt、.pdf、.md

    参数：
        file_path: 文档文件路径

    返回：
        包含内容和元数据的 LoadedDocument

    抛出：
        ValueError: 文件类型不受支持或文件无法读取时
    """
    path = Path(file_path)

    if not path.exists():
        raise ValueError(f"File not found: {file_path}")

    suffix = path.suffix.lower()

    loaders = {
        ".txt": load_txt_file,
        ".pdf": load_pdf_file,
        ".md": load_markdown_file,
    }

    loader = loaders.get(suffix)
    if loader is None:
        raise ValueError(f"Unsupported file type: {suffix}. Supported: {list(loaders.keys())}")

    return loader(path)


def get_supported_extensions() -> list[str]:
    """返回支持的文件扩展名列表。"""
    return [".txt", ".pdf", ".md"]
