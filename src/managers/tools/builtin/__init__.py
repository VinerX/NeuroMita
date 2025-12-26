# src/managers/tools/builtin/__init__.py
from .calc import CalculatorTool
from .web_read import WebPageReaderTool
from .web_search import WebSearchTool

__all__ = ["CalculatorTool", "WebPageReaderTool", "WebSearchTool"]