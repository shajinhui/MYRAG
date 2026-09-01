"""
Gemini LLM 与向量提供商
=================================
使用 Google ``google-genai`` SDK 的具体实现。

同时支持 Gemini 2.5（thinking_budget_tokens）和 Gemini 3.x+
（thinking_level: minimal | low | medium | high）。
"""
from __future__ import annotations

import logging
import re
from typing import AsyncGenerator, Optional

import numpy as np
from google import genai
from google.genai import types

from app.services.llm.base import EmbeddingProvider, LLMProvider
from app.services.llm.types import LLMMessage, LLMResult, StreamChunk

logger = logging.getLogger(__name__)

# 从模型名中提取主版本号的正则：gemini-2.5-flash → 2，gemini-3.1-flash-lite → 3
_GEMINI_VERSION_RE = re.compile(r"gemini-(\d+)")


class GeminiLLMProvider(LLMProvider):
    """Google Gemini 文本 / 多模态生成。"""

    def __init__(
        self,
        api_key: str,
        model: str = "gemini-2.5-flash",
        thinking_level: str = "medium",
    ):
        self._client = genai.Client(api_key=api_key)
        self._model = model
        self._thinking_level = thinking_level
        self._major_version = self._parse_major_version(model)

    # ------------------------------------------------------------------
    # 内部辅助函数
    # ------------------------------------------------------------------

    @staticmethod
    def _parse_major_version(model: str) -> int:
        """从模型名中提取主版本号（例如 'gemini-3.1-flash' → 3）。"""
        match = _GEMINI_VERSION_RE.search(model)
        return int(match.group(1)) if match else 0

    @staticmethod
    def _build_parts(msg: LLMMessage) -> list[types.Part]:
        """将 LLMMessage 转换为 Gemini Part 对象列表。"""
        parts: list[types.Part] = []
        if msg.content:
            parts.append(types.Part.from_text(text=msg.content))
        for img in msg.images:
            parts.append(types.Part.from_bytes(data=img.data, mime_type=img.mime_type))
        return parts

    def _to_contents(self, messages: list[LLMMessage]) -> list[types.Content]:
        """将 LLMMessage 列表映射为 Gemini Content 对象。

        系统消息以模拟的 用户→模型 对话注入
        （Gemini 在 ``contents`` 中不支持原生 system 角色）。

        如果消息携带 ``_raw_provider_content``（原生 Gemini
        ``types.Content``），则直接使用——这样可以保留
        ``thought_signature`` 等无法从纯文本重建的不透明字段。
        """
        contents: list[types.Content] = []
        for msg in messages:
            # 原始 Gemini Content —— 原样使用（保留 thought_signature）
            if msg._raw_provider_content is not None:
                contents.append(msg._raw_provider_content)
                continue

            if msg.role == "system":
                # Gemini：contents 中不允许 system 角色 → 注入为
                # 用户指令 + 模型确认 的配对。
                contents.append(types.Content(
                    role="user",
                    parts=[types.Part.from_text(
                        text=f"[System Instructions]: {msg.content}",
                    )],
                ))
                contents.append(types.Content(
                    role="model",
                    parts=[types.Part.from_text(
                        text="Understood. I will follow these instructions.",
                    )],
                ))
            else:
                role = "model" if msg.role == "assistant" else "user"
                contents.append(types.Content(
                    role=role,
                    parts=self._build_parts(msg),
                ))
        return contents

    def _build_thinking_config(self) -> types.ThinkingConfig:
        """根据模型版本构建 ThinkingConfig。

        Gemini 2.5：使用 ``thinking_budget_tokens``（不支持 thinking_level）。
        Gemini 3.x+：使用 ``thinking_level`` + ``include_thoughts=True``。
        """
        if self._major_version >= 3:
            return types.ThinkingConfig(
                thinking_level=self._thinking_level,
                include_thoughts=True,
            )
        # Gemini 2.5 —— 使用基于预算的思考
        _BUDGET_MAP = {"minimal": 1024, "low": 2048, "medium": 4096, "high": 8192}
        budget = _BUDGET_MAP.get(self._thinking_level, 4096)
        return types.ThinkingConfig(thinking_budget=budget)

    # ------------------------------------------------------------------
    # LLMProvider 接口
    # ------------------------------------------------------------------

    def complete(
        self,
        messages: list[LLMMessage],
        *,
        temperature: float = 0.0,
        max_tokens: int = 4096,
        system_prompt: Optional[str] = None,
        think: bool = False,
    ) -> str | LLMResult:
        contents = self._to_contents(messages)

        config = types.GenerateContentConfig(
            temperature=temperature,
            max_output_tokens=max_tokens,
        )
        if system_prompt:
            config.system_instruction = system_prompt

        use_think = think and self.supports_thinking()
        if use_think:
            config.thinking_config = self._build_thinking_config()

        try:
            response = self._client.models.generate_content(
                model=self._model,
                contents=contents,
                config=config,
            )
            if use_think:
                return self._extract_with_thinking(response)
            return response.text or ""
        except Exception as e:
            logger.error(f"Gemini LLM call failed: {e}")
            return LLMResult(content="") if use_think else ""

    @staticmethod
    def _extract_with_thinking(response) -> LLMResult:
        """从 Gemini 响应中提取内容和思考文本。"""
        content = ""
        thinking = ""
        if response.candidates:
            for part in response.candidates[0].content.parts:
                if hasattr(part, "thought") and part.thought:
                    thinking += (part.text or "")
                else:
                    content += (part.text or "")
        return LLMResult(content=content, thinking=thinking)

    async def astream(
        self,
        messages: list[LLMMessage],
        *,
        temperature: float = 0.0,
        max_tokens: int = 4096,
        system_prompt: Optional[str] = None,
        think: bool = False,
        tools: list | None = None,
    ) -> AsyncGenerator[StreamChunk, None]:
        """通过 Gemini 的异步流式 API 进行流式生成。

        流式结束后，``self.last_response_content`` 保存累积的
        ``types.Content`` 及其全部 part（包括不透明的
        ``thought_signature`` 字段）。需要构建正确多轮历史
        （例如函数调用之后）的调用方应读取该属性，
        并通过 ``LLMMessage._raw_provider_content`` 传回。
        """
        contents = self._to_contents(messages)

        config = types.GenerateContentConfig(
            temperature=temperature,
            max_output_tokens=max_tokens,
        )
        if system_prompt:
            config.system_instruction = system_prompt
        if tools:
            config.tools = tools

        use_think = think and self.supports_thinking()
        if use_think:
            config.thinking_config = self._build_thinking_config()

        # 累积原始 part，让调用方可以访问完整响应，
        # 包括用于正确多轮回传的 thought_signature。
        accumulated_parts: list[types.Part] = []

        try:
            stream = await self._client.aio.models.generate_content_stream(
                model=self._model,
                contents=contents,
                config=config,
            )
            async for chunk in stream:
                if not chunk.candidates:
                    continue
                for part in chunk.candidates[0].content.parts:
                    accumulated_parts.append(part)

                    if getattr(part, "thought", False):
                        if part.text:
                            yield StreamChunk(type="thinking", text=part.text)
                    elif hasattr(part, "function_call") and part.function_call:
                        fc = part.function_call
                        yield StreamChunk(
                            type="function_call",
                            function_call={
                                "name": fc.name,
                                "args": dict(fc.args) if fc.args else {},
                            },
                        )
                    elif hasattr(part, "text") and part.text:
                        yield StreamChunk(type="text", text=part.text)
        except Exception as e:
            logger.error(f"Gemini streaming failed: {e}")
            yield StreamChunk(type="text", text="")
        finally:
            # 保存完整响应 Content，供需要 thought_signature
            # 回传（Gemini 3 函数调用）的调用方使用。
            self.last_response_content = types.Content(
                role="model",
                parts=accumulated_parts,
            ) if accumulated_parts else None

    def supports_vision(self) -> bool:
        return True

    def supports_thinking(self) -> bool:
        """Gemini 2.5+ 和 3.x+ 模型支持思考。"""
        return self._major_version >= 2

    def supports_native_tools(self) -> bool:
        return True


class GeminiEmbeddingProvider(EmbeddingProvider):
    """Google Gemini 文本向量化（``gemini-embedding-001``，3072 维）。"""

    _BATCH_SIZE = 100  # Gemini API 限制

    def __init__(self, api_key: str, model: str = "gemini-embedding-001"):
        self._client = genai.Client(api_key=api_key)
        self._model = model
        # gemini-embedding-001 → 3072，text-embedding-004 → 768
        self._dimension = 3072 if "embedding-001" in model else 768

    def embed_sync(self, texts: list[str]) -> np.ndarray:
        all_embeddings: list[list[float]] = []

        for i in range(0, len(texts), self._BATCH_SIZE):
            batch = texts[i : i + self._BATCH_SIZE]
            try:
                result = self._client.models.embed_content(
                    model=self._model,
                    contents=batch,
                )
                for emb in result.embeddings:
                    all_embeddings.append(emb.values)
            except Exception as e:
                logger.error(f"Gemini embedding failed for batch {i}: {e}")
                for _ in batch:
                    all_embeddings.append([0.0] * self._dimension)

        return np.array(all_embeddings, dtype=np.float32)

    def get_dimension(self) -> int:
        return self._dimension
