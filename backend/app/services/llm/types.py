"""
LLM 提供商类型
==================
多提供商 LLM 抽象层共享的数据类。
"""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class LLMResult:
    """LLM 调用结果，可包含思考文本。"""
    content: str
    thinking: str = ""


@dataclass
class LLMImagePart:
    """LLM 消息中的图片附件。"""
    data: bytes
    mime_type: str = "image/png"


@dataclass
class LLMMessage:
    """对话中的单条消息。"""
    role: str  # "system" | "user" | "assistant"
    content: str = ""
    images: list[LLMImagePart] = field(default_factory=list)
    # 提供商特有的不透明内容（例如带 thought_signature 的 Gemini Content）。
    # 设置后，提供商应直接使用该字段，而不是从 content/images 重新构建。
    _raw_provider_content: object | None = field(default=None, repr=False)


@dataclass
class StreamChunk:
    """流式 LLM 输出的单个分块。"""
    type: str  # "text" | "thinking" | "function_call"
    text: str = ""
    function_call: dict | None = None  # {"name": str, "args": dict}
