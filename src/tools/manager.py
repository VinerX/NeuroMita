# src/tools/manager.py
from __future__ import annotations

import json
from typing import Dict, List, Any, Optional

from .calc import CalculatorTool
from .web_read import WebPageReaderTool
from .web_search import WebSearchTool
from .base import Tool

from tools.dialects.registry import ToolDialectRegistry


class ToolManager:
    def __init__(self):
        self._tools: Dict[str, Tool] = {}

        # Dialects registry (авто-дискавери из tools/dialects/*.py)
        self.dialects = ToolDialectRegistry(auto_discover=True)

        # Backward-compat aliases (можно убрать позже, когда везде будет "openai"/"gemini")
        self.dialects.add_alias("deepseek", "openai")
        self.dialects.add_alias("anthropic", "openai")

        self.register(CalculatorTool())
        self.register(WebSearchTool())
        self.register(WebPageReaderTool())

    # -------------------------------------------------
    #  Регистрация инструментов / базовая схема
    # -------------------------------------------------
    def register(self, tool: Tool):
        self._tools[tool.name] = tool

    def json_schema(self) -> List[dict]:
        """
        Ваш internal schema (OpenAI-style minimal):
        [{name, description, parameters}, …]
        """
        return [
            {
                "name": t.name,
                "description": t.description,
                "parameters": t.parameters
            }
            for t in self._tools.values()
        ]

    # -------------------------------------------------
    #  Dialects API
    # -------------------------------------------------
    def available_dialects(self) -> List[dict]:
        return self.dialects.list_meta()

    def get_tools_payload(self, dialect_id: str) -> Any:
        """
        Возвращает tools payload в конкретном диалекте.
        dialect_id: "openai", "gemini", ...
        """
        d = self.dialects.get(dialect_id)
        if not d:
            # Не хардкодим логику моделей здесь — только дефолт “без tools”
            return []
        return d.build_tools_payload(self.json_schema())

    def mk_tool_call_msg(self, dialect_id: str, name: str, args: dict, tool_call_id: Optional[str] = None) -> dict:
        d = self.dialects.get(dialect_id)
        if not d:
            raise ValueError(f"Unknown tools dialect: {dialect_id}")
        return d.mk_tool_call_msg(name=name, args=args or {}, tool_call_id=tool_call_id)

    def mk_tool_resp_msg(
        self,
        dialect_id: str,
        name: str,
        result: str | dict,
        tool_call_id: Optional[str] = None
    ) -> dict:
        d = self.dialects.get(dialect_id)
        if not d:
            raise ValueError(f"Unknown tools dialect: {dialect_id}")
        return d.mk_tool_resp_msg(name=name, result=result, tool_call_id=tool_call_id)

    # -------------------------------------------------
    #  Execution
    # -------------------------------------------------
    def run(self, name: str, arguments: dict):
        tool = self._tools.get(name)
        if not tool:
            return f"[Tool-Error] Неизвестный инструмент: {name}"

        try:
            return tool.run(**(arguments or {}))
        except Exception as e:
            return f"[Tool-Error] {name} вызвал исключение: {e}"

    def tools_prompt(self):
        return (
            "You can use the following tools by responding with a JSON object: {tools_json}. "
            "For example: {{ \"tool\": \"tool_name\", \"args\": {{ \"param\": \"value\" }} }}."
        )


# -------------------------------------------------
# Backward-compatible wrappers (чтобы не ломать существующие импорты)
# -------------------------------------------------
# Эти функции раньше принимали provider=("gemini"/"openai"/"deepseek") и генерировали сообщения.
# Теперь они используют реестр диалектов.

_DEFAULT_REGISTRY = ToolDialectRegistry(auto_discover=True)
_DEFAULT_REGISTRY.add_alias("deepseek", "openai")
_DEFAULT_REGISTRY.add_alias("anthropic", "openai")

def mk_tool_call_msg(name: str, args: dict, provider: str = "gemini", tool_call_id: str | None = None):
    dialect = provider  # provider == dialect_id (совместимость)
    d = _DEFAULT_REGISTRY.get(dialect)
    if not d:
        # fallback: как было раньше — gemini
        d = _DEFAULT_REGISTRY.get("gemini")
    return d.mk_tool_call_msg(name=name, args=args or {}, tool_call_id=tool_call_id)

def mk_tool_resp_msg(
    name: str,
    result: str | dict,
    provider: str = "gemini",
    tool_call_id: str | None = None
):
    dialect = provider
    d = _DEFAULT_REGISTRY.get(dialect)
    if not d:
        d = _DEFAULT_REGISTRY.get("gemini")
    return d.mk_tool_resp_msg(name=name, result=result, tool_call_id=tool_call_id)