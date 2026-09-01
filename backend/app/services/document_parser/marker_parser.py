"""
Marker 文档解析器
======================

使用 Marker（marker-pdf）的备选文档解析器，用于高质量
数学 / 公式提取（通过 Surya 输出 LaTeX）、更低的 GPU 占用（约 2-4GB 显存），
以及更广泛的格式支持（PDF、DOCX、PPTX、XLSX、EPUB、HTML、图片）。

安装：``pip install marker-pdf[full]``
"""
from __future__ import annotations

import json
import logging
import re
import time
import uuid
from pathlib import Path
from typing import Optional

from app.core.config import settings
from app.services.document_parser.base import BaseDocumentParser
from app.services.models.parsed_document import (
    ExtractedImage,
    ExtractedTable,
    EnrichedChunk,
    ParsedDocument,
)

logger = logging.getLogger(__name__)

_MARKER_EXTENSIONS = {".pdf", ".docx", ".pptx", ".xlsx", ".html", ".epub"}
_LEGACY_EXTENSIONS = {".txt", ".md"}

# Marker 在 paginate_output=True 时使用的默认分页分隔符
_PAGE_SEPARATOR = "-" * 48


class MarkerDocumentParser(BaseDocumentParser):
    """
    由 Marker（marker-pdf）驱动的文档解析器。

    特性：
    - 更优秀的数学 / 公式提取（通过 Surya 输出 LaTeX）
    - 更低的 GPU 占用（约 2-4GB，对比 Docling 的约 18-20GB）
    - 内置图片提取、表格 → markdown、代码块
    - 可选的 LLM 增强模式，改善表格与公式效果
    """

    parser_name = "marker"

    def __init__(self, workspace_id: int, output_dir: Optional[Path] = None):
        super().__init__(workspace_id, output_dir)
        self._converter = None
        self._artifact_dict = None

    @staticmethod
    def supported_extensions() -> set[str]:
        return _MARKER_EXTENSIONS | _LEGACY_EXTENSIONS

    # ------------------------------------------------------------------
    # 延迟初始化
    # ------------------------------------------------------------------

    def _get_converter(self):
        """延迟初始化带共享模型工件的 Marker PdfConverter。"""
        if self._converter is not None:
            return self._converter

        from marker.converters.pdf import PdfConverter
        from marker.models import create_model_dict
        from marker.config.parser import ConfigParser

        # 只加载一次模型（约 2GB，跨调用缓存）
        if self._artifact_dict is None:
            logger.info("Loading Marker ML models...")
            self._artifact_dict = create_model_dict()

        config = {
            "output_format": "markdown",
            "paginate_output": True,
            "disable_image_extraction": not settings.MYRAG_ENABLE_IMAGE_EXTRACTION,
        }

        # LLM 增强模式（更好的表格、公式、手写内容）
        if settings.MYRAG_MARKER_USE_LLM:
            config["use_llm"] = True

        config_parser = ConfigParser(config)

        self._converter = PdfConverter(
            config=config_parser.generate_config_dict(),
            artifact_dict=self._artifact_dict,
            processor_list=config_parser.get_processors(),
            renderer=config_parser.get_renderer(),
        )

        # 若启用，则挂载 LLM 服务
        if settings.MYRAG_MARKER_USE_LLM:
            try:
                self._converter.llm_service = config_parser.get_llm_service()
            except Exception as e:
                logger.warning(f"Failed to init Marker LLM service: {e}")

        return self._converter

    # ------------------------------------------------------------------
    # 主解析入口
    # ------------------------------------------------------------------

    def parse(
        self,
        file_path: str | Path,
        document_id: int,
        original_filename: str,
    ) -> ParsedDocument:
        path = Path(file_path)
        suffix = path.suffix.lower()
        start_time = time.time()

        if suffix in _MARKER_EXTENSIONS:
            result = self._parse_with_marker(path, document_id, original_filename)
        elif suffix in _LEGACY_EXTENSIONS:
            result = self._parse_legacy(path, document_id, original_filename)
        else:
            raise ValueError(
                f"Unsupported file type: {suffix}. "
                f"Supported: {_MARKER_EXTENSIONS | _LEGACY_EXTENSIONS}"
            )

        elapsed_ms = int((time.time() - start_time) * 1000)
        logger.info(
            f"[marker] Parsed document {document_id} ({original_filename}) in {elapsed_ms}ms: "
            f"{result.page_count} pages, {len(result.chunks)} chunks, "
            f"{len(result.images)} images, {result.tables_count} tables"
        )
        return result

    # ------------------------------------------------------------------
    # Marker 流水线
    # ------------------------------------------------------------------

    def _parse_with_marker(
        self,
        file_path: Path,
        document_id: int,
        original_filename: str,
    ) -> ParsedDocument:
        """使用 Marker 解析，以获得丰富的文档提取。"""
        from marker.output import text_from_rendered

        converter = self._get_converter()

        logger.info(f"Marker converting: {file_path}")
        rendered = converter(str(file_path))
        text, ext, marker_images = text_from_rendered(rendered)

        # 提取并保存图片
        images = self._save_marker_images(marker_images, document_id)

        # 使用 LLM 视觉为图片生成说明
        if settings.MYRAG_ENABLE_IMAGE_CAPTIONING and images:
            self._caption_images(images)

        # 清理输出中 "{0}"、"{1}" 之类的 Marker 页码标记
        markdown = re.sub(r"\n\{(\d+)\}", "", text)

        # 用服务 URL 更新 markdown 中的图片引用
        markdown = self._replace_image_refs_in_markdown(markdown, marker_images, images)

        # 从 markdown 中提取表格
        tables = self._extract_tables_from_markdown(markdown, document_id)

        # 为表格生成说明
        if settings.MYRAG_ENABLE_TABLE_CAPTIONING and tables:
            self._caption_tables(tables)

        # 注入表格说明
        markdown = self._inject_table_captions(markdown, tables)

        # 从分页输出中统计页数
        page_count = self._count_pages(markdown)

        # 切分文档
        chunks = self._chunk_markdown(
            markdown, document_id, original_filename, images, tables
        )

        return ParsedDocument(
            document_id=document_id,
            original_filename=original_filename,
            markdown=markdown,
            page_count=page_count,
            chunks=chunks,
            images=images,
            tables=tables,
            tables_count=len(tables),
        )

    # ------------------------------------------------------------------
    # 图片处理
    # ------------------------------------------------------------------

    def _save_marker_images(
        self,
        marker_images: dict,
        document_id: int,
    ) -> list[ExtractedImage]:
        """将 Marker 提取的图片（PIL）保存到磁盘并创建 ExtractedImage 列表。"""
        if not marker_images or not settings.MYRAG_ENABLE_IMAGE_EXTRACTION:
            return []

        images_dir = self.output_dir / "images"
        images_dir.mkdir(parents=True, exist_ok=True)

        images: list[ExtractedImage] = []
        count = 0

        for filename, pil_image in marker_images.items():
            if count >= settings.MYRAG_MAX_IMAGES_PER_DOC:
                break

            try:
                image_id = str(uuid.uuid4())
                image_path = images_dir / f"{image_id}.png"

                # 需要时转换为 RGB（某些格式无法处理 RGBA/P 模式）
                if pil_image.mode in ("RGBA", "P", "LA"):
                    pil_image = pil_image.convert("RGB")

                pil_image.save(str(image_path), format="PNG")
                width, height = pil_image.size

                # 尝试从文件名提取页码（例如 "page_3_image_1.png"）
                page_no = self._extract_page_from_filename(filename)

                images.append(ExtractedImage(
                    image_id=image_id,
                    document_id=document_id,
                    page_no=page_no,
                    file_path=str(image_path),
                    caption="",
                    width=width,
                    height=height,
                ))
                count += 1

            except Exception as e:
                logger.warning(f"Failed to save Marker image {filename}: {e}")
                continue

        logger.info(f"Saved {len(images)} Marker images from document {document_id}")
        return images

    @staticmethod
    def _extract_page_from_filename(filename: str) -> int:
        """尝试从 Marker 图片文件名中提取页码。"""
        # Marker 文件名类似："{doc_name}_page_{N}_image_{M}.png"
        match = re.search(r"page[_-]?(\d+)", filename, re.IGNORECASE)
        if match:
            return int(match.group(1))
        return 0

    def _replace_image_refs_in_markdown(
        self,
        markdown: str,
        marker_images: dict,
        images: list[ExtractedImage],
    ) -> str:
        """将 markdown 中的 Marker 图片文件名替换为服务 URL。"""
        if not marker_images or not images:
            return markdown

        # 构建映射：原始文件名 → 服务 URL
        # Marker 图片字典与我们的图片列表顺序一致
        filenames = list(marker_images.keys())
        for i, img in enumerate(images):
            if i < len(filenames):
                original_name = filenames[i]
                served_url = f"/static/doc-images/kb_{self.workspace_id}/images/{img.image_id}.png"
                # 替换 markdown 中的图片：![alt](original_name) → ![alt](served_url)
                markdown = markdown.replace(f"]({original_name})", f"]({served_url})")

        return markdown

    # ------------------------------------------------------------------
    # 从 markdown 提取表格
    # ------------------------------------------------------------------

    @staticmethod
    def _extract_tables_from_markdown(
        markdown: str, document_id: int
    ) -> list[ExtractedTable]:
        """从 markdown 输出中提取表格块。"""
        tables: list[ExtractedTable] = []
        lines = markdown.split("\n")
        current_page = 1
        i = 0

        while i < len(lines):
            line = lines[i]

            # 根据分页分隔符跟踪页码
            if line.strip() == _PAGE_SEPARATOR:
                current_page += 1
                i += 1
                continue

            # 检测表格开始
            if line.strip().startswith("|"):
                table_lines = [line]
                while i + 1 < len(lines) and lines[i + 1].strip().startswith("|"):
                    i += 1
                    table_lines.append(lines[i])

                content_md = "\n".join(table_lines)

                # 统计行列数
                data_rows = [
                    l for l in table_lines
                    if l.strip().startswith("|") and "---" not in l
                ]
                num_rows = max(0, len(data_rows) - 1)  # 排除表头
                num_cols = 0
                if data_rows:
                    num_cols = len([
                        c for c in data_rows[0].split("|") if c.strip()
                    ])

                if num_rows > 0 or num_cols > 0:
                    tables.append(ExtractedTable(
                        table_id=str(uuid.uuid4()),
                        document_id=document_id,
                        page_no=current_page,
                        content_markdown=content_md,
                        num_rows=num_rows,
                        num_cols=num_cols,
                    ))

            i += 1

        if tables:
            logger.info(f"Extracted {len(tables)} tables from Marker markdown")
        return tables

    # ------------------------------------------------------------------
    # 页数统计
    # ------------------------------------------------------------------

    @staticmethod
    def _count_pages(markdown: str) -> int:
        """从分页 markdown 输出中统计页数。"""
        if not markdown:
            return 0
        # Marker 使用 48 个短横线作为分页分隔符
        separators = markdown.count(_PAGE_SEPARATOR)
        return separators + 1  # 页数 = 分隔符数量 + 1

    # ------------------------------------------------------------------
    # 切分
    # ------------------------------------------------------------------

    def _chunk_markdown(
        self,
        markdown: str,
        document_id: int,
        original_filename: str,
        images: list[ExtractedImage] | None = None,
        tables: list[ExtractedTable] | None = None,
    ) -> list[EnrichedChunk]:
        """将 Marker 的 markdown 输出切分为 EnrichedChunks。

        策略：先按分页分隔符切分，再在每页内按标题切分，
        并遵守 max_tokens 限制。每个分块保留 page_no 与标题上下文。
        """
        pages = markdown.split(_PAGE_SEPARATOR)
        chunks: list[EnrichedChunk] = []
        chunk_index = 0

        for page_idx, page_text in enumerate(pages):
            page_no = page_idx + 1
            page_text = page_text.strip()
            if not page_text:
                continue

            # 移除 "{0}"、"{1}" 等 Marker 页码标记
            page_text = re.sub(r"^\{(\d+)\}\s*", "", page_text)

            # 按标题将页面拆分为章节
            sections = self._split_by_headings(page_text)

            for heading_path, section_text in sections:
                if not section_text.strip():
                    continue

                # 将过长章节拆分为子分块
                sub_chunks = self._split_text_by_tokens(
                    section_text,
                    max_tokens=settings.MYRAG_CHUNK_MAX_TOKENS,
                )

                for sub_text in sub_chunks:
                    if not sub_text.strip():
                        continue

                    has_table = "|" in sub_text and "---" in sub_text
                    has_code = "```" in sub_text

                    contextualized = ""
                    if heading_path:
                        contextualized = " > ".join(heading_path) + ": " + sub_text[:100]

                    chunks.append(EnrichedChunk(
                        content=sub_text,
                        chunk_index=chunk_index,
                        source_file=original_filename,
                        document_id=document_id,
                        page_no=page_no,
                        heading_path=heading_path,
                        has_table=has_table,
                        has_code=has_code,
                        contextualized=contextualized,
                    ))
                    chunk_index += 1

        # 为分块补充图片 / 表格引用（复用基类逻辑）
        chunks = self._enrich_chunks_with_refs(chunks, images, tables)

        return chunks

    @staticmethod
    def _split_by_headings(text: str) -> list[tuple[list[str], str]]:
        """按 markdown 标题将文本拆分为章节。

        返回 (heading_path, section_text) 元组列表。
        """
        heading_pattern = re.compile(r"^(#{1,6})\s+(.+)$", re.MULTILINE)
        matches = list(heading_pattern.finditer(text))

        if not matches:
            return [([], text)]

        sections: list[tuple[list[str], str]] = []
        # 跟踪当前标题层级
        heading_stack: list[tuple[int, str]] = []

        # 第一个标题之前的文本
        if matches[0].start() > 0:
            pre_text = text[:matches[0].start()].strip()
            if pre_text:
                sections.append(([], pre_text))

        for i, match in enumerate(matches):
            level = len(match.group(1))  # # 的数量
            title = match.group(2).strip()

            # 更新标题栈
            while heading_stack and heading_stack[-1][0] >= level:
                heading_stack.pop()
            heading_stack.append((level, title))
            heading_path = [h[1] for h in heading_stack]

            # 获取章节文本（从当前标题之后到下一个标题）
            start = match.end()
            end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
            section_text = text[start:end].strip()

            if section_text:
                sections.append((heading_path, section_text))

        return sections

    @staticmethod
    def _split_text_by_tokens(text: str, max_tokens: int = 512) -> list[str]:
        """在遵守近似 token 限制的前提下拆分文本。

        使用简单的词数近似（1 token ≈ 0.75 个词）。
        """
        # 近似：1 token ≈ 英文 4 字符，中日韩 2 字符
        max_chars = max_tokens * 4
        if len(text) <= max_chars:
            return [text]

        # 先按段落拆分
        paragraphs = re.split(r"\n\s*\n", text)
        chunks: list[str] = []
        current = ""

        for para in paragraphs:
            if len(current) + len(para) + 2 > max_chars:
                if current:
                    chunks.append(current.strip())
                # 处理超过 max_chars 的段落
                if len(para) > max_chars:
                    # 按句子拆分
                    sentences = re.split(r"(?<=[.!?])\s+", para)
                    current = ""
                    for sent in sentences:
                        if len(current) + len(sent) + 1 > max_chars:
                            if current:
                                chunks.append(current.strip())
                            current = sent
                        else:
                            current = current + " " + sent if current else sent
                else:
                    current = para
            else:
                current = current + "\n\n" + para if current else para

        if current.strip():
            chunks.append(current.strip())

        return chunks if chunks else [text]

    # ------------------------------------------------------------------
    # 旧版回退（TXT/MD）—— 与 Docling 相同
    # ------------------------------------------------------------------

    def _parse_legacy(
        self,
        file_path: Path,
        document_id: int,
        original_filename: str,
    ) -> ParsedDocument:
        """回退方案：使用旧版加载器解析 TXT/MD。"""
        from app.services.document_loader import load_document
        from app.services.chunker import DocumentChunker

        loaded = load_document(str(file_path))
        chunker = DocumentChunker(chunk_size=500, chunk_overlap=50)
        text_chunks = chunker.split_text(
            text=loaded.content,
            source=original_filename,
            extra_metadata={"document_id": document_id, "file_type": loaded.file_type},
        )

        chunks = [
            EnrichedChunk(
                content=tc.content,
                chunk_index=tc.chunk_index,
                source_file=original_filename,
                document_id=document_id,
                page_no=0,
            )
            for tc in text_chunks
        ]

        return ParsedDocument(
            document_id=document_id,
            original_filename=original_filename,
            markdown=loaded.content,
            page_count=loaded.page_count,
            chunks=chunks,
            images=[],
            tables_count=0,
        )
