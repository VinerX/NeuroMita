# src/managers/tools/tool_manager.py
from __future__ import annotations

from typing import Dict, List, Any, Optional

from managers.tools.base import Tool
from managers.tools.builtin import CalculatorTool, WebSearchTool, WebPageReaderTool, GoogleSearchTool
from managers.tools.dialects.registry import ToolDialectRegistry


class ToolManager:
    def __init__(self):
        self._tools: Dict[str, Tool] = {}

        self.dialects = ToolDialectRegistry(package="managers.tools.dialects", auto_discover=True)
        self.dialects.add_alias("deepseek", "openai")
        self.dialects.add_alias("anthropic", "openai")

        self.register(CalculatorTool())
        self.register(WebSearchTool())
        self.register(GoogleSearchTool())
        self.register(WebPageReaderTool())

    def register(self, tool: Tool):
        self._tools[tool.name] = tool

    def json_schema(self) -> List[dict]:
        return [{"name": t.name, "description": t.description, "parameters": t.parameters} for t in self._tools.values()]

    def available_dialects(self) -> List[dict]:
        return self.dialects.list_meta()

    def _filtered_schema(self, enabled_names: Optional[List[str]]) -> List[dict]:
        """Return json_schema filtered to enabled_names. None = all tools, [] = no tools."""
        if enabled_names is None:
            return self.json_schema()
        return [s for s in self.json_schema() if s["name"] in enabled_names]

    def get_tools_payload(self, dialect_id: str, enabled_names: Optional[List[str]] = None) -> Any:
        d = self.dialects.get(dialect_id)
        if not d:
            return []
        return d.build_tools_payload(self._filtered_schema(enabled_names))

    def mk_tool_call_msg(self, dialect_id: str, name: str, args: dict, tool_call_id: Optional[str] = None) -> dict:
        d = self.dialects.get(dialect_id)
        if not d:
            raise ValueError(f"Unknown tools dialect: {dialect_id}")
        return d.mk_tool_call_msg(name=name, args=args or {}, tool_call_id=tool_call_id)

    def mk_tool_resp_msg(
        self, dialect_id: str, name: str, result: str | dict, tool_call_id: Optional[str] = None
    ) -> dict:
        d = self.dialects.get(dialect_id)
        if not d:
            raise ValueError(f"Unknown tools dialect: {dialect_id}")
        return d.mk_tool_resp_msg(name=name, result=result, tool_call_id=tool_call_id)

    def set_char_context(self, char_id: str) -> None:
        """Inject character context into tools that need it (e.g. memory_search)."""
        for tool in self._tools.values():
            if hasattr(tool, "set_char_id"):
                tool.set_char_id(char_id)

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


# Backward-compatible wrappers (оставим пока)
_DEFAULT_REGISTRY = ToolDialectRegistry(package="managers.tools.dialects", auto_discover=True)
_DEFAULT_REGISTRY.add_alias("deepseek", "openai")
_DEFAULT_REGISTRY.add_alias("anthropic", "openai")

def mk_tool_call_msg(name: str, args: dict, provider: str = "gemini", tool_call_id: str | None = None):
    d = _DEFAULT_REGISTRY.get(provider) or _DEFAULT_REGISTRY.get("gemini")
    return d.mk_tool_call_msg(name=name, args=args or {}, tool_call_id=tool_call_id)

def mk_tool_resp_msg(name: str, result: str | dict, provider: str = "gemini", tool_call_id: str | None = None):
    d = _DEFAULT_REGISTRY.get(provider) or _DEFAULT_REGISTRY.get("gemini")
    return d.mk_tool_resp_msg(name=name, result=result, tool_call_id=tool_call_id)