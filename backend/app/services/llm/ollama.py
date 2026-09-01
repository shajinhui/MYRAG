"""
Ollama LLM 与向量提供商
==================================
使用 ``ollama`` Python 库实现本地模型的具体实现。
"""
from __future__ import annotations

import json
import logging
import re
from typing import AsyncGenerator, Optional

import numpy as np

from app.services.llm.base import EmbeddingProvider, LLMProvider
from app.services.llm.types import LLMMessage, LLMResult, StreamChunk

logger = logging.getLogger(__name__)

# 用于从模型输出中移除 <think>...</think> 块的正则
_THINK_RE = re.compile(r"<think>.*?</think>\s*", re.DOTALL)


class OllamaLLMProvider(LLMProvider):
    """本地 Ollama 文本 / 多模态生成。"""

    def __init__(self, host: str = "http://localhost:11434", model: str = "gemma3:12b"):
        self._host = host
        self._model = model
        self._thinking_supported: bool | None = None  # 延迟探测
        self._native_tools_supported: bool | None = None  # 延迟探测
        self.last_response_message: dict | None = None  # 用于原生工具调用历史

    # ------------------------------------------------------------------
    # 内部辅助函数
    # ------------------------------------------------------------------

    @staticmethod
    def _to_ollama_messages(
        messages: list[LLMMessage],
        system_prompt: Optional[str] = None,
    ) -> list[dict]:
        """将 LLMMessage 列表转换为 Ollama 消息字典。"""
        result: list[dict] = []

        if system_prompt:
            result.append({"role": "system", "content": system_prompt})

        for msg in messages:
            # 原始 Ollama 消息字典 —— 原样透传
            # （用于原生工具调用历史：带 tool_calls 的 assistant、工具结果）
            if msg._raw_provider_content is not None:
                result.append(msg._raw_provider_content)
                continue

            entry: dict = {"role": msg.role, "content": msg.content}
            if msg.images:
                # Ollama 的 'images' 字段接受原始字节
                entry["images"] = [img.data for img in msg.images]
            result.append(entry)

        return result

    @staticmethod
    def _extract_content(response, keep_thinking: bool = False) -> str | LLMResult:
        """从 Ollama 响应中提取可用文本。

        处理边界情况：
        - ``content`` 为空，但 ``thinking`` 字段包含答案
        - ``content`` 中包含内嵌的 ``<think>...</think>`` 块

        当 *keep_thinking* 为 True 时，返回 LLMResult，
        并将思考文本单独保留。
        """
        content = response.message.content or ""
        thinking = getattr(response.message, "thinking", None) or ""

        # 从内容中移除 <think>...</think> 块
        if "<think>" in content:
            content = _THINK_RE.sub("", content).strip()

        # 兜底：如果内容仍为空，则检查 thinking 字段
        if not content:
            if thinking:
                logger.warning(
                    "Ollama response.content is empty but thinking has %d chars — "
                    "using thinking as fallback", len(thinking)
                )
                content = _THINK_RE.sub("", thinking).strip()

        if keep_thinking:
            return LLMResult(content=content, thinking=thinking)
        return content

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
        import ollama

        ollama_msgs = self._to_ollama_messages(messages, system_prompt)
        use_think = think and self.supports_thinking()

        try:
            client = ollama.Client(host=self._host)
            response = client.chat(
                model=self._model,
                messages=ollama_msgs,
                options={"temperature": temperature, "num_predict": max_tokens},
                think=True if use_think else None,
            )
            result = self._extract_content(response, keep_thinking=use_think)
            content = result.content if isinstance(result, LLMResult) else result
            if not content:
                logger.warning(
                    "Ollama complete() returned empty | model=%s | "
                    "content=%r | thinking=%r",
                    self._model,
                    response.message.content,
                    getattr(response.message, "thinking", None),
                )
            return result
        except Exception as e:
            logger.error(f"Ollama LLM call failed: {e}", exc_info=True)
            return LLMResult(content="") if use_think else ""

    async def acomplete(
        self,
        messages: list[LLMMessage],
        *,
        temperature: float = 0.0,
        max_tokens: int = 4096,
        system_prompt: Optional[str] = None,
        think: bool = False,
    ) -> str | LLMResult:
        """通过 ollama.AsyncClient 实现原生异步（优于 to_thread）。"""
        import ollama

        ollama_msgs = self._to_ollama_messages(messages, system_prompt)
        use_think = think and self.supports_thinking()

        try:
            client = ollama.AsyncClient(host=self._host)
            response = await client.chat(
                model=self._model,
                messages=ollama_msgs,
                options={"temperature": temperature, "num_predict": max_tokens},
                think=True if use_think else None,
            )
            result = self._extract_content(response, keep_thinking=use_think)
            content = result.content if isinstance(result, LLMResult) else result
            if not content:
                logger.warning(
                    "Ollama acomplete() returned empty | model=%s | "
                    "content=%r | thinking=%r",
                    self._model,
                    response.message.content,
                    getattr(response.message, "thinking", None),
                )
            return result
        except Exception as e:
            logger.error(f"Ollama async LLM call failed: {e}", exc_info=True)
            return LLMResult(content="") if use_think else ""

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
        """通过 Ollama 的异步流式 API 进行流式生成。

        当提供 *tools* 时，使用原生工具调用，工具调用会通过
        ``chunk.message.tool_calls`` 到达。否则，通过状态机检测
        基于提示词的 ``<tool_call>`` XML 标签。
        """
        import ollama

        ollama_msgs = self._to_ollama_messages(messages, system_prompt)
        use_think = think and self.supports_thinking()

        try:
            client = ollama.AsyncClient(host=self._host)

            kwargs: dict = dict(
                model=self._model,
                messages=ollama_msgs,
                options={"temperature": temperature, "num_predict": max_tokens},
                stream=True,
                think=True if use_think else None,
            )
            if tools:
                kwargs["tools"] = tools

            stream = await client.chat(**kwargs)

            if tools:
                # ── 原生工具调用路径 ──────────────────────────────
                self.last_response_message = None

                async for chunk in stream:
                    thinking = getattr(chunk.message, "thinking", None) or ""
                    content = chunk.message.content or ""

                    if thinking:
                        yield StreamChunk(type="thinking", text=thinking)

                    if content:
                        cleaned = _THINK_RE.sub("", content)
                        if cleaned:
                            yield StreamChunk(type="text", text=cleaned)

                    # 原生工具调用以完整对象形式到达
                    tool_calls = getattr(chunk.message, "tool_calls", None)
                    if tool_calls:
                        self.last_response_message = {
                            "role": "assistant",
                            "content": content,
                            "tool_calls": [
                                {
                                    "function": {
                                        "name": tc.function.name,
                                        "arguments": tc.function.arguments,
                                    }
                                }
                                for tc in tool_calls
                            ],
                        }
                        for tc in tool_calls:
                            args = tc.function.arguments
                            yield StreamChunk(
                                type="function_call",
                                function_call={
                                    "name": tc.function.name,
                                    "args": args if isinstance(args, dict) else {},
                                },
                            )
            else:
                # ── 基于提示词的工具调用路径（XML 状态机） ────
                tool_buffer = ""
                in_tool_call = False

                async for chunk in stream:
                    thinking = getattr(chunk.message, "thinking", None) or ""
                    content = chunk.message.content or ""

                    if thinking:
                        yield StreamChunk(type="thinking", text=thinking)

                    if not content:
                        continue

                    if in_tool_call:
                        tool_buffer += content
                        if "</tool_call>" in tool_buffer:
                            match = re.search(
                                r"<tool_call>(.*?)</tool_call>",
                                tool_buffer,
                                re.DOTALL,
                            )
                            if match:
                                try:
                                    tool_data = json.loads(match.group(1).strip())
                                    yield StreamChunk(
                                        type="function_call",
                                        function_call={
                                            "name": tool_data.get("name", ""),
                                            "args": tool_data.get("arguments", {}),
                                        },
                                    )
                                except json.JSONDecodeError:
                                    logger.warning("Failed to parse tool call JSON: %s", match.group(1))
                                    yield StreamChunk(type="text", text=tool_buffer)
                            else:
                                yield StreamChunk(type="text", text=tool_buffer)
                            after = tool_buffer.split("</tool_call>", 1)[1]
                            tool_buffer = ""
                            in_tool_call = False
                            if after.strip():
                                yield StreamChunk(type="text", text=after)
                    elif "<tool_call>" in content:
                        before, rest = content.split("<tool_call>", 1)
                        if before.strip():
                            yield StreamChunk(type="text", text=before)
                        in_tool_call = True
                        tool_buffer = "<tool_call>" + rest
                        if "</tool_call>" in tool_buffer:
                            match = re.search(
                                r"<tool_call>(.*?)</tool_call>",
                                tool_buffer,
                                re.DOTALL,
                            )
                            if match:
                                try:
                                    tool_data = json.loads(match.group(1).strip())
                                    yield StreamChunk(
                                        type="function_call",
                                        function_call={
                                            "name": tool_data.get("name", ""),
                                            "args": tool_data.get("arguments", {}),
                                        },
                                    )
                                except json.JSONDecodeError:
                                    logger.warning("Failed to parse tool call JSON: %s", match.group(1))
                                    yield StreamChunk(type="text", text=tool_buffer)
                            after = tool_buffer.split("</tool_call>", 1)[1]
                            tool_buffer = ""
                            in_tool_call = False
                            if after.strip():
                                yield StreamChunk(type="text", text=after)
                    else:
                        cleaned = _THINK_RE.sub("", content)
                        if cleaned:
                            yield StreamChunk(type="text", text=cleaned)

                if in_tool_call and tool_buffer:
                    yield StreamChunk(type="text", text=tool_buffer)

        except Exception as e:
            logger.error(f"Ollama streaming failed: {e}", exc_info=True)
            yield StreamChunk(type="text", text="")

    def supports_vision(self) -> bool:
        # 视觉支持取决于模型（例如 qwen3-vl、llava 等）。
        # 这里返回 True 交给模型处理；如果模型不支持视觉，
        # Ollama API 会优雅地返回错误。
        return True

    def supports_thinking(self) -> bool:
        """通过探测调用检测模型是否支持思考模式。"""
        if self._thinking_supported is not None:
            return self._thinking_supported

        import ollama

        try:
            client = ollama.Client(host=self._host, timeout=10.0)
            response = client.chat(
                model=self._model,
                messages=[{"role": "user", "content": "Hi"}],
                options={"num_predict": 2},
                think=True,
            )
            # 执行到这里且没有报错，说明支持思考
            thinking = getattr(response.message, "thinking", None) or ""
            self._thinking_supported = True
            logger.info(
                f"Ollama thinking probe: model={self._model} host={self._host} "
                f"supported=True (thinking={len(thinking)} chars)"
            )
        except Exception as e:
            self._thinking_supported = False
            logger.info(
                f"Ollama thinking probe: model={self._model} host={self._host} "
                f"supported=False ({e})"
            )

        return self._thinking_supported

    def supports_native_tools(self) -> bool:
        """通过探测调用检测模型是否支持原生工具调用。

        发送一个应触发工具调用的问题。只有当模型 *实际* 产生
        ``tool_calls`` 响应时才标记为支持——而不是仅凭 API 接受参数。
        """
        if self._native_tools_supported is not None:
            return self._native_tools_supported

        import ollama

        _PROBE_TOOL = [{
            "type": "function",
            "function": {
                "name": "lookup",
                "description": "Look up information. You MUST call this for any question.",
                "parameters": {
                    "type": "object",
                    "properties": {"query": {"type": "string", "description": "search query"}},
                    "required": ["query"],
                },
            },
        }]

        try:
            client = ollama.Client(host=self._host, timeout=15.0)
            use_think = self.supports_thinking()
            response = client.chat(
                model=self._model,
                messages=[
                    {"role": "system", "content": "You MUST use the lookup tool for any question."},
                    {"role": "user", "content": "What is the capital of France?"},
                ],
                options={"num_predict": 256},
                tools=_PROBE_TOOL,
                think=True if use_think else None,
            )
            tool_calls = getattr(response.message, "tool_calls", None)
            self._native_tools_supported = bool(tool_calls)
            logger.info(
                "Ollama native tools probe: model=%s host=%s supported=%s "
                "(tool_calls=%s)",
                self._model, self._host, self._native_tools_supported,
                bool(tool_calls),
            )
        except Exception as e:
            self._native_tools_supported = False
            logger.info(
                "Ollama native tools probe: model=%s host=%s supported=False (%s)",
                self._model, self._host, e,
            )

        return self._native_tools_supported


