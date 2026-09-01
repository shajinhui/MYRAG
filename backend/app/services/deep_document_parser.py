"""
深度文档解析器 —— 向后兼容
==============================================

本模块从新的 ``document_parser`` 包重新导出。
例如现有导入::

    from app.services.deep_document_parser import DeepDocumentParser

无需改动即可继续使用。
"""
from app.services.document_parser.docling_parser import DoclingDocumentParser as DeepDocumentParser

__all__ = ["DeepDocumentParser"]
