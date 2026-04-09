# src/managers/tools/builtin/memory_search.py
"""
MemorySearchTool — позволяет Мите самостоятельно искать по воспоминаниям и истории.
Работает независимо от RAG_ENABLED (автоматический RAG и ручная тула — разные галки).
"""
from __future__ import annotations

import datetime
import re
from typing import Any, Dict, List, Optional

from managers.tools.base import Tool
from main_logger import logger


# ---------- date parsing --------------------------------------------------

_PATTERNS_RU = [
    (re.compile(r"(\d+)\s*дн[еёя]\s*назад", re.I), lambda m: -int(m.group(1))),
    (re.compile(r"(\d+)\s*недел[юьи]\s*назад", re.I), lambda m: -int(m.group(1)) * 7),
    (re.compile(r"(\d+)\s*месяц[еяов]*\s*назад", re.I), lambda m: -int(m.group(1)) * 30),
    (re.compile(r"неделю\s*назад", re.I), lambda m: -7),
    (re.compile(r"месяц\s*назад", re.I), lambda m: -30),
    (re.compile(r"вчера", re.I), lambda m: -1),
    (re.compile(r"сегодня", re.I), lambda m: 0),
    (re.compile(r"позавчера", re.I), lambda m: -2),
]

_PATTERNS_EN = [
    (re.compile(r"(\d+)\s*days?\s*ago", re.I), lambda m: -int(m.group(1))),
    (re.compile(r"(\d+)\s*weeks?\s*ago", re.I), lambda m: -int(m.group(1)) * 7),
    (re.compile(r"(\d+)\s*months?\s*ago", re.I), lambda m: -int(m.group(1)) * 30),
    (re.compile(r"week\s*ago", re.I), lambda m: -7),
    (re.compile(r"month\s*ago", re.I), lambda m: -30),
    (re.compile(r"yesterday", re.I), lambda m: -1),
    (re.compile(r"today", re.I), lambda m: 0),
    (re.compile(r"day\s*before\s*yesterday", re.I), lambda m: -2),
]


def _parse_date(s: str) -> Optional[datetime.datetime]:
    """
    Парсит строку даты:
    - Относительная: "7 дней назад", "week ago", "вчера", "yesterday"
    - ISO: "2024-01-15", "2024-01-15T10:00:00"
    - Формат игры: "15.01.2024"
    Возвращает datetime в начале дня (00:00:00) или None если не распознано.
    """
    if not s:
        return None
    s = s.strip()

    today = datetime.datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)

    for pat, delta_fn in _PATTERNS_RU + _PATTERNS_EN:
        m = pat.fullmatch(s) or pat.search(s)
        if m:
            try:
                delta = delta_fn(m)
                return today + datetime.timedelta(days=delta)
            except Exception:
                pass

    # ISO / custom formats
    for fmt in ("%Y-%m-%dT%H:%M:%S", "%Y-%m-%d", "%d.%m.%Y", "%d.%m.%Y_%H.%M"):
        try:
            return datetime.datetime.strptime(s, fmt)
        except ValueError:
            pass

    return None


def _extract_date_from_result(r: dict) -> Optional[datetime.datetime]:
    """Извлекает дату из результата RAG (memory или history)."""
    raw = r.get("date_created") or r.get("date") or ""
    if not raw:
        return None
    return _parse_date(str(raw))


# ---------- config override mapping ----------------------------------------

_SEARCH_TYPE_OVERRIDES: dict[str, dict] = {
    "fts": {
        "RAG_VECTOR_SEARCH_ENABLED": False,
        "RAG_USE_FTS": True,
        "RAG_KEYWORD_SEARCH": True,
    },
    "vector": {
        "RAG_USE_FTS": False,
        "RAG_KEYWORD_SEARCH": False,
        "RAG_VECTOR_SEARCH_ENABLED": True,
    },
    "hybrid": {
        "RAG_USE_FTS": True,
        "RAG_VECTOR_SEARCH_ENABLED": True,
        "RAG_KEYWORD_SEARCH": True,
    },
    "keyword": {
        "RAG_USE_FTS": False,
        "RAG_VECTOR_SEARCH_ENABLED": False,
        "RAG_KEYWORD_SEARCH": True,
    },
    "auto": {},
}

_SOURCE_OVERRIDES: dict[str, dict] = {
    "memories": {"RAG_SEARCH_HISTORY": False, "RAG_SEARCH_MEMORY": True},
    "history":  {"RAG_SEARCH_MEMORY": False,  "RAG_SEARCH_HISTORY": True},
    "both":     {},
}


# ---------- tool -----------------------------------------------------------

