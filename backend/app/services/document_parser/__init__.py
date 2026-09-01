"""
文档解析器包
========================

根据配置创建文档解析器的工厂函数。

用法::

    from app.services.document_parser import get_document_parser

    parser = get_document_parser(workspace_id=1)
    result = parser.parse(file_path, document_id, original_filename)
"""
from __future__ import annotations

from pathlib import Path
from typing import Optional

from app.services.document_parser.base import BaseDocumentParser


def get_document_parser(
    workspace_id: int,
    output_dir: Optional[Path] = None,
) -> BaseDocumentParser:
    """根据 ``MYRAG_DOCUMENT_PARSER`` 配置创建文档解析器。"""
    from app.core.config import settings

    provider = settings.MYRAG_DOCUMENT_PARSER.lower()

    if provider == "marker":
        from app.services.document_parser.marker_parser import MarkerDocumentParser

        return MarkerDocumentParser(workspace_id, output_dir)

    # 默认：docling
    from app.services.document_parser.docling_parser import DoclingDocumentParser

    return DoclingDocumentParser(workspace_id, output_dir)


__all__ = [
    "get_document_parser",
    "BaseDocumentParser",
]
