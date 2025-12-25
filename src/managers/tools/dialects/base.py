# src/managers/tools/dialects/base.py
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional


class ToolDialect(ABC):
    @property
    @abstractmethod
    def id(self) -> str: ...

    @property
    def title(self) -> str:
        return self.id

    @abstractmethod
    def build_tools_payload(self, tools_schema: List[dict]) -> Any:
        pass

    @abstractmethod
    def mk_tool_call_msg(self, name: str, args: dict, tool_call_id: Optional[str] = None) -> Dict[str, Any]:
        pass

    @abstractmethod
    def mk_tool_resp_msg(
        self,
        name: str,
        result: str | dict,
        tool_call_id: Optional[str] = None
    ) -> Dict[str, Any]:
        pass