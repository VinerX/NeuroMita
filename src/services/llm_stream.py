from __future__ import annotations

import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Optional


class LLMStreamEventType(str, Enum):
    STARTED = "started"
    TEXT_DELTA = "text_delta"
    REASONING_DELTA = "reasoning_delta"
    TOOL_CALL_STARTED = "tool_call_started"
    TOOL_CALL_DELTA = "tool_call_delta"
    TOOL_CALL_COMPLETED = "tool_call_completed"
    USAGE = "usage"
    COMPLETED = "completed"
    FAILED = "failed"


@dataclass(frozen=True)
class LLMStreamEvent:
    type: LLMStreamEventType
    request_id: str
    provider: str
    model: str
    sequence: int
    timestamp: float = field(default_factory=time.time)
    text: str = ""
    tool_call_id: str = ""
    tool_name: str = ""
    usage: Optional[Any] = None
    finish_reason: Optional[str] = None
    retryable: bool = False
    error_code: Optional[str] = None
    raw_provider_code: Optional[str] = None
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def terminal(self) -> bool:
        return self.type in {LLMStreamEventType.COMPLETED, LLMStreamEventType.FAILED}


__all__ = ["LLMStreamEvent", "LLMStreamEventType"]
