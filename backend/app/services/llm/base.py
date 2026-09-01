"""
LLM 提供商基类
=========================
面向 LLM 文本 / 视觉生成与向量化的抽象接口。
"""
from __future__ import annotations

import asyncio
from abc import ABC, abstractmethod
from typing import AsyncGenerator, Optional

import numpy as np

from app.services.llm.types import LLMMessage, LLMResult, StreamChunk


class LLMProvider(ABC):
    """LLM 文本 / 多模态生成的抽象接口。"""

    @abstractmethod
    def complete(
        self,
        messages: list[LLMMessage],
        *,
        temperature: float = 0.0,
        max_tokens: int = 4096,
        system_prompt: Optional[str] = None,
        think: bool = False,
    ) -> str | LLMResult:
        """
        同步文本生成。

        参数：
            messages: 对话历史（可能包含图片）。
            temperature: 采样温度。
            max_tokens: 最大输出 token 数。
            system_prompt: 系统级指令（由提供商负责注入）。
            think: 为 True 且受支持时，返回带思考文本的 LLMResult。

        返回：
            生成的文本字符串；当 think=True 时返回 LLMResult。
        """
        ...

    async def acomplete(
        self,
        messages: list[LLMMessage],
        *,
        temperature: float = 0.0,
        max_tokens: int = 4096,
        system_prompt: Optional[str] = None,
        think: bool = False,
    ) -> str | LLMResult:
        """
        异步文本生成。
        默认在线程池中运行 complete()。
        支持原生异步的提供商应重写此方法。
        """
        return await asyncio.to_thread(
            self.complete,
            messages,
            temperature=temperature,
            max_tokens=max_tokens,
            system_prompt=system_prompt,
            think=think,
        )

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
        """异步流式生成。逐个产出 StreamChunk 对象。

        默认回退方式：调用 acomplete() 并产出一个文本分块。
        支持原生流式的提供商应重写此方法。
        """
        result = await self.acomplete(
            messages,
            temperature=temperature,
            max_tokens=max_tokens,
            system_prompt=system_prompt,
            think=think,
        )
        if isinstance(result, LLMResult):
            if result.thinking:
                yield StreamChunk(type="thinking", text=result.thinking)
            yield StreamChunk(type="text", text=result.content)
        else:
            yield StreamChunk(type="text", text=result)

    @abstractmethod
    def supports_vision(self) -> bool:
        """该提供商 / 模型是否支持图片输入。"""
        ...

    def supports_thinking(self) -> bool:
        """该提供商 / 模型是否支持思考模式。"""
        return False

    def supports_native_tools(self) -> bool:
        """该提供商 / 模型是否支持原生工具调用。"""
        return False


class EmbeddingProvider(ABC):
    """文本向量生成的抽象接口（供知识图谱使用）。"""

    @abstractmethod
    def embed_sync(self, texts: list[str]) -> np.ndarray:
        """
        同步批量向量化。

        返回：
            形状为 (len(texts), embedding_dim) 的 numpy 数组。
        """
        ...

    async def embed(self, texts: list[str]) -> np.ndarray:
        """
        异步批量向量化。
        默认在线程池中运行 embed_sync()。
        """
        return await asyncio.to_thread(self.embed_sync, texts)

    @abstractmethod
    def get_dimension(self) -> int:
        """返回该模型的向量维度。"""
        ...
