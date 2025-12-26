# src/handlers/llm_providers/base.py
from dataclasses import dataclass, field
from typing import List, Dict, Callable, Optional, Any
from abc import ABC, abstractmethod

@dataclass
class LLMRequest:
    model: str
    messages: List[Dict]
    api_key: Optional[str] = None
    api_url: Optional[str] = None
    make_request: bool = False
    gemini_case: bool = False
    g4f_flag: bool = False
    g4f_model: Optional[str] = None
    stream: bool = False
    stream_cb: Optional[Callable[[str], None]] = None

    tools_on: bool = False
    tools_mode: str = "native"

    tools_payload: Optional[Any] = None
    tools_dialect: Optional[str] = None

    extra: Dict[str, Any] = field(default_factory=dict)
    settings: Optional[Any] = None
    pip_installer: Optional[Any] = None
    depth: int = 0
    tool_manager: Optional[Any] = None

class BaseProvider(ABC):
    name: str
    priority: int = 100

    supports_tools_native: bool = False
    supports_streaming: bool = True
    supports_streaming_with_tools: bool = False
    uses_custom_messages_handler: bool = False

    @abstractmethod
    def is_applicable(self, req: LLMRequest) -> bool:
        pass

    @abstractmethod
    def generate(self, req: LLMRequest) -> str:
        pass