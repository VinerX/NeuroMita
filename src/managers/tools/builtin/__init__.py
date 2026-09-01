from __future__ import annotations

from importlib import import_module

_LAZY_EXPORTS = {
    "CalculatorTool": ("managers.tools.builtin.calc", "CalculatorTool"),
    "GoogleSearchTool": ("managers.tools.builtin.google_search", "GoogleSearchTool"),
    "WebPageReaderTool": ("managers.tools.builtin.web_read", "WebPageReaderTool"),
    "WebSearchTool": ("managers.tools.builtin.web_search", "WebSearchTool"),
}


def __getattr__(name: str):
    target = _LAZY_EXPORTS.get(name)
    if target is None:
        raise AttributeError(name)
    module_name, attribute = target
    value = getattr(import_module(module_name), attribute)
    globals()[name] = value
    return value


__all__ = sorted(_LAZY_EXPORTS)
