from __future__ import annotations

from typing import TYPE_CHECKING

from .contract import ProtocolAdapter

if TYPE_CHECKING:
    from .responses.request import ResponsesPolicy


def adapter_for(dialect_id: str, *, provider_name: str = "", supports_stream_usage: bool = False,
                responses_policy: ResponsesPolicy | None = None) -> ProtocolAdapter:
    if dialect_id == "openai_chat_completions":
        from .chat_completions.adapter import ChatCompletionsAdapter

        return ChatCompletionsAdapter(provider_name=provider_name, supports_stream_usage=supports_stream_usage)
    if dialect_id == "openai_responses":
        from .responses.adapter import ResponsesAdapter

        return ResponsesAdapter(policy=responses_policy)
    raise ValueError(f"Unsupported wire dialect: {dialect_id}")
