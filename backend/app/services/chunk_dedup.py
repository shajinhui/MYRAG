"""
入库前去重流水线
=====================================

在向量化之前过滤噪声并移除重复 / 近似重复的分块，
减少向量空间污染并提升检索质量。

三阶段流水线：
  1. 噪声过滤 —— 移除样板页眉页脚、法律套话、过短分块
  2. 精确去重 —— 使用 SHA-256 内容哈希丢弃完全相同的分块
  3. 近似去重 —— 使用字符 n-gram 分片 + Jaccard 相似度匹配模糊重复
"""
from __future__ import annotations

import hashlib
import logging
import re
from typing import Sequence

from app.core.config import settings
from app.services.models.parsed_document import EnrichedChunk

logger = logging.getLogger(__name__)

# ── 编译好的样板文本模式 ────────────────────────────────────────
# 每个模式匹配整段以样板内容为主的分块。
# 使用 re.IGNORECASE | re.DOTALL，以便处理多行分块。

_BOILERPLATE_PATTERNS: list[re.Pattern] = [
    # 版权 / 许可声明行
    re.compile(
        r"^[\s\S]{0,30}(?:©|copyright|\(c\)|all\s+rights?\s+reserved)"
        r"[\s\S]{0,300}$",
        re.IGNORECASE,
    ),
    # "Confidential" / "proprietary" 免责声明
    re.compile(
        r"^[\s\S]{0,30}(?:confidential|proprietary|internal\s+use\s+only)"
        r"[\s\S]{0,300}$",
        re.IGNORECASE,
    ),
    # 仅包含页码（"Page 3"、"- 12 -"、"3 / 10"、"Trang 5"）
    re.compile(
        r"^\s*(?:page|trang|p\.?)?\s*\d{1,4}\s*(?:[/of|trên]\s*\d{1,4})?\s*$",
        re.IGNORECASE,
    ),
    # 重复的短横线 / 下划线 / 等号（视觉分隔符）
    re.compile(r"^\s*[-_=~*]{4,}\s*$"),
    # 单独的 "Table of Contents" / "Mục lục" 标题
    re.compile(
        r"^\s*(?:table\s+of\s+contents?|mục\s+lục|nội\s+dung)\s*$",
        re.IGNORECASE,
    ),
    # 草稿 / 水印文本
    re.compile(
        r"^\s*(?:draft|bản\s+nháp|watermark|confidential)\s*$",
        re.IGNORECASE,
    ),
    # 页眉页脚模式："Company Name | Page X" 或 "Report Title — 2024"
    re.compile(
        r"^[A-ZÀ-Ỹa-zà-ỹ\s\-|·•]{3,60}\s*[|·•\-—]\s*(?:page|trang|p\.?)?\s*\d{0,4}\s*$",
        re.IGNORECASE,
    ),
]

# 越南语法律样板片段（部分匹配 —— 如果分块包含这些文本
# 且内容较短，很可能是样板内容）
_LEGAL_FRAGMENTS_VI = [
    "theo quy định của pháp luật",
    "không được sao chép",
    "bảo mật thông tin",
    "điều khoản sử dụng",
    "chịu trách nhiệm trước pháp luật",
    "bản quyền thuộc về",
]

_LEGAL_FRAGMENTS_EN = [
    "all rights reserved",
    "without prior written consent",
    "this document is confidential",
    "for internal use only",
    "subject to change without notice",
    "disclaimer:",
    "terms and conditions",
    "no part of this publication",
]


def _normalize_text(text: str) -> str:
    """折叠空白并转为小写，便于比较。"""
    return re.sub(r"\s+", " ", text.strip().lower())


def _content_hash(text: str) -> str:
    """规范化文本的 SHA-256 哈希。"""
    return hashlib.sha256(_normalize_text(text).encode("utf-8")).hexdigest()


def _char_ngrams(text: str, n: int = 5) -> set[str]:
    """从规范化文本生成字符级 n-gram 分片。"""
    normed = _normalize_text(text)
    if len(normed) < n:
        return {normed}
    return {normed[i : i + n] for i in range(len(normed) - n + 1)}


def _jaccard_similarity(set_a: set, set_b: set) -> float:
    """两个集合之间的 Jaccard 相似度。"""
    if not set_a or not set_b:
        return 0.0
    intersection = len(set_a & set_b)
    union = len(set_a | set_b)
    return intersection / union if union > 0 else 0.0


# ── 阶段 1：噪声过滤 ───────────────────────────────────────────────

def _is_boilerplate(text: str) -> bool:
    """检查文本是否匹配已知的样板模式。"""
    stripped = text.strip()

    # 全量匹配模式
    for pattern in _BOILERPLATE_PATTERNS:
        if pattern.match(stripped):
            return True

    # 包含法律片段的短分块
    normed = stripped.lower()
    if len(stripped) < 300:
        for frag in _LEGAL_FRAGMENTS_VI + _LEGAL_FRAGMENTS_EN:
            if frag in normed:
                return True

    return False


def _meaningful_char_count(text: str) -> int:
    """统计非空白、非标点字符的数量。"""
    return len(re.sub(r"[\s\-_=~*|#>•·\"\'`(){}\[\]]+", "", text))


