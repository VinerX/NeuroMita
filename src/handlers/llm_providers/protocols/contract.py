from typing import Any, Iterable, Protocol

from ..base import LLMRequest, LLMResponse


class ProtocolAdapter(Protocol):
    dialect_id: str

    def encode(self, req: LLMRequest, *, wire_stream: bool) -> dict[str, Any]: ...

    def decode(self, req: LLMRequest, payload: dict[str, Any]) -> LLMResponse: ...

    def consume_stream(self, req: LLMRequest, chunks: Iterable[dict[str, Any]]) -> LLMResponse: ...
