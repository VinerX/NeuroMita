# src/tools/dialects/base.py
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional


class ToolDialect(ABC):
    """
    Описывает только “диалект инструментов”:
    - как выглядит payload tools в запросе
    - как выглядят сообщения tool call / tool response в истории
    """

    @property
    @abstractmethod
    def id(self) -> str: ...

    @property
    def title(self) -> str:
        return self.id

    @abstractmethod
    def build_tools_payload(self, tools_schema: List[dict]) -> Any:
        """
        Вернуть структуру tools-поля (list/dict), которую ожидает этот диалект.
        """

    @abstractmethod
    def mk_tool_call_msg(self, name: str, args: dict, tool_call_id: Optional[str] = None) -> Dict[str, Any]:
        """
        Сообщение, которое фиксирует вызов инструмента (assistant side).
        """

    @abstractmethod
    def mk_tool_resp_msg(
        self,
        name: str,
        result: str | dict,
        tool_call_id: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Сообщение, которое фиксирует результат инструмента (tool side).
        """