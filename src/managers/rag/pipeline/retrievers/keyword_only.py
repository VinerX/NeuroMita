from __future__ import annotations

from typing import Any, List

from managers.rag.rag_utils import rag_clean_text, keyword_score
from ..types import Candidate, QueryState
from ..config import RAGConfig


class KeywordOnlyRetriever:
    """
    Keyword recall for rows where embedding IS NULL.
    Mirrors your old:
      - find_keyword_memories_without_embedding
      - find_keyword_histories_without_embedding
    """
    name = "keyword_only"

    def __init__(self, *, rag: Any, cfg: RAGConfig):
        self.rag = rag
        self.cfg = cfg

    def retrieve(self, qs: QueryState) -> List[Candidate]:
        if not qs.keywords:
            return []

        out: list[Candidate] = []
        conn = self.rag.db.get_connection()
        try:
            cur = conn.cursor()
            if self.cfg.search_memory:
                out.extend(self._memories(cur, qs))
            if self.cfg.search_history:
                out.extend(self._histories(cur, qs))
        finally:
            try:
                conn.close()
            except Exception:
                pass
        return out

    _ALLOWED_COLUMNS = frozenset({"content"})

    def _sql_keyword_where(self, keywords: list[str], column: str = "content") -> tuple[str, list[str]]:
        if column not in self._ALLOWED_COLUMNS:
            raise ValueError(f"Invalid column for keyword search: {column!r}")
        kws = [k for k in (keywords or []) if isinstance(k, str) and k.strip()]
        if not kws:
            return "", []
        clauses = []
        params: list[str] = []
        for k in kws:
            clauses.append(f"{column} LIKE ?")
            params.append(f"%{k}%")
        return "(" + " OR ".join(clauses) + ")", params

    def _memories(self, cur, qs: QueryState) -> list[Candidate]:
        out: list[Candidate] = []

        has_forgotten_col = ("is_forgotten" in self.rag._mem_cols)
        if (not has_forgotten_col) and self.cfg.memory_mode == "forgotten":
            return out

        mem_where = "character_id=? AND is_deleted=0 AND (embedding IS NULL) AND content IS NOT NULL AND TRIM(content) != ''"
        params: list[Any] = [self.rag.character_id]

        if has_forgotten_col:
            if self.cfg.memory_mode == "forgotten":
                mem_where += " AND is_forgotten=1"
            elif self.cfg.memory_mode == "active":
                mem_where += " AND is_forgotten=0"

        kw_where, kw_params = self._sql_keyword_where(qs.keywords, column="content")
        if not kw_where:
            return out
        mem_where = f"{mem_where} AND {kw_where}"
        params.extend(kw_params)

        cols = ["eternal_id", "content", "type", "priority", "date_created", "participants"]
        if has_forgotten_col:
            cols.append("is_forgotten")

        try:
            cur.execute(
                f"""
                SELECT {', '.join(cols)}
                FROM memories
                WHERE {mem_where}
                ORDER BY eternal_id DESC
                LIMIT ?
                """,
                tuple(params + [int(self.cfg.kw_sql_limit)]),
            )
            rows = cur.fetchall() or []
        except Exception:
            return out

        for row in rows:
            rd = dict(zip(cols, row))
            mid = int(rd.get("eternal_id") or 0)
            if mid <= 0:
                continue

            content_raw = rd.get("content")
            content_clean = rag_clean_text(str(content_raw or ""))

            try:
                kw, _ = keyword_score(qs.keywords, content_clean)
            except Exception:
                kw = 0.0

            if kw < float(self.cfg.kw_min_score or 0.0):
                continue

            parts = self.rag._json_loads_list(rd.get("participants"))
            out.append(Candidate(
                source="memory",
                id=mid,
                content=content_raw,
                meta={
                    "type": rd.get("type"),
                    "priority": rd.get("priority"),
                    "date_created": rd.get("date_created"),
                    "participants": parts,
                },
                features={"sim": 0.0, "kw": float(kw), "lex": 0.0, "time": 0.0, "entity": 0.0, "prio": 0.0},
            ))

        return out

    def _histories(self, cur, qs: QueryState) -> list[Candidate]:
        out: list[Candidate] = []

        where = "character_id=? AND is_active=0 AND (embedding IS NULL) AND content IS NOT NULL AND TRIM(content) != ''"
        params: list[Any] = [self.rag.character_id]
        if "is_deleted" in self.rag._history_cols:
            where += " AND is_deleted=0"

        kw_where, kw_params = self._sql_keyword_where(qs.keywords, column="content")
        if not kw_where:
            return out
        where = f"{where} AND {kw_where}"
        params.extend(kw_params)

        cols = ["id", "role", "content", "timestamp"]
        for opt in ("speaker", "target", "participants"):
            if opt in self.rag._history_cols:
                cols.append(opt)

        try:
            cur.execute(
                f"""
                SELECT {', '.join(cols)}
                FROM history
                WHERE {where}
                ORDER BY id DESC
                LIMIT ?
                """,
                tuple(params + [int(self.cfg.kw_sql_limit)]),
            )
            rows = cur.fetchall() or []
        except Exception:
            return out

        for row in rows:
            rd = dict(zip(cols, row))
            hid = int(rd.get("id") or 0)
            if hid <= 0:
                continue

            content_raw = rd.get("content")
            content_clean = rag_clean_text(str(content_raw or ""))

            try:
                kw, _ = keyword_score(qs.keywords, content_clean)
            except Exception:
                kw = 0.0

            if kw < float(self.cfg.kw_min_score or 0.0):
                continue

            parts = self.rag._json_loads_list(rd.get("participants"))
            out.append(Candidate(
                source="history",
                id=hid,
                content=content_raw,
                meta={
                    "role": rd.get("role"),
                    "date": rd.get("timestamp"),
                    "speaker": str(rd.get("speaker") or "").strip() or None,
                    "target": str(rd.get("target") or "").strip() or None,
                    "participants": parts,
                },
                features={"sim": 0.0, "kw": float(kw), "lex": 0.0, "time": 0.0, "entity": 0.0, "prio": 0.0},
            ))

        return out
