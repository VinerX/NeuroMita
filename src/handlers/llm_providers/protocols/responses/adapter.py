from __future__ import annotations

from typing import Iterable

from ...base import LLMRequest, LLMResponse

from .request import ResponsesPolicy, encode_request
from .response import decode_response
from .stream import consume_response_stream


class ResponsesAdapter:
    dialect_id = 'openai_responses'

    def __init__(self, *, policy: ResponsesPolicy | None = None):
        self.policy = policy or ResponsesPolicy()

    def encode(self, req: LLMRequest, *, wire_stream: bool) -> dict:
        return encode_request(req, wire_stream=wire_stream, policy=self.policy)

    def decode(self, req: LLMRequest, payload: dict) -> LLMResponse:
        return decode_response(req, payload, namespace=self.policy.namespace)

    def consume_stream(self, req: LLMRequest, chunks: Iterable[dict]) -> LLMResponse:
        return consume_response_stream(req, chunks, namespace=self.policy.namespace)