class MemorySearchTool(Tool):
    """
    Инструмент поиска по воспоминаниям и истории чата.
    Работает независимо от автоматического RAG.
    """

    name = "memory_search"

    def __init__(self, settings):
        self._settings = settings
        self._char_id: Optional[str] = None

    def set_char_id(self, char_id: str) -> None:
        self._char_id = char_id

    # -- dynamic description -----------------------------------------------

    @property
    def description(self) -> str:
        types = self._available_search_types()
        types_str = ", ".join(f'"{t}"' for t in types)
        return (
            f"Search through memories and chat history. "
            f"Use when asked about past events, dates, or specific topics. "
            f"Available search_type values: {types_str}. "
            f"'auto' uses current pipeline settings; "
            f"'fts' — full-text/morphological; "
            f"'vector' — semantic similarity; "
            f"'hybrid' — both fts+vector; "
            f"'keyword' — keyword matching. "
            f"Supports date filters: ISO dates (2024-01-15) or relative "
            f"('7 дней назад', '7 days ago', 'неделю назад', 'вчера', 'yesterday')."
        )

    @property
    def parameters(self) -> Dict[str, Any]:
        types = self._available_search_types()
        props: dict = {
            "query": {
                "type": "string",
                "description": "What to search for in memories and history.",
            },
            "search_type": {
                "type": "string",
                "enum": types,
                "description": (
                    "Search method. 'auto' = use current pipeline settings. "
                    "Choose 'vector' or 'hybrid' for semantic/topic search; "
                    "'fts' for exact words/morphology; 'keyword' as fallback."
                ),
            },
            "date_from": {
                "type": "string",
                "description": (
                    "Start of date range (inclusive). "
                    "ISO: '2024-01-15', or relative: '7 дней назад', 'week ago', 'вчера'."
                ),
            },
            "date_to": {
                "type": "string",
                "description": (
                    "End of date range (inclusive). "
                    "ISO: '2024-01-20', or relative: 'сегодня', 'today', 'yesterday'."
                ),
            },
            "limit": {
                "type": "integer",
                "description": "Maximum number of results to return. Default: 10.",
            },
            "source": {
                "type": "string",
                "enum": ["both", "memories", "history"],
                "description": (
                    "'both' = search memories and chat history (default). "
                    "'memories' = only saved memories. "
                    "'history' = only chat history."
                ),
            },
        }
        return {
            "type": "object",
            "properties": props,
            "required": ["query"],
        }

    # -- helpers -----------------------------------------------------------

    def _available_search_types(self) -> List[str]:
        """Возвращает типы поиска доступные по текущим настройкам."""
        types = ["auto"]
        has_fts = bool(self._settings.get("RAG_USE_FTS", True))
        has_vec = bool(self._settings.get("RAG_VECTOR_SEARCH_ENABLED", True))
        if has_fts:
            types.append("fts")
        if has_vec:
            types.append("vector")
        if has_fts and has_vec:
            types.append("hybrid")
        types.append("keyword")
        return types

    # -- execution ---------------------------------------------------------

    def run(self, query: str, search_type: str = "auto", date_from: str = None,
            date_to: str = None, limit: int = 10, source: str = "both", **_) -> str:

        if not self._char_id:
            return "[memory_search] Ошибка: не задан character_id."

        limit = max(1, min(int(limit or 10), 50))

        # Build config overrides
        overrides: dict = {}
        st = str(search_type or "auto").lower()
        overrides.update(_SEARCH_TYPE_OVERRIDES.get(st, {}))
        src = str(source or "both").lower()
        overrides.update(_SOURCE_OVERRIDES.get(src, {}))

        # Parse date filters
        dt_from = _parse_date(date_from) if date_from else None
        dt_to = _parse_date(date_to) if date_to else None
        # date_to is end of day
        if dt_to is not None:
            dt_to = dt_to.replace(hour=23, minute=59, second=59)

        # Request more results to account for date filtering
        fetch_limit = limit * 5 if (dt_from or dt_to) else limit

        try:
            from managers.rag.rag_manager import RAGManager
            rag = RAGManager(self._char_id)
            results: List[Dict] = rag.search_relevant(
                query,
                limit=fetch_limit,
                config_overrides=overrides,
            )
        except Exception as e:
            logger.error(f"[memory_search] RAG error: {e}", exc_info=True)
            return f"[memory_search] Ошибка поиска: {e}"

        if not results:
            date_hint = ""
            if dt_from or dt_to:
                date_hint = f" в указанном диапазоне дат"
            return f"Ничего не найдено по запросу «{query}»{date_hint}."

        # Strict date filtering
        if dt_from or dt_to:
            filtered = []
            for r in results:
                d = _extract_date_from_result(r)
                if d is None:
                    continue  # skip records without dates when filter is set
                if dt_from and d < dt_from:
                    continue
                if dt_to and d > dt_to:
                    continue
                filtered.append(r)
            results = filtered

        results = results[:limit]

        if not results:
            return f"Ничего не найдено по запросу «{query}» в указанном диапазоне дат."

        return self._format_results(results)

    @staticmethod
    def _format_results(results: List[Dict]) -> str:
        lines = [f"Found {len(results)} result(s):"]
        for i, r in enumerate(results, 1):
            src = r.get("source", "?")
            content = str(r.get("content", "")).strip()
            score = r.get("score", 0.0)

            if src == "memory":
                date = r.get("date_created", "")
                prio = r.get("priority", "")
                mtype = r.get("type", "")
                meta = ", ".join(filter(None, [mtype, f"prio={prio}" if prio else "", date]))
                lines.append(f"{i}. [memory] ({meta}) {content}  [score={score:.3f}]")
            elif src == "history":
                date = r.get("date", "")
                speaker = r.get("speaker", r.get("role", ""))
                lines.append(f"{i}. [history/{speaker}] ({date}) {content}  [score={score:.3f}]")
            elif src == "graph":
                subj = r.get("subject", "")
                pred = r.get("predicate", "")
                obj = r.get("object", "")
                lines.append(f"{i}. [graph] {subj} {pred} {obj}  [score={score:.3f}]")
            else:
                lines.append(f"{i}. [{src}] {content}  [score={score:.3f}]")

        return "\n".join(lines)
