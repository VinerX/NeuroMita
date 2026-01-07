from __future__ import annotations

import random
import numpy as np

from main_logger import logger
from managers.rag.rag_keyword_search import keyword_score


def find_forgotten_histories(
    self,
    K1, K2, K4,
    cursor,
    decay_rate,
    entity_bonus_history,
    noise_max,
    now,
    query_vec,
    scored,
    threshold,
    *,
    keywords: list[str],
    KW_ENABLED: bool,
    kw_min_score: float,
    K5: float,
):
    if query_vec is None:
        return
    try:
        base_cols = ["id", "role", "content", "embedding", "timestamp"]
        opt_cols = ["speaker", "target", "participants"]
        cols = base_cols + [c for c in opt_cols if c in self._history_cols]

        where = "character_id=? AND embedding IS NOT NULL AND is_active=0"
        if "is_deleted" in self._history_cols:
            where += " AND is_deleted=0"

        cursor.execute(
            f"SELECT {', '.join(cols)} FROM history WHERE {where}",
            (self.character_id,),
        )
        hist_rows = cursor.fetchall() or []
    except Exception as e:
        logger.warning(f"RAGManager: failed to read history for search: {e}", exc_info=True)
        hist_rows = []
    for row in hist_rows:
        rd = dict(zip(cols, row))
        blob = rd.get("embedding")
        vec = self._blob_to_array(blob)
        if vec is None:
            continue
        sim = float(np.dot(query_vec, vec))

        # keyword score (может протащить запись даже если sim < threshold)
        kw = 0.0
        if KW_ENABLED and keywords:
            try:
                kw, _hits = keyword_score(keywords, self.rag_clean_text(str(rd.get("content") or "")))
            except Exception:
                kw = 0.0

        if sim < float(threshold) and (not KW_ENABLED or kw < float(kw_min_score)):
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
        final = (sim * K1) + (tf * K2) + (eb * K4) + (kw * K5) + noise

        scored.append({
            "source": "history",
            "id": int(rd.get("id") or 0),
            "role": rd.get("role"),
            "content": rd.get("content"),
            "date": ts,
            "speaker": sp or None,
            "target": tg or None,
            "participants": parts,
            "score": float(final),
            "_dbg": {
                "sim": sim, "time": tf, "prio": 0.0, "entity": eb, "kw": kw, "lex": 0.0, "noise": noise,
                "final": final
            }
        })


def find_forgotten_memories(
    self,
    K1, K2, K3, K4,
    cursor,
    decay_rate,
    entity_bonus_from_participants,
    memory_mode,
    noise_max,
    now,
    prio_bonus,
    query_vec,
    scored,
    threshold,
    *,
    keywords: list[str],
    KW_ENABLED: bool,
    kw_min_score: float,
    K5: float,
):
    if query_vec is None:
        return
    try:
        mem_where = "character_id=? AND is_deleted=0 AND embedding IS NOT NULL"

        has_forgotten_col = ("is_forgotten" in self._mem_cols)
        if has_forgotten_col:
            if memory_mode == "forgotten":
                mem_where += " AND is_forgotten=1"
            elif memory_mode == "active":
                mem_where += " AND is_forgotten=0"
            elif memory_mode == "all":
                pass  # без фильтра

        # если колонка is_forgotten есть — выберем её, чтобы применить штраф
        select_cols = [
            "eternal_id", "content", "embedding", "type",
            "priority", "date_created", "participants",
        ]
        if has_forgotten_col:
            select_cols.append("is_forgotten")

        cursor.execute(
            f"SELECT {', '.join(select_cols)} FROM memories WHERE {mem_where}",
            (self.character_id,),
        )
        mem_rows = cursor.fetchall() or []
    except Exception as e:
        logger.warning(f"RAGManager: failed to read memories for search: {e}", exc_info=True)
        mem_rows = []
    for row in mem_rows:
        # распакуем безопасно (под разные схемы)
        if "is_forgotten" in self._mem_cols:
            eternal_id, content, blob, mtype, priority, date_created, participants, is_forgotten = row
            is_forgotten = int(is_forgotten or 0)
        else:
            eternal_id, content, blob, mtype, priority, date_created, participants = row
            is_forgotten = 0

        # Если колонки нет (старая БД), а режим "forgotten" — просто ничего не тащим (иначе пойдут дубли).
        if ("is_forgotten" not in self._mem_cols) and memory_mode == "forgotten":
            continue

        vec = self._blob_to_array(blob)
        if vec is None:
            continue
        sim = float(np.dot(query_vec, vec))

        kw = 0.0
        if KW_ENABLED and keywords:
            try:
                kw, _hits = keyword_score(keywords, self.rag_clean_text(str(content or "")))
            except Exception:
                kw = 0.0

        if sim < float(threshold) and (not KW_ENABLED or kw < float(kw_min_score)):
            continue

        ts = date_created
        dt = self._parse_dt(ts)
        if dt:
            days = max(0.0, (now - dt).total_seconds() / 86400.0)
            tf = 1.0 / (1.0 + (decay_rate * days))
        else:
            tf = 0.0

        pb = prio_bonus(priority)
        eb = entity_bonus_from_participants(self._json_loads_list(participants))
        noise = random.uniform(0.0, noise_max)
        final = (sim * K1) + (tf * K2) + (pb * K3) + (eb * K4) + (kw * K5) + noise

        scored.append({
            "source": "memory",
            "id": int(eternal_id or 0),
            "content": content,
            "type": mtype,
            "priority": priority,
            "date_created": date_created,
            "score": float(final),
            "_dbg": {
                "sim": sim, "time": tf, "prio": pb, "entity": eb, "kw": kw, "lex": 0.0, "noise": noise,
                "final": final
            }
        })
