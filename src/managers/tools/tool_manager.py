# src/managers/tools/tool_manager.py
from __future__ import annotations

from importlib import import_module
from typing import Any, Dict, List, Optional

from main_logger import logger
from managers.tools.base import Tool
from managers.tools.dialects.registry import ToolDialectRegistry


class _LazyTool(Tool):
    """Load an optional/heavy tool only when its schema or implementation is used."""

    def __init__(self, name: str, module_name: str, class_name: str) -> None:
        self._name = str(name)
        self._module_name = str(module_name)
        self._class_name = str(class_name)
        self._instance: Tool | None = None
        self._load_error: Exception | None = None
        self._pending_char_id = ""

    @property
    def name(self) -> str:
        return self._name

    def _load(self) -> Tool:
        if self._instance is not None:
            return self._instance
        if self._load_error is not None:
            raise RuntimeError(
                f"Tool {self._class_name} is unavailable: {self._load_error}"
            ) from self._load_error
        try:
            tool_type = getattr(import_module(self._module_name), self._class_name)
            instance = tool_type()
            if self._pending_char_id and hasattr(instance, "set_char_id"):
                instance.set_char_id(self._pending_char_id)
            self._instance = instance
            return instance
        except Exception as exc:
            self._load_error = exc
            logger.warning(f"Tool {self._class_name} unavailable: {exc}")
            raise

    @property
    def description(self) -> str:
        try:
            return str(self._load().description)
        except Exception:
            return f"Инструмент {self._name} недоступен в текущем окружении."

    @property
    def parameters(self) -> Dict[str, Any]:
        try:
            return dict(self._load().parameters or {})
        except Exception:
            return {}

    def set_char_id(self, char_id: str) -> None:
        self._pending_char_id = str(char_id or "")
        if self._instance is not None and hasattr(self._instance, "set_char_id"):
            self._instance.set_char_id(self._pending_char_id)

    def run(self, **kwargs) -> Any:
        return self._load().run(**kwargs)


class ToolManager:
    def __init__(self):
        self._tools: Dict[str, Tool] = {}

        self.dialects = ToolDialectRegistry(package="managers.tools.dialects", auto_discover=True)
        self.dialects.add_alias("deepseek", "openai")
        self.dialects.add_alias("anthropic", "openai")

        for name, module_name, class_name in (
            ("calculator", "managers.tools.builtin.calc", "CalculatorTool"),
            ("web_search", "managers.tools.builtin.web_search", "WebSearchTool"),
            ("google_search", "managers.tools.builtin.google_search", "GoogleSearchTool"),
            ("web_reader", "managers.tools.builtin.web_read", "WebPageReaderTool"),
        ):
            self.register(_LazyTool(name, module_name, class_name))

    def register(self, tool: Tool):
        self._tools[tool.name] = tool

    def json_schema(self) -> List[dict]:
        return [
            {
                "name": tool.name,
                "description": tool.description,
                "parameters": tool.parameters,
            }
            for tool in self._tools.values()
        ]

    def available_dialects(self) -> List[dict]:
        return self.dialects.list_meta()

    def _filtered_schema(self, enabled_names: Optional[List[str]]) -> List[dict]:
        """Return schema only for requested tools; disabled heavy tools stay unloaded."""
        if enabled_names is None:
            selected = self._tools.values()
        else:
            enabled = set(enabled_names)
            selected = (tool for name, tool in self._tools.items() if name in enabled)
        return [
            {
                "name": tool.name,
                "description": tool.description,
                "parameters": tool.parameters,
            }
            for tool in selected
        ]

    def get_tools_payload(self, dialect_id: str, enabled_names: Optional[List[str]] = None) -> Any:
        dialect = self.dialects.get(dialect_id)
        if not dialect:
            return []
        return dialect.build_tools_payload(self._filtered_schema(enabled_names))

    def mk_tool_call_msg(
        self,
        dialect_id: str,
        name: str,
        args: dict,
        tool_call_id: Optional[str] = None,
    ) -> dict:
        dialect = self.dialects.get(dialect_id)
        if not dialect:
            raise ValueError(f"Unknown tools dialect: {dialect_id}")
        return dialect.mk_tool_call_msg(
            name=name,
            args=args or {},
            tool_call_id=tool_call_id,
        )

    def mk_tool_resp_msg(
        self,
        dialect_id: str,
        name: str,
        result: str | dict,
        tool_call_id: Optional[str] = None,
    ) -> dict:
        dialect = self.dialects.get(dialect_id)
        if not dialect:
            raise ValueError(f"Unknown tools dialect: {dialect_id}")
        return dialect.mk_tool_resp_msg(
            name=name,
            result=result,
            tool_call_id=tool_call_id,
        )

    def set_char_context(self, char_id: str) -> None:
        """Inject character context without forcing lazy tools to import."""
        for tool in self._tools.values():
            setter = getattr(tool, "set_char_id", None)
            if callable(setter):
                setter(char_id)

    def run(self, name: str, arguments: dict):
        tool = self._tools.get(name)
        if not tool:
            return f"[Tool-Error] Неизвестный инструмент: {name}"
        try:
            return tool.run(**(arguments or {}))
        except Exception as exc:
            return f"[Tool-Error] {name} вызвал исключение: {exc}"

    def tools_prompt(self):
        return (
            "You can use the following tools by responding with a JSON object: {tools_json}. "
            "For example: {{ \"tool\": \"tool_name\", \"args\": {{ \"param\": \"value\" }} }}."
        )


# Backward-compatible wrappers (оставим пока)
_DEFAULT_REGISTRY = ToolDialectRegistry(package="managers.tools.dialects", auto_discover=True)
_DEFAULT_REGISTRY.add_alias("deepseek", "openai")
_DEFAULT_REGISTRY.add_alias("anthropic", "openai")


def mk_tool_call_msg(
    name: str,
    args: dict,
    provider: str = "gemini",
    tool_call_id: str | None = None,
):
    dialect = _DEFAULT_REGISTRY.get(provider) or _DEFAULT_REGISTRY.get("gemini")
    return dialect.mk_tool_call_msg(
        name=name,
        args=args or {},
        tool_call_id=tool_call_id,
    )


def mk_tool_resp_msg(
    name: str,
    result: str | dict,
    provider: str = "gemini",
    tool_call_id: str | None = None,
):
    dialect = _DEFAULT_REGISTRY.get(provider) or _DEFAULT_REGISTRY.get("gemini")
    return dialect.mk_tool_resp_msg(
        name=name,
        result=result,
        tool_call_id=tool_call_id,
    )