class OllamaEmbeddingProvider(EmbeddingProvider):
    """本地 Ollama 文本向量化。"""

    def __init__(
        self,
        host: str = "http://localhost:11434",
        model: str = "bge-m3",
    ):
        self._host = host
        self._model = model
        self._dimension: Optional[int] = None

    def _detect_dimension(self) -> int:
        """通过运行探测请求检测向量维度。"""
        import ollama

        try:
            client = ollama.Client(host=self._host, timeout=10.0)
            result = client.embed(model=self._model, input=["dimension probe"])
            dim = len(result.embeddings[0])
            logger.info(f"Detected Ollama embedding dimension: {dim} for model {self._model}")
            return dim
        except Exception as e:
            logger.warning(f"Failed to detect embedding dimension: {e}, defaulting to config")
            from app.core.config import settings
            return settings.KG_EMBEDDING_DIMENSION

    @staticmethod
    def _sanitize_texts(texts: list[str]) -> list[str]:
        """清理文本，避免 Ollama 向量化产生 NaN 错误。

        某些文本（空文本、仅特殊字符、超长文本）会导致
        通过 Ollama 的 bge-m3 返回 NaN 向量或 500 错误。
        """
        sanitized = []
        for t in texts:
            t = t.strip()
            if not t:
                t = "[empty]"
            # 截断超长文本（>8192 token ≈ 32k 字符）
            if len(t) > 32000:
                t = t[:32000]
            sanitized.append(t)
        return sanitized

    def embed_sync(self, texts: list[str]) -> np.ndarray:
        import ollama

        clean = self._sanitize_texts(texts)
        try:
            result = ollama.embed(model=self._model, input=clean)
            arr = np.array(result.embeddings, dtype=np.float32)
            # 防护 NaN —— 用零值替换
            if np.any(np.isnan(arr)):
                logger.warning("Ollama embed_sync produced NaN values — replacing with zeros")
                arr = np.nan_to_num(arr, nan=0.0)
            return arr
        except Exception as e:
            logger.error(f"Ollama embedding failed: {e}")
            dim = self.get_dimension()
            return np.zeros((len(texts), dim), dtype=np.float32)

    async def embed(self, texts: list[str]) -> np.ndarray:
        """通过 ollama.AsyncClient 实现原生异步向量化。"""
        import ollama

        clean = self._sanitize_texts(texts)
        try:
            client = ollama.AsyncClient(host=self._host)
            result = await client.embed(model=self._model, input=clean)
            arr = np.array(result.embeddings, dtype=np.float32)
            # 防护 NaN —— 用零值替换
            if np.any(np.isnan(arr)):
                logger.warning("Ollama async embed produced NaN values — replacing with zeros")
                arr = np.nan_to_num(arr, nan=0.0)
            return arr
        except Exception as e:
            logger.error(f"Ollama async embedding failed: {e}")
            dim = self.get_dimension()
            return np.zeros((len(texts), dim), dtype=np.float32)

    def get_dimension(self) -> int:
        if self._dimension is None:
            self._dimension = self._detect_dimension()
        return self._dimension
