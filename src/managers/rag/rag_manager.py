import logging
import math
import re
import sqlite3
import numpy as np
from threading import Lock
import json
import struct
import random
import datetime
from typing import List, Dict, Any, Optional, Tuple

from managers.database_manager import DatabaseManager
from handlers.embedding_handler import EmbeddingModelHandler, QUERY_PREFIX
from core.events import get_event_bus, Events
from main_logger import logger


from managers.rag.rag_utils import rag_clean_text, make_reindex_progress_logger
from managers.settings_manager import SettingsManager



from managers.rag.rag_keyword_search import extract_keywords, keyword_score
from .stopwords.stopwords import STOPWORDS

def _resolve_event_name(fallback: str, *path: str) -> str:
    try:
        obj = Events
        for p in path:
            obj = getattr(obj, p)
        return obj
    except Exception:
        return fallback


EMBED_EVENT_NAME = Events.RAG.GET_EMBEDDING
EMBEDS_EVENT_NAME = Events.RAG.GET_EMBEDDINGS

class RAGManager:
    _fallback_handler: Optional[EmbeddingModelHandler] = None
    _fallback_lock: Lock = Lock()

    @classmethod
    def _get_fallback_handler(cls) -> EmbeddingModelHandler:
        """
        Fallback handler создаём лениво и один раз на процесс.
        ВАЖНО: используем EmbeddingModelHandler.shared(), чтобы не грузить модель второй раз.
        """
        if cls._fallback_handler is None:
            with cls._fallback_lock:
                if cls._fallback_handler is None:
                    cls._fallback_handler = EmbeddingModelHandler()
        return cls._fallback_handler

    def __init__(self, character_id: str):
        self.character_id = character_id
        self.db = DatabaseManager()

        self.event_bus = get_event_bus()
        self._history_cols = self.db.get_table_columns("history")
        self._mem_cols = self.db.get_table_columns("memories")

    def _get_bool_setting(self, key: str, default: bool) -> bool:
        try:
            v = SettingsManager.get(key, default)
            if isinstance(v, str):
                return v.strip().lower() in ("1", "true", "yes", "on")
            return bool(v)
        except Exception:
            return bool(default)

    def _get_float_setting(self, key: str, default: float) -> float:
        try:
            return float(SettingsManager.get(key, default))
        except Exception:
            return float(default)

    def _get_int_setting(self, key: str, default: int) -> int:
        try:
            return int(SettingsManager.get(key, default))
        except Exception:
            return int(default)

    def _json_loads_list(self, s) -> list[str]:
        if not s:
            return []
        if isinstance(s, list):
            return [str(x).strip() for x in s if str(x).strip()]
        if not isinstance(s, str):
            return []
        raw = s.strip()
        if not raw:
            return []
        try:
            parsed = json.loads(raw)
            if isinstance(parsed, list):
                return [str(x).strip() for x in parsed if str(x).strip()]
        except Exception:
            pass
        return [p.strip() for p in raw.split(",") if p.strip()]

    def _parse_dt(self, s: Optional[str]) -> Optional[datetime.datetime]:
        if not s:
            return None
        raw = str(s).strip()
        if not raw:
            return None
        fmts = ("%d.%m.%Y %H:%M:%S", "%d.%m.%Y_%H.%M", "%d.%m.%Y %H:%M")
        for f in fmts:
            try:
                return datetime.datetime.strptime(raw, f)
            except Exception:
                continue
        return None

    def _clip_text(self, s: Any, n: int) -> str:
        try:
            t = str(s or "")
        except Exception:
            return ""
        t = t.strip()
        if not t:
            return ""
        if n and len(t) > int(n):
            return t[: int(n)]
        return t

    def _l2_normalize(self, v: Optional[np.ndarray]) -> Optional[np.ndarray]:
        if v is None:
            return None
        try:
            n = float(np.linalg.norm(v))
            if not (n > 0.0):
                return v
            return (v / n).astype(np.float32, copy=False)
        except Exception:
            return v

    def _get_recent_active_contents(self, tail: int, role_filter: str = "user_only") -> list[str]:
        """
        Возвращает список контекстных текстов из активной history (самые последние -> более старые).
        role_filter:
          - "user_only"
          - "user_and_assistant"
          - "assistant_only"
        """
        out: list[str] = []
        tail_n = int(tail or 0)
        if tail_n <= 0:
            return out

        rf = str(role_filter or "user_only").strip().lower()
        if rf not in ("user_only", "user_and_assistant", "assistant_only"):
            rf = "user_only"

        conn = self.db.get_connection()
        try:
            cur = conn.cursor()
            where = "character_id=? AND is_active=1"
            params: list[Any] = [self.character_id]
            if "is_deleted" in self._history_cols:
                where += " AND is_deleted=0"

            cur.execute(
                f"""
                SELECT role, content
                FROM history
                WHERE {where}
                ORDER BY id DESC
                LIMIT ?
                """,
                tuple(params + [tail_n]),
            )
            rows = cur.fetchall() or []

            max_chars = int(SettingsManager.get("RAG_QUERY_TAIL_MAX_CHARS", 1200) or 1200)
            for role, content in rows:
                r = str(role or "").strip().lower()
                if rf == "user_only" and r != "user":
                    continue
                if rf == "assistant_only" and r != "assistant":
                    continue
                c = rag_clean_text(self._clip_text(content, max_chars))
                if c:
                    out.append(c)
        except Exception:
            pass
        finally:
            try:
                conn.close()
            except Exception:
                pass
        return out

    def _fts_build_match_query(self, text: str, *, max_terms: int, min_len: int) -> str:
        """
        Build a safe-ish FTS5 MATCH query:
          token1 OR token2 OR ...
        Tokens are double-quoted to avoid syntax errors on weird characters.
        """
        cleaned = rag_clean_text(str(text or ""))
        if not cleaned:
            return ""

        # Unicode-ish tokenization (ru/en/digits/_). Keep it simple and robust.
        tokens = re.findall(r"[0-9A-Za-zА-Яа-я_]+", cleaned.lower())
        out: List[str] = []
        seen = set()
        for t in tokens:
            t = t.strip().strip('"').strip("'")
            if len(t) < int(min_len):
                continue
            if t in STOPWORDS:
                continue
            if t in seen:
                continue
            seen.add(t)
            out.append(f"\"{t}\"")
            if len(out) >= int(max_terms):
                break
        return " OR ".join(out)

    def _normalize_bm25_to_01(self, ranks: List[float]) -> List[float]:
        """
        bm25() direction differs by build; we normalize *relative* within returned top-K:
          best rank (min) -> 1.0
          worst rank (max) -> 0.0
        """
        rr: List[float] = []
        for x in ranks or []:
            try:
                v = float(x)
                if np.isnan(v) or np.isinf(v):
                    v = 0.0
                rr.append(v)
            except Exception:
                rr.append(0.0)
        if not rr:
            return []
        mn = min(rr)
        mx = max(rr)
        if abs(mx - mn) < 1e-12:
            return [1.0 for _ in rr]
        out: List[float] = []
        for v in rr:
            s = 1.0 - ((v - mn) / (mx - mn))  # min -> 1, max -> 0
            if s < 0.0:
                s = 0.0
            if s > 1.0:
                s = 1.0
            out.append(float(s))
        return out

    def _fts_history_rows(
        self,
        cursor,
        *,
        match_q: str,
        top_k: int,
    ) -> List[Dict[str, Any]]:
        if not match_q:
            return []
        if not self.db.table_exists(cursor, "history_fts"):
            return []

        cols = ["h.id", "bm25(history_fts) AS rank", "h.role", "h.content", "h.timestamp"]
        if "embedding" in self._history_cols:
            cols.append("h.embedding")
        opt = []
        for c in ("speaker", "target", "participants"):
            if c in self._history_cols:
                opt.append(f"h.{c}")
        cols += opt

        where = "h.character_id=? AND h.is_active=0"
        params: List[Any] = [self.character_id]
        if "is_deleted" in self._history_cols:
            where += " AND h.is_deleted=0"

        try:
            cursor.execute(
                f"""
                SELECT {', '.join(cols)}
                FROM history_fts
                JOIN history h ON h.id = history_fts.rowid
                WHERE history_fts MATCH ? AND {where}
                ORDER BY rank
                LIMIT ?
                """,
                tuple([match_q] + params + [int(top_k)]),
            )
            rows = cursor.fetchall() or []
            keys = [c.split(" AS ")[-1].split(".")[-1] for c in cols]  # crude but stable here
            out = []
            for r in rows:
                rd = dict(zip(keys, r))
                out.append(rd)
            return out
        except Exception as e:
            logger.debug(f"[RAG][FTS] history query failed (ignored): {e}")
            return []

    def _fts_memory_rows(
        self,
        cursor,
        *,
        match_q: str,
        top_k: int,
        memory_mode: str,
    ) -> List[Dict[str, Any]]:
        if not match_q:
            return []
        if not self.db.table_exists(cursor, "memories_fts"):
            return []

        cols = ["m.eternal_id", "bm25(memories_fts) AS rank", "m.content", "m.type", "m.priority", "m.date_created", "m.participants"]
        if "embedding" in self._mem_cols:
            cols.append("m.embedding")
        if "is_forgotten" in self._mem_cols:
            cols.append("m.is_forgotten")

        where = "m.character_id=? AND m.is_deleted=0"
        params: List[Any] = [self.character_id]
        if "is_forgotten" in self._mem_cols:
            if memory_mode == "forgotten":
                where += " AND m.is_forgotten=1"
            elif memory_mode == "active":
                where += " AND m.is_forgotten=0"
            elif memory_mode == "all":
                pass

        try:
            cursor.execute(
                f"""
                SELECT {', '.join(cols)}
                FROM memories_fts
                JOIN memories m ON m.id = memories_fts.rowid
                WHERE memories_fts MATCH ? AND {where}
                ORDER BY rank
                LIMIT ?
                """,
                tuple([match_q] + params + [int(top_k)]),
            )
            rows = cursor.fetchall() or []
            keys = [c.split(" AS ")[-1].split(".")[-1] for c in cols]
            out = []
            for r in rows:
                rd = dict(zip(keys, r))
                out.append(rd)
            return out
        except Exception as e:
            logger.debug(f"[RAG][FTS] memories query failed (ignored): {e}")
            return []

    def _build_query_embedding(self, user_query: str, tail: int) -> Optional[np.ndarray]:
        """
        Два режима:
        - concat: как раньше (склейка хвоста + user_query -> один embedding)
        - weighted: отдельные embeddings + взвешенная сумма (лучше для коротких фраз игрока)
        """
        mode = str(SettingsManager.get("RAG_QUERY_EMBED_MODE", "concat") or "concat").strip().lower()
        if mode not in ("concat", "weighted"):
            mode = "concat"

        if mode == "concat":
            qt = self._build_query_from_recent(user_query, tail=int(tail or 0))
            qt = rag_clean_text(qt)
            return self._l2_normalize(self._get_embedding(qt))

        # weighted
        w_user = float(SettingsManager.get("RAG_QUERY_WEIGHT_LAST_USER", 0.7) or 0.7)
        w_tail = float(SettingsManager.get("RAG_QUERY_WEIGHT_PREV_CONTEXT", 0.3) or 0.3)
        if w_user < 0.0:
            w_user = 0.0
        if w_tail < 0.0:
            w_tail = 0.0
        s = w_user + w_tail
        if s <= 0.0:
            w_user, w_tail = 0.7, 0.3
            s = 1.0
        # нормализуем веса (чтобы было стабильно)
        w_user /= s
        w_tail /= s

        # 1) embedding текущего user_query
        uq = rag_clean_text(str(user_query or "").strip())
        e_user = self._get_embedding(uq) if uq else None
        if e_user is not None:
            e_user = self._l2_normalize(e_user)

        # 2) embeddings хвоста (по умолчанию user_only, чтобы длинный ассистент не забивал)
        role_filter = str(SettingsManager.get("RAG_QUERY_TAIL_ROLE_FILTER", "user_only") or "user_only")
        tail_texts = self._get_recent_active_contents(int(tail or 0), role_filter=role_filter)

        e_tail: list[np.ndarray] = []
        if tail_texts and w_tail > 0.0:
            vecs = self._get_embeddings(tail_texts)
            for v in vecs or []:
                if v is None:
                    continue
                vv = self._l2_normalize(v)
                if vv is not None:
                    e_tail.append(vv)

        if e_user is None and not e_tail:
            return None

        # распределение веса хвоста: экспоненциальный спад от самого свежего к старым
        decay = float(SettingsManager.get("RAG_QUERY_TAIL_EXP_DECAY", 0.6) or 0.6)
        if not (0.0 < decay < 1.0):
            decay = 0.6

        tail_weights: list[float] = []
        if e_tail:
            raw = [(decay ** i) for i in range(len(e_tail))]  # i=0 самый свежий
            denom = float(sum(raw)) if raw else 1.0
            tail_weights = [(w_tail * (r / denom)) for r in raw]

        # суммируем
        base_vec = e_user if e_user is not None else e_tail[0]
        q = np.zeros_like(base_vec, dtype=np.float32)
        if e_user is not None and w_user > 0.0:
            q += (w_user * e_user).astype(np.float32, copy=False)
        for v, w in zip(e_tail, tail_weights):
            if w > 0.0:
                q += (w * v).astype(np.float32, copy=False)

        return self._l2_normalize(q)

    def _build_query_from_recent(self, user_query: str, tail: int = 2) -> str:
        """
        Требование: query строится из последних 1-3 сообщений (user+assistant),
        чтобы ловить местоимения/контекст.
        Мы берём хвост активной истории + текущий запрос.
        """
        parts: list[str] = []
        uq = str(user_query or "").strip()

        conn = self.db.get_connection()
        try:
            cur = conn.cursor()
            where = "character_id=? AND is_active=1"
            params: list[Any] = [self.character_id]
            if "is_deleted" in self._history_cols:
                where += " AND is_deleted=0"

            cur.execute(
                f"""
                SELECT role, content
                FROM history
                WHERE {where}
                ORDER BY id DESC
                LIMIT ?
                """,
                tuple(params + [int(tail)]),
            )
            rows = cur.fetchall() or []
            # rows сейчас от новых к старым -> развернём в хронологию
            rows = list(reversed(rows))
            for role, content in rows:
                r = str(role or "").strip().lower()
                c = str(content or "").strip()
                if not c:
                    continue
                tag = "User" if r == "user" else ("Assistant" if r == "assistant" else "Other")
                parts.append(f"{tag}: {c}")
        except Exception:
            pass
        finally:
            try:
                conn.close()
            except Exception:
                pass

        if uq:
            parts.append(f"User: {uq}")

        # ограничим размер строки (на всякий случай)
        out = "\n".join(parts).strip()
        if len(out) > 4000:
            out = out[-4000:]
        return out or uq

    def _blob_to_array(self, blob) -> Optional[np.ndarray]:
        """Конвертирует BLOB из SQLite обратно в numpy array"""
        if not blob:
            return None
        # float32 занимает 4 байта.
        return np.frombuffer(blob, dtype=np.float32)

    def _array_to_blob(self, array: np.ndarray) -> bytes:
        """Конвертирует numpy array в байты для сохранения"""
        return array.astype(np.float32).tobytes()

    def _get_embedding(self, text: str, prefix: str = QUERY_PREFIX, use_event_bus: bool = True) -> Optional[np.ndarray]:
        """
        1) Пытаемся получить эмбеддинг через EventBus (EmbeddingController).
        2) Если не вышло — fallback на Singleton EmbeddingModelHandler().
        """
        if not text or not SettingsManager.get("RAG_ENABLED", False):
            return None

        # Очистка от тегов
        text = rag_clean_text(text)

        if use_event_bus:
            try:
                logger.debug(f"RAGManager: Запрашиваю embedding через EventBus: {EMBED_EVENT_NAME}")
                results = self.event_bus.emit_and_wait(EMBED_EVENT_NAME, {"text": text, "prefix": prefix})
                if results:
                    vec = results[0]
                    if vec is not None:
                        return vec
            except Exception as e:
                # Не валим RAG из-за EventBus — просто откатываемся на прямой вызов singleton
                logger.warning(f"RAGManager: EventBus embedding не сработал, fallback на singleton. Причина: {e}")

        try:
            return self._get_fallback_handler().get_embedding(text, prefix=prefix)
        except Exception as e:
            logger.error(f"RAGManager: ошибка singleton эмбеддинга: {e}", exc_info=True)
            return None

    def _get_embeddings(
        self,
        texts: List[str],
        prefix: str = QUERY_PREFIX,
        use_event_bus: bool = True,
        batch_size: Optional[int] = None,
    ) -> List[Optional[np.ndarray]]:
        """
        Массовое получение эмбеддингов:
        1) EventBus batch (rag.get_embeddings) — меньше overhead и lock'ов.
        2) Fallback на ленивый singleton EmbeddingModelHandler, если EventBus недоступен.
        """
        if not texts or not SettingsManager.get("RAG_ENABLED", False):
            return []

        cleaned: List[str] = []
        for t in texts:
            if not t:
                cleaned.append("")
            else:
                cleaned.append(rag_clean_text(str(t)))

        bs = int(batch_size or self._get_int_setting("RAG_EMBED_BATCH_SIZE", 16))
        if bs <= 0:
            bs = len(cleaned)

        out: List[Optional[np.ndarray]] = []

        if use_event_bus:
            try:
                for i in range(0, len(cleaned), bs):
                    chunk = cleaned[i:i + bs]
                    results = self.event_bus.emit_and_wait(
                        EMBEDS_EVENT_NAME,
                        {"texts": chunk, "prefix": prefix, "batch_size": bs},
                    )
                    vecs = results[0] if results else []
                    if not isinstance(vecs, list):
                        vecs = []
                    # выравниваем длину под входной chunk
                    if len(vecs) != len(chunk):
                        vecs = (vecs + [None] * len(chunk))[:len(chunk)]
                    out.extend(vecs)
                return out
            except Exception as e:
                logger.warning(
                    f"RAGManager: EventBus batch embedding не сработал, fallback на singleton. Причина: {e}"
                )
                out.clear()

        # Fallback: последовательно (но без повторной загрузки модели)
        try:
            handler = self._get_fallback_handler()
            # Используем batch API модели (быстрее и тоже без повторной загрузки)
            # batch_size уже нормализован в bs
            vecs = handler.get_embeddings(cleaned, prefix=prefix, batch_size=bs)
            if not isinstance(vecs, list):
                vecs = []
            if len(vecs) != len(cleaned):
                vecs = (vecs + [None] * len(cleaned))[:len(cleaned)]
            return vecs
        except Exception as e:
            logger.error(f"RAGManager: ошибка fallback batch эмбеддингов: {e}", exc_info=True)
            return [None] * len(cleaned)

    def update_memory_embedding(self, eternal_id: int, text: str):
        """Создает и сохраняет эмбеддинг для воспоминания (без падений, RAG опционален)."""
        try:
            vector = self._get_embedding(text)
        except Exception as e:
            logger.warning(f"RAGManager: embedding generation failed (memory) - ignored: {e}", exc_info=True)
            return

        if vector is None:
            return

        blob = self._array_to_blob(vector)
        conn = None
        try:
            conn = self.db.get_connection()
            conn.execute(
                "UPDATE memories SET embedding = ? WHERE character_id = ? AND eternal_id = ?",
                (blob, self.character_id, eternal_id)
            )
            conn.commit()
        except sqlite3.OperationalError as e:
            logger.warning(f"RAGManager: sqlite operational error while updating memory embedding (ignored): {e}")
        except Exception as e:
            logger.warning(f"RAGManager: failed to update memory embedding (ignored): {e}", exc_info=True)
        finally:
            try:
                if conn:
                    conn.close()
            except Exception:
                pass

    def update_history_embedding(self, msg_id: int, text: str):
        """Создает и сохраняет эмбеддинг для сообщения истории (без падений, RAG опционален)."""
        try:
            vector = self._get_embedding(text)
        except Exception as e:
            logger.warning(f"RAGManager: embedding generation failed (history) - ignored: {e}", exc_info=True)
            return

        if vector is None:
            return

        blob = self._array_to_blob(vector)
        conn = None
        try:
            conn = self.db.get_connection()
            conn.execute(
                "UPDATE history SET embedding = ? WHERE id = ?",
                (blob, msg_id)
            )
            conn.commit()
        except sqlite3.OperationalError as e:
            logger.warning(f"RAGManager: sqlite operational error while updating history embedding (ignored): {e}")
        except Exception as e:
            logger.warning(f"RAGManager: failed to update history embedding (ignored): {e}", exc_info=True)
        finally:
            try:
                if conn:
                    conn.close()
            except Exception:
                pass

    def search_relevant(self, query: str, limit: int = 5, threshold: float = 0.4) -> List[Dict[str, Any]]:
        """
        Pipeline-based RAG search with selectable combiner modes:
          - union (default)
          - vector_only
          - intersect (min N methods)
          - two_stage (vector recall, others only add features; can fallback to union)
        """
        if not SettingsManager.get("RAG_ENABLED", False):
            return []

        # lazy imports (avoid circular)
        from managers.rag.pipeline.config import RAGConfig
        from managers.rag.pipeline.query_builder import QueryBuilder
        from managers.rag.pipeline.retrievers.vector import VectorRetriever
        from managers.rag.pipeline.retrievers.keyword_only import KeywordOnlyRetriever
        from managers.rag.pipeline.retrievers.fts import FTSRetriever
        from managers.rag.pipeline.combiner import (
            UnionCombiner,
            VectorOnlyCombiner,
            IntersectCombiner,
            TwoStageCombiner,
        )
        from managers.rag.pipeline.enrichers.common import TimeEnricher, EntityEnricher, PriorityEnricher
        from managers.rag.pipeline.reranker import LinearReranker
        from managers.rag.pipeline.debug_logger import RagDebugLogger

        cfg = RAGConfig.from_settings(limit=limit, threshold=threshold)

        qb = QueryBuilder(rag=self, cfg=cfg)
        qs = qb.build(query)

        # If no embedding AND no keywords AND no fts -> nothing to do
        if qs.query_vec is None and not qs.keywords and not cfg.use_fts:
            return []

        # --- choose retrievers (can depend on combiner mode) ---
        retrievers = []

        # vector recall (always useful if query_vec exists)
        if qs.query_vec is not None:
            retrievers.append(VectorRetriever(rag=self, cfg=cfg))

        # keyword-only recall (embedding IS NULL candidates)
        # In two_stage we still allow it for fallback-to-union when vector set is empty.
        if cfg.kw_enabled and qs.keywords:
            retrievers.append(KeywordOnlyRetriever(rag=self, cfg=cfg))

        # FTS recall
        # In two_stage it is used mainly to add lex features to vector candidates (combiner decides).
        if cfg.use_fts:
            retrievers.append(FTSRetriever(rag=self, cfg=cfg))

        # Fast path: vector_only mode -> don't even run other retrievers
        if cfg.combine_mode == "vector_only":
            retrievers = [r for r in retrievers if getattr(r, "name", "") == "vector"]

        buckets = {}
        for r in retrievers:
            try:
                buckets[r.name] = r.retrieve(qs)
            except Exception as e:
                logger.debug(f"[RAG][PIPE] retriever '{r.name}' failed (ignored): {e}", exc_info=True)
                buckets[r.name] = []

        # --- choose combiner ---
        mode = (cfg.combine_mode or "union").strip().lower()
        if mode == "vector_only":
            combiner = VectorOnlyCombiner(cfg=cfg)
        elif mode in ("intersect", "intersect2", "intersect_n"):
            combiner = IntersectCombiner(
                cfg=cfg,
                min_methods=int(cfg.intersect_min_methods),
                require_vector=bool(cfg.intersect_require_vector),
                fallback_union=bool(cfg.intersect_fallback_union),
            )
        elif mode == "two_stage":
            combiner = TwoStageCombiner(cfg=cfg, fallback_union=bool(cfg.two_stage_fallback_union))
        else:
            combiner = UnionCombiner(cfg=cfg)

        cands = combiner.combine(buckets)

        if not cands:
            if cfg.detailed_logs:
                RagDebugLogger(rag=self, cfg=cfg).log(qs, buckets, cands)
            return []

        # --- enrich common features (time/entity/priority) ---
        enrichers = [
            TimeEnricher(rag=self, cfg=cfg),
            EntityEnricher(rag=self, cfg=cfg),
            PriorityEnricher(rag=self, cfg=cfg),
        ]
        for enr in enrichers:
            try:
                enr.enrich(qs, cands)
            except Exception as e:
                logger.debug(f"[RAG][PIPE] enricher '{enr.name}' failed (ignored): {e}", exc_info=True)

        # --- final rerank ---
        reranker = LinearReranker(cfg=cfg)
        reranker.score_all(cands)

        cands.sort(key=lambda c: float(c.score or 0.0), reverse=True)

        if cfg.detailed_logs:
            RagDebugLogger(rag=self, cfg=cfg).log(qs, buckets, cands)

        # convert to old output format
        out: list[dict] = []
        for c in cands[: int(cfg.limit)]:
            out.append(c.to_public_dict())
        return out

    def _sql_keyword_where(self, keywords: list[str], column: str = "content") -> tuple[str, list[str]]:
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

        kw_where, kw_params = self._sql_keyword_where(keywords, column="content")
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
            content = rag_clean_text(str(content_raw or ""))

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

        kw_where, kw_params = self._sql_keyword_where(keywords, column="content")
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
            content = rag_clean_text(str(content_raw or ""))

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

    def find_forgotten_histories(self, K1, K2, K4, cursor, decay_rate, entity_bonus_history, noise_max, now, query_vec,
                                 scored, threshold, *, keywords: list[str], KW_ENABLED: bool, kw_min_score: float, K5: float):
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
                    kw, _hits = keyword_score(keywords, rag_clean_text(str(rd.get("content") or "")))
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

    def find_forgotten_memories(self, K1, K2, K3, K4, cursor, decay_rate, entity_bonus_from_participants, memory_mode,
                                noise_max, now, prio_bonus, query_vec, scored, threshold,
                                *, keywords: list[str], KW_ENABLED: bool, kw_min_score: float, K5: float):
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
                    kw, _hits = keyword_score(keywords, rag_clean_text(str(content or "")))
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

    def index_all_missing(self, progress_callback=None) -> int:
        """
        Генерит embedding только для записей без embedding.
        Возвращает количество записей, где embedding реально записали (updated_count).
        """
        conn = self.db.get_connection()
        cursor = conn.cursor()

        try:
            # History: только пустые embedding
            hist_where = "character_id=? AND embedding IS NULL AND content != '' AND content IS NOT NULL"
            if "is_deleted" in self._history_cols:
                hist_where += " AND is_deleted=0"
            cursor.execute(
                f"SELECT id, content FROM history WHERE {hist_where}",
                (self.character_id,),
            )
            hist_rows = cursor.fetchall() or []

            # Memories: только пустые embedding
            mem_where = "character_id=? AND embedding IS NULL AND is_deleted=0"
            cursor.execute(
                f"SELECT eternal_id, content FROM memories WHERE {mem_where}",
                (self.character_id,),
            )
            mem_rows = cursor.fetchall() or []

            total = len(hist_rows) + len(mem_rows)
            if total == 0:
                return 0

            batch_size = self._get_int_setting("RAG_EMBED_BATCH_SIZE", 16)
            if batch_size <= 0:
                batch_size = 16

            processed = 0
            updated_count = 0

            prog = make_reindex_progress_logger(self,
                "index_all_missing",
                total,
                extra_meta=f"batch_size={batch_size} | hist={len(hist_rows)} | mem={len(mem_rows)}",
            )
            prog.start()

            # --- History ---
            for i in range(0, len(hist_rows), batch_size):
                chunk = hist_rows[i:i + batch_size]
                texts = [(c if isinstance(c, str) else "") for _, c in chunk]
                vecs = self._get_embeddings(texts, batch_size=batch_size)

                for (row_id, _), vec in zip(chunk, vecs):
                    if vec is not None:
                        blob = self._array_to_blob(vec)
                        cursor.execute("UPDATE history SET embedding = ? WHERE id = ?", (blob, row_id))
                        updated_count += 1

                    processed += 1
                    if progress_callback:
                        try:
                            progress_callback(processed, total)
                        except Exception:
                            pass
                    prog.tick(processed=processed, updated=updated_count, stage="history")

                conn.commit()

            # --- Memories ---
            for i in range(0, len(mem_rows), batch_size):
                chunk = mem_rows[i:i + batch_size]
                texts = [str(c or "") for _, c in chunk]
                vecs = self._get_embeddings(texts, batch_size=batch_size)

                for (eternal_id, _), vec in zip(chunk, vecs):
                    if vec is not None:
                        blob = self._array_to_blob(vec)
                        cursor.execute(
                            "UPDATE memories SET embedding = ? WHERE character_id = ? AND eternal_id = ?",
                            (blob, self.character_id, eternal_id),
                        )
                        updated_count += 1

                    processed += 1
                    if progress_callback:
                        try:
                            progress_callback(processed, total)
                        except Exception:
                            pass
                    prog.tick(processed=processed, updated=updated_count, stage="memories")

                conn.commit()

            prog.done(processed=processed, updated=updated_count)
            return updated_count

        except Exception as e:
            logger.error(f"Error during re-indexing: {e}", exc_info=True)
            return 0
        finally:
            try:
                conn.close()
            except Exception:
                pass

    def index_all(self, progress_callback=None) -> int:
        """
        Полная переиндексация: пересоздаёт embedding для ВСЕХ записей.
        Возвращает количество записей, где embedding реально записали (updated_count).
        """
        conn = self.db.get_connection()
        cursor = conn.cursor()

        try:
            # History: все записи с контентом
            hist_where = "character_id=? AND content != '' AND content IS NOT NULL"
            if "is_deleted" in self._history_cols:
                hist_where += " AND is_deleted=0"
            cursor.execute(
                f"SELECT id, content FROM history WHERE {hist_where}",
                (self.character_id,),
            )
            hist_rows = cursor.fetchall() or []

            # Memories: все не удалённые с контентом
            mem_where = "character_id=? AND is_deleted=0 AND content IS NOT NULL"
            cursor.execute(
                f"SELECT eternal_id, content FROM memories WHERE {mem_where}",
                (self.character_id,),
            )
            mem_rows = cursor.fetchall() or []

            total = len(hist_rows) + len(mem_rows)
            if total == 0:
                return 0

            batch_size = self._get_int_setting("RAG_EMBED_BATCH_SIZE", 16)
            if batch_size <= 0:
                batch_size = 16

            processed = 0
            updated_count = 0

            prog = make_reindex_progress_logger(
                self,
                "index_all",
                total,
                extra_meta=f"batch_size={batch_size} | hist={len(hist_rows)} | mem={len(mem_rows)}",
            )
            prog.start()

            # --- History ---
            for i in range(0, len(hist_rows), batch_size):
                chunk = hist_rows[i:i + batch_size]
                texts = [(c if isinstance(c, str) else "") for _, c in chunk]
                vecs = self._get_embeddings(texts, batch_size=batch_size)

                for (row_id, _), vec in zip(chunk, vecs):
                    if vec is not None:
                        blob = self._array_to_blob(vec)
                        cursor.execute("UPDATE history SET embedding = ? WHERE id = ?", (blob, row_id))
                        updated_count += 1

                    processed += 1
                    if progress_callback:
                        try:
                            progress_callback(processed, total)
                        except Exception:
                            pass
                    prog.tick(processed=processed, updated=updated_count, stage="history")

                conn.commit()

            # --- Memories ---
            for i in range(0, len(mem_rows), batch_size):
                chunk = mem_rows[i:i + batch_size]
                texts = [str(c or "") for _, c in chunk]
                vecs = self._get_embeddings(texts, batch_size=batch_size)

                for (eternal_id, _), vec in zip(chunk, vecs):
                    if vec is not None:
                        blob = self._array_to_blob(vec)
                        cursor.execute(
                            "UPDATE memories SET embedding = ? WHERE character_id = ? AND eternal_id = ?",
                            (blob, self.character_id, eternal_id),
                        )
                        updated_count += 1

                    processed += 1
                    if progress_callback:
                        try:
                            progress_callback(processed, total)
                        except Exception:
                            pass
                    prog.tick(processed=processed, updated=updated_count, stage="memories")

                conn.commit()

            prog.done(processed=processed, updated=updated_count)
            return updated_count

        except Exception as e:
            logger.error(f"Error during full re-indexing: {e}", exc_info=True)
            return 0
        finally:
            try:
                conn.close()
            except Exception:
                pass
    