def filter_noise(chunks: list[EnrichedChunk]) -> list[EnrichedChunk]:
    """
    阶段 1：移除以噪声为主的分块。

    移除：
      - 有效字符数少于 DEDUP_MIN_CHUNK_LENGTH 的分块
      - 样板页眉页脚 / 法律免责声明 / 版权声明
      - 只有空白或只有格式的分块

    无论文本长度如何，都会保留带 image_refs 或 table_refs 的分块，
    因为它们的增强说明文字具有语义价值。
    """
    min_len = settings.MYRAG_DEDUP_MIN_CHUNK_LENGTH
    kept: list[EnrichedChunk] = []
    removed = 0

    for chunk in chunks:
        # 始终保留带图片 / 表格的分块
        if chunk.image_refs or chunk.table_refs:
            kept.append(chunk)
            continue

        text = chunk.content.strip()

        # 空内容 / 仅空白
        if not text:
            removed += 1
            continue

        # 过短（去除格式后）
        if _meaningful_char_count(text) < min_len:
            removed += 1
            continue

        # 匹配样板内容
        if _is_boilerplate(text):
            removed += 1
            continue

        kept.append(chunk)

    if removed:
        logger.info(f"Noise filter: removed {removed}/{len(chunks)} boilerplate/short chunks")

    return kept


# ── 阶段 2：精确去重 ────────────────────────────────────────────────

def dedup_exact(chunks: list[EnrichedChunk]) -> list[EnrichedChunk]:
    """
    阶段 2：移除规范化后内容完全相同的分块。

    使用小写、压缩空白后的文本的 SHA-256 哈希。保留首次出现的分块。
    """
    seen_hashes: set[str] = set()
    kept: list[EnrichedChunk] = []
    removed = 0

    for chunk in chunks:
        h = _content_hash(chunk.content)
        if h in seen_hashes:
            removed += 1
            continue
        seen_hashes.add(h)
        kept.append(chunk)

    if removed:
        logger.info(f"Exact dedup: removed {removed}/{len(chunks)} identical chunks")

    return kept


# ── 阶段 3：近似重复检测 ───────────────────────────────────

def dedup_near(
    chunks: list[EnrichedChunk],
    threshold: float | None = None,
) -> list[EnrichedChunk]:
    """
    阶段 3：使用字符 n-gram 分片的 Jaccard 相似度
    移除近似重复的分块。

    对于每一对分块，当相似度 >= 阈值时丢弃更靠后的分块（按 chunk_index）。
    复杂度为 O(n²)，但每个文档通常少于 200 个分块，因此足够快。
    """
    if threshold is None:
        threshold = settings.MYRAG_DEDUP_NEAR_THRESHOLD

    if threshold >= 1.0:
        return chunks  # 已禁用

    # 预计算分片
    shingles = [_char_ngrams(c.content) for c in chunks]

    drop_indices: set[int] = set()

    for i in range(len(chunks)):
        if i in drop_indices:
            continue
        for j in range(i + 1, len(chunks)):
            if j in drop_indices:
                continue
            sim = _jaccard_similarity(shingles[i], shingles[j])
            if sim >= threshold:
                drop_indices.add(j)

    kept = [c for idx, c in enumerate(chunks) if idx not in drop_indices]
    removed = len(drop_indices)

    if removed:
        logger.info(
            f"Near dedup (threshold={threshold:.2f}): "
            f"removed {removed}/{len(chunks)} near-duplicate chunks"
        )

    return kept


# ── 公开 API ───────────────────────────────────────────────────────────

def deduplicate_chunks(
    chunks: list[EnrichedChunk],
) -> tuple[list[EnrichedChunk], dict[str, int]]:
    """
    运行完整的 3 阶段去重流水线。

    返回：
        (filtered_chunks, stats)，其中 stats = {
            "input": 输入分块总数，
            "noise_removed": 噪声过滤移除的数量，
            "exact_removed": 精确去重移除的数量，
            "near_removed": 近似去重移除的数量，
            "output": 输出分块总数，
        }
    """
    if not settings.MYRAG_DEDUP_ENABLED:
        return chunks, {"input": len(chunks), "output": len(chunks),
                        "noise_removed": 0, "exact_removed": 0, "near_removed": 0}

    total_input = len(chunks)

    # 阶段 1：噪声过滤
    after_noise = filter_noise(chunks)
    noise_removed = total_input - len(after_noise)

    # 阶段 2：精确去重
    after_exact = dedup_exact(after_noise)
    exact_removed = len(after_noise) - len(after_exact)

    # 阶段 3：近似去重
    after_near = dedup_near(after_exact)
    near_removed = len(after_exact) - len(after_near)

    # 重新编号 chunk_index，使其连续
    for i, chunk in enumerate(after_near):
        chunk.chunk_index = i

    stats = {
        "input": total_input,
        "noise_removed": noise_removed,
        "exact_removed": exact_removed,
        "near_removed": near_removed,
        "output": len(after_near),
    }

    total_removed = total_input - len(after_near)
    if total_removed:
        logger.info(
            f"Dedup pipeline: {total_input} → {len(after_near)} chunks "
            f"(-{total_removed}: noise={noise_removed}, exact={exact_removed}, "
            f"near={near_removed})"
        )

    return after_near, stats
