"""增量索引用到的两个小工具。

别被名字吓到：一个算文件指纹，一个算索引配置指纹。没上分布式锁，
也没造什么“索引中台”，个人知识库真没必要把自己折腾成云厂商。
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path


def content_hash(content: bytes) -> str:
    """计算文件内容的 SHA-256。内容一样，结果就一样。"""
    return hashlib.sha256(content).hexdigest()


def file_hash(file_path: str | Path) -> str:
    """分块读取文件，免得以后放宽 50MB 限制后一次性把内存吃撑。"""
    digest = hashlib.sha256()
    with Path(file_path).open("rb") as file:
        for block in iter(lambda: file.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def index_fingerprint() -> str:
    """记录会影响索引结果的配置；配置变了，就别假装旧索引还能用。"""
    # 放函数里再导入，这样单独测文件 Hash 时不用把整套后端依赖都搬过来。
    from app.core.config import settings

    if settings.MYRAG_ENABLED:
        config = {
            "pipeline": "myrag",
            "parser": settings.MYRAG_DOCUMENT_PARSER,
            "chunk_max_tokens": settings.MYRAG_CHUNK_MAX_TOKENS,
            "embedding_model": settings.MYRAG_EMBEDDING_MODEL,
            "dedup_enabled": settings.MYRAG_DEDUP_ENABLED,
            "dedup_min_length": settings.MYRAG_DEDUP_MIN_CHUNK_LENGTH,
            "dedup_threshold": settings.MYRAG_DEDUP_NEAR_THRESHOLD,
            "image_captioning": settings.MYRAG_ENABLE_IMAGE_CAPTIONING,
            "table_captioning": settings.MYRAG_ENABLE_TABLE_CAPTIONING,
        }
    else:
        config = {
            "pipeline": "legacy",
            "chunk_size": 500,
            "chunk_overlap": 50,
            "embedding_model": settings.MYRAG_EMBEDDING_MODEL,
        }

    raw = json.dumps(config, sort_keys=True, ensure_ascii=True)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()
