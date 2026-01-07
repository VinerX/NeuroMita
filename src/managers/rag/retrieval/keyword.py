from __future__ import annotations

import datetime
import random
from typing import Any

from main_logger import logger
from managers.rag.rag_keyword_search import keyword_score


def _sql_keyword_where(keywords: list[str], column: str = "content") -> tuple[str, list[str]]:
    kws = [k for k in (keywords or []) if isinstance(k, str) and k.strip()]
    if not kws:
        return "", []
    clauses = []
    params: list[str] = []
    for k in kws:
        clauses.append(f"{column} LIKE ?")
        params.append(f"%{k}%")
    return "(" + " OR ".join(clauses) + ")", params


def find_keyword_histories_without_embedding(
    self,
    *,
    cursor,
    scored: list[dict],
    keywords: list[str],
    kw_min_score: float,
    K2: float,
    K4: float,
    K5: float,
    decay_rate: float,
    noise_max: float,
    now: datetime.datetime,
    entity_bonus_history,
    sql_limit: int,
) -> None:
    if not keywords:
        return

    where = "character_id=? AND is_active=0 AND (embedding IS NULL) AND content IS NOT NULL AND TRIM(content) != ''"
    params: list[Any] = [self.character_id]
    if "is_deleted" in self._history_cols:
        where += " AND is_deleted=0"

    kw_where, kw_params = _sql_keyword_where(keywords, column="content")
    if not kw_where:
        return
    where = f"{where} AND {kw_where}"
    params.extend(kw_params)

    cols = ["id", "role", "content", "timestamp"]
    opt_cols = ["speaker", "target", "participants"]
    cols += [c for c in opt_cols if c in self._history_cols]

    try:
        cursor.execute(
            f"""
            SELECT {', '.join(cols)}
            FROM history
            WHERE {where}
            ORDER BY id DESC
            LIMIT ?
            """,
            tuple(params + [int(sql_limit)]),
        )
        rows = cursor.fetchall() or []
    except Exception as e:
        logger.warning(f"RAGManager: keyword-only history read failed: {e}", exc_info=True)
        return

    for row in rows:
        rd = dict(zip(cols, row))
        content_raw = rd.get("content")
        content = self.rag_clean_text(str(content_raw or ""))

        try:
            kw, _hits = keyword_score(keywords, content)
        except Exception:
            kw = 0.0

        if kw < float(kw_min_score):
            continue

        ts = rd.get("timestamp")
        dt = self._parse_dt(ts)
        if dt:
            days = max(0.0, (now - dt).total_seconds() / 86400.0)
            tf = 1.0 / (1.0 + (decay_rate * days))
        else:
            tf = 0.0

        sp = str(rd.get("speaker") or "").strip()
        tg = str(rd.get("target") or "").strip()
        parts = self._json_loads_list(rd.get("participants"))
        eb = entity_bonus_history(sp, tg, parts)

        noise = random.uniform(0.0, noise_max)
        final = (tf * K2) + (eb * K4) + (kw * K5) + noise

        scored.append({
            "source": "history",
            "id": int(rd.get("id") or 0),
            "role": rd.get("role"),
            "content": content_raw,
            "date": ts,
            "speaker": sp or None,
            "target": tg or None,
            "participants": parts,
            "score": float(final),
            "_dbg": {"sim": 0.0, "time": tf, "prio": 0.0, "entity": eb, "kw": kw, "noise": noise, "final": final}
        })


def find_keyword_memories_without_embedding(
    self,
    *,
    cursor,
    scored: list[dict],
    keywords: list[str],
    kw_min_score: float,
    K2: float,
    K3: float,
    K4: float,
    K5: float,
    decay_rate: float,
    noise_max: float,
    now: datetime.datetime,
    prio_bonus,
    entity_bonus_from_participants,
    memory_mode: str,
    sql_limit: int,
) -> None:
    if not keywords:
        return

    mem_where = "character_id=? AND is_deleted=0 AND (embedding IS NULL) AND content IS NOT NULL AND TRIM(content) != ''"
    params: list[Any] = [self.character_id]

    has_forgotten_col = ("is_forgotten" in self._mem_cols)
    if has_forgotten_col:
        if memory_mode == "forgotten":
            mem_where += " AND is_forgotten=1"
        elif memory_mode == "active":
            mem_where += " AND is_forgotten=0"

    kw_where, kw_params = _sql_keyword_where(keywords, column="content")
    if not kw_where:
        return
    mem_where = f"{mem_where} AND {kw_where}"
    params.extend(kw_params)

    cols = ["eternal_id", "content", "type", "priority", "date_created", "participants"]
    if has_forgotten_col:
        cols.append("is_forgotten")

    try:
        cursor.execute(
            f"""
            SELECT {', '.join(cols)}
            FROM memories
            WHERE {mem_where}
            ORDER BY eternal_id DESC
            LIMIT ?
            """,
            tuple(params + [int(sql_limit)]),
        )
        rows = cursor.fetchall() or []
    except Exception as e:
        logger.warning(f"RAGManager: keyword-only memories read failed: {e}", exc_info=True)
        return

    for row in rows:
        rd = dict(zip(cols, row))
        content_raw = rd.get("content")
        content = self.rag_clean_text(str(content_raw or ""))

        try:
            kw, _hits = keyword_score(keywords, content)
        except Exception:
            kw = 0.0

        if kw < float(kw_min_score):
            continue

        ts = rd.get("date_created")
        dt = self._parse_dt(ts)
        if dt:
            days = max(0.0, (now - dt).total_seconds() / 86400.0)
            tf = 1.0 / (1.0 + (decay_rate * days))
        else:
            tf = 0.0

        pb = prio_bonus(rd.get("priority"))
        eb = entity_bonus_from_participants(self._json_loads_list(rd.get("participants")))
        noise = random.uniform(0.0, noise_max)

        final = (tf * K2) + (pb * K3) + (eb * K4) + (kw * K5) + noise

        scored.append({
            "source": "memory",
            "id": int(rd.get("eternal_id") or 0),
            "content": content_raw,
            "type": rd.get("type"),
            "priority": rd.get("priority"),
            "date_created": rd.get("date_created"),
            "score": float(final),
            "_dbg": {"sim": 0.0, "time": tf, "prio": pb, "entity": eb, "kw": kw, "lex": 0.0, "noise": noise, "final": final}
        })
