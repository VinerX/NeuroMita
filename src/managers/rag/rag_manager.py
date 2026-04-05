import logging
import math
import sqlite3
import numpy as np
from threading import Lock
import json
import struct
import random
import datetime
import time as _time
from typing import List, Dict, Any, Optional, Tuple

from managers.database_manager import DatabaseManager
from handlers.embedding_handler import EmbeddingModelHandler, QUERY_PREFIX
from handlers.embedding_presets import resolve_model_settings
from managers.rag.pipeline.retrievers.faiss_index import invalidate as _faiss_invalidate
from core.events import get_event_bus, Events
from main_logger import logger
from ui.task_worker import TaskWorker


from managers.rag.rag_utils import rag_clean_text, make_reindex_progress_logger, extract_keywords, keyword_score
from managers.settings_manager import SettingsManager


EMBED_EVENT_NAME = Events.RAG.GET_EMBEDDING
EMBEDS_EVENT_NAME = Events.RAG.GET_EMBEDDINGS

# --- Default configuration constants ---
DEFAULT_QUERY_WEIGHT_USER = 0.7
DEFAULT_QUERY_WEIGHT_TAIL = 0.3
DEFAULT_TAIL_EXP_DECAY = 0.6
DEFAULT_SEARCH_LIMIT = 5
DEFAULT_SEARCH_THRESHOLD = 0.4
DEFAULT_EXPANDED_QUERY_MAX_CHARS = 4000
DEFAULT_RECENT_TAIL_MAX_CHARS = 1200

class RAGManager:
    _fallback_handler: Optional[EmbeddingModelHandler] = None
    _fallback_lock: Lock = Lock()
    _fallback_failed: bool = False  # avoid retrying after permanent load failure

    @classmethod
    def _get_fallback_handler(cls) -> EmbeddingModelHandler:
        """
        Fallback handler создаём лениво и один раз на процесс.
        ВАЖНО: используем EmbeddingModelHandler.shared(), чтобы не грузить модель второй раз.
        """
        if cls._fallback_failed:
            raise RuntimeError("Embedding model unavailable (failed to load; restart required)")
        if cls._fallback_handler is None:
            with cls._fallback_lock:
                if cls._fallback_handler is None and not cls._fallback_failed:
                    try:
                        ms = resolve_model_settings()
                        cls._fallback_handler = EmbeddingModelHandler.shared(
                            model_name=ms["hf_name"],
                            query_prefix=ms["query_prefix"],
                        )
                    except Exception:
                        cls._fallback_failed = True
                        raise
        return cls._fallback_handler

    def __init__(self, character_id: str):
        self.character_id = character_id
        self.db = DatabaseManager()

        self.event_bus = get_event_bus()
        self._history_cols = self.db.get_table_columns("history")
        self._mem_cols = self.db.get_table_columns("memories")
        self._embed_failed_warned: bool = False  # warn once when embed model unavailable

    def _current_model_name(self) -> str:
        """Возвращает HF-имя текущей модели эмбеддингов (разрешает пресет)."""
        ms = resolve_model_settings()
        return ms["hf_name"]

    def _current_dimensions(self) -> int:
        ms = resolve_model_settings()
        return int(ms.get("dimensions") or 0)

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

            max_chars = int(SettingsManager.get("RAG_QUERY_TAIL_MAX_CHARS", DEFAULT_RECENT_TAIL_MAX_CHARS) or DEFAULT_RECENT_TAIL_MAX_CHARS)
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

    def _build_query_embedding(self, user_query: str, tail: int) -> Optional[np.ndarray]:
        """
        Два режима:
        - concat: как раньше (склейка хвоста + user_query -> один embedding)
        - weighted: отдельные embeddings + взвешенная сумма (лучше для коротких фраз игрока)
        """
        if not SettingsManager.get("RAG_VECTOR_SEARCH_ENABLED", True):
            return None
        mode = str(SettingsManager.get("RAG_QUERY_EMBED_MODE", "concat") or "concat").strip().lower()
        if mode not in ("concat", "weighted"):
            mode = "concat"

        if mode == "concat":
            qt = self._build_query_from_recent(user_query, tail=int(tail or 0))
            qt = rag_clean_text(qt)
            return self._l2_normalize(self._get_embedding(qt))

        # weighted
        w_user = float(SettingsManager.get("RAG_QUERY_WEIGHT_LAST_USER", DEFAULT_QUERY_WEIGHT_USER) or DEFAULT_QUERY_WEIGHT_USER)
        w_tail = float(SettingsManager.get("RAG_QUERY_WEIGHT_PREV_CONTEXT", DEFAULT_QUERY_WEIGHT_TAIL) or DEFAULT_QUERY_WEIGHT_TAIL)
        if w_user < 0.0:
            w_user = 0.0
        if w_tail < 0.0:
            w_tail = 0.0
        s = w_user + w_tail
        if s <= 0.0:
            w_user, w_tail = DEFAULT_QUERY_WEIGHT_USER, DEFAULT_QUERY_WEIGHT_TAIL
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
        decay = float(SettingsManager.get("RAG_QUERY_TAIL_EXP_DECAY", DEFAULT_TAIL_EXP_DECAY) or DEFAULT_TAIL_EXP_DECAY)
        if not (0.0 < decay < 1.0):
            decay = DEFAULT_TAIL_EXP_DECAY

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
        if len(out) > DEFAULT_EXPANDED_QUERY_MAX_CHARS:
            out = out[-DEFAULT_EXPANDED_QUERY_MAX_CHARS:]
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

    def _get_embedding(self, text: str, prefix: str = "", use_event_bus: bool = True) -> Optional[np.ndarray]:
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
        prefix: str = "",
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
                _eventbus_ok = False
                for i in range(0, len(cleaned), bs):
                    chunk = cleaned[i:i + bs]
                    results = self.event_bus.emit_and_wait(
                        EMBEDS_EVENT_NAME,
                        {"texts": chunk, "prefix": prefix, "batch_size": bs},
                    )
                    if not results:
                        # No subscribers — fall through to fallback handler
                        out.clear()
                        _eventbus_ok = False
                        break
                    vecs = results[0]
                    if not isinstance(vecs, list):
                        vecs = []
                    # выравниваем длину под входной chunk
                    if len(vecs) != len(chunk):
                        vecs = (vecs + [None] * len(chunk))[:len(chunk)]
                    out.extend(vecs)
                    _eventbus_ok = True
                if _eventbus_ok:
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

    # ------------------------------------------------------------------ #
    #  Sentence-level indexing helpers                                    #
    # ------------------------------------------------------------------ #

    @staticmethod
    def _split_sentences(text: str, min_len: int = 20) -> list[str]:
        """Split text into sentences on punctuation and newline boundaries."""
        import re
        text = str(text or "").strip()
        if not text:
            return []
        # Split on sentence-ending punctuation followed by whitespace, or on newlines
        parts = re.split(r'(?<=[.!?…])\s+|\n+', text)
        return [p.strip() for p in parts if len(p.strip()) >= min_len]

    def _index_sentences(
        self,
        conn,
        source_table: str,
        source_id: int,
        content: str,
        *,
        model: str,
        batch_size: int = 16,
        min_len: int = 20,
    ) -> int:
        """Split content into sentences, embed each, store in sentence_embeddings.

        Returns the number of sentences stored.
        """
        sentences = self._split_sentences(content, min_len=min_len)
        if not sentences:
            return 0

        vecs = self._get_embeddings(sentences, batch_size=batch_size)
        stored = 0
        for idx, (sent, vec) in enumerate(zip(sentences, vecs)):
            if vec is None:
                continue
            blob = self._array_to_blob(vec)
            try:
                conn.execute(
                    """INSERT OR REPLACE INTO sentence_embeddings
                       (source_table, source_id, character_id, model_name, sentence_idx, embedding, created_at)
                       VALUES (?, ?, ?, ?, ?, ?, datetime('now'))""",
                    (source_table, source_id, self.character_id, model, idx, blob),
                )
                stored += 1
            except Exception:
                pass
        return stored

    def _index_sentences_missing(self, cursor, conn, model: str, batch_size: int = 16) -> int:
        """Index sentence embeddings for rows that have whole-doc embeddings but no sentence embeddings yet."""
        min_len = int(SettingsManager.get("RAG_SENTENCE_MIN_LEN", 20) or 20)
        updated = 0

        # History rows with whole-doc embedding but no sentence embeddings for current model
        try:
            hist_where = "h.character_id=? AND h.content != '' AND h.content IS NOT NULL"
            if "is_deleted" in self._history_cols:
                hist_where += " AND h.is_deleted=0"
            cursor.execute(
                f"""SELECT h.id, h.content FROM history h
                    INNER JOIN embeddings e
                      ON e.source_table='history' AND e.source_id=h.id
                      AND e.character_id=h.character_id AND e.model_name=?
                    LEFT JOIN sentence_embeddings se
                      ON se.source_table='history' AND se.source_id=h.id
                      AND se.character_id=h.character_id AND se.model_name=?
                    WHERE {hist_where} AND se.id IS NULL""",
                (model, model, self.character_id),
            )
            hist_rows = cursor.fetchall() or []
        except Exception as e:
            logger.warning(f"RAGManager: sentence index query failed (history): {e}")
            hist_rows = []

        for row_id, content in hist_rows:
            try:
                n = self._index_sentences(conn, "history", row_id, str(content or ""),
                                          model=model, batch_size=batch_size, min_len=min_len)
                updated += n
            except Exception:
                pass
        if hist_rows:
            try:
                conn.commit()
            except Exception:
                pass

        # Memory rows with whole-doc embedding but no sentence embeddings for current model
        try:
            cursor.execute(
                """SELECT m.eternal_id, m.content FROM memories m
                   INNER JOIN embeddings e
                     ON e.source_table='memories' AND e.source_id=m.eternal_id
                     AND e.character_id=m.character_id AND e.model_name=?
                   LEFT JOIN sentence_embeddings se
                     ON se.source_table='memories' AND se.source_id=m.eternal_id
                     AND se.character_id=m.character_id AND se.model_name=?
                   WHERE m.character_id=? AND m.is_deleted=0 AND se.id IS NULL""",
                (model, model, self.character_id),
            )
            mem_rows = cursor.fetchall() or []
        except Exception as e:
            logger.warning(f"RAGManager: sentence index query failed (memories): {e}")
            mem_rows = []

        for eternal_id, content in mem_rows:
            try:
                n = self._index_sentences(conn, "memories", eternal_id, str(content or ""),
                                          model=model, batch_size=batch_size, min_len=min_len)
                updated += n
            except Exception:
                pass
        if mem_rows:
            try:
                conn.commit()
            except Exception:
                pass

        if updated:
            logger.info(f"RAGManager: indexed {updated} sentence embeddings (model={model})")
        return updated

    def index_graph_entity_embeddings(self) -> int:
        """Embed entity names that have no vector yet. Returns count embedded."""
        try:
            from managers.rag.graph.graph_store import GraphStore
            gs = GraphStore(self.db, self.character_id)
            entities = gs.get_entities_without_embeddings()
            if not entities:
                return 0
            model = self._current_model_name()
            names = [e["name"] for e in entities]
            vecs = self._get_embeddings(names)
            if not vecs:
                return 0
            count = 0
            for ent, vec in zip(entities, vecs):
                if vec is not None:
                    gs.store_entity_embedding(
                        ent["id"],
                        vec.astype(np.float32).tobytes(),
                        model_name=model,
                    )
                    count += 1
            if count:
                logger.info(f"RAGManager: embedded {count} graph entities (model={model})")
            return count
        except Exception as e:
            logger.warning(f"RAGManager: index_graph_entity_embeddings failed: {e}")
            return 0

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
        model = self._current_model_name()
        dims = self._current_dimensions() or (vector.shape[0] if vector is not None else 0)
        conn = None
        try:
            conn = self.db.get_connection()
            # Legacy BLOB column (backwards compat)
            conn.execute(
                "UPDATE memories SET embedding = ? WHERE character_id = ? AND eternal_id = ?",
                (blob, self.character_id, eternal_id)
            )
            # New embeddings table
            conn.execute(
                """INSERT OR REPLACE INTO embeddings
                   (source_table, source_id, character_id, model_name, dimensions, embedding, created_at)
                   VALUES ('memories', ?, ?, ?, ?, ?, datetime('now'))""",
                (eternal_id, self.character_id, model, dims, blob),
            )
            # Sentence-level indexing (optional)
            if SettingsManager.get("RAG_SENTENCE_LEVEL", False):
                min_len = int(SettingsManager.get("RAG_SENTENCE_MIN_LEN", 20) or 20)
                self._index_sentences(conn, "memories", eternal_id, text, model=model, min_len=min_len)
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
        model = self._current_model_name()
        dims = self._current_dimensions() or (vector.shape[0] if vector is not None else 0)
        conn = None
        try:
            conn = self.db.get_connection()
            # Legacy BLOB column (backwards compat)
            conn.execute(
                "UPDATE history SET embedding = ? WHERE id = ?",
                (blob, msg_id)
            )
            # New embeddings table
            conn.execute(
                """INSERT OR REPLACE INTO embeddings
                   (source_table, source_id, character_id, model_name, dimensions, embedding, created_at)
                   VALUES ('history', ?, ?, ?, ?, ?, datetime('now'))""",
                (msg_id, self.character_id, model, dims, blob),
            )
            # Sentence-level indexing (optional)
            if SettingsManager.get("RAG_SENTENCE_LEVEL", False):
                min_len = int(SettingsManager.get("RAG_SENTENCE_MIN_LEN", 20) or 20)
                self._index_sentences(conn, "history", msg_id, text, model=model, min_len=min_len)
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

    def search_relevant(self, query: str, limit: int = DEFAULT_SEARCH_LIMIT, threshold: float = DEFAULT_SEARCH_THRESHOLD) -> List[Dict[str, Any]]:
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
        _t_embed0 = _time.perf_counter()
        qs = qb.build(query)
        self._last_query_timing = {"embed_ms": (_time.perf_counter() - _t_embed0) * 1000, "rerank_ms": 0.0}

        # If no embedding AND no keywords AND no fts -> nothing to do
        if qs.query_vec is None and not qs.keywords and not cfg.use_fts:
            return []

        # --- choose retrievers (can depend on combiner mode) ---
        retrievers = []

        # vector recall (always useful if query_vec exists)
        if qs.query_vec is not None and cfg.vector_search_enabled:
            retrievers.append(VectorRetriever(rag=self, cfg=cfg))
        elif cfg.vector_search_enabled and qs.query_vec is None and not self._embed_failed_warned:
            self._embed_failed_warned = True
            logger.warning(
                "[RAG] Embedding model unavailable — falling back to FTS+keyword only. "
                "Vector search disabled for this session. "
                "Install torch/transformers or ensure the embedding model is loaded to restore full recall."
            )

        # keyword-only recall (embedding IS NULL candidates)
        # In two_stage we still allow it for fallback-to-union when vector set is empty.
        if cfg.kw_enabled and qs.keywords:
            retrievers.append(KeywordOnlyRetriever(rag=self, cfg=cfg))

        # FTS recall
        # In two_stage it is used mainly to add lex features to vector candidates (combiner decides).
        if cfg.use_fts:
            retrievers.append(FTSRetriever(rag=self, cfg=cfg))

        # Graph retriever (entity-relation triples from knowledge graph).
        if cfg.search_graph:
            try:
                from managers.rag.graph.graph_store import GraphStore
                gs = GraphStore(self.db, self.character_id)
                from managers.rag.pipeline.retrievers.graph import GraphRetriever
                retrievers.append(GraphRetriever(graph_store=gs, cfg=cfg))
            except Exception as e:
                logger.debug(f"[RAG][PIPE] GraphRetriever init failed (ignored): {e}", exc_info=True)

        # Fast path: vector_only mode -> don't even run other retrievers
        if cfg.combine_mode == "vector_only":
            retrievers = [r for r in retrievers if getattr(r, "name", "") == "vector"]

        buckets = {}
        for r in retrievers:
            try:
                buckets[r.name] = r.retrieve(qs)
            except Exception as e:
                logger.debug(f"[RAG][PIPE] retriever \'{r.name}\' failed (ignored): {e}", exc_info=True)
                buckets[r.name] = []

        # --- choose combiner ---
        mode = (cfg.combine_mode or "union").strip().lower()
        if cfg.use_rrf:
            from managers.rag.pipeline.combiner import RRFCombiner
            combiner = RRFCombiner(cfg=cfg)
        elif mode == "vector_only":
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
                logger.debug(f"[RAG][PIPE] enricher \'{enr.name}\' failed (ignored): {e}", exc_info=True)

        # --- final rerank ---
        reranker = LinearReranker(cfg=cfg)
        reranker.score_all(cands)

        cands.sort(key=lambda c: float(c.score or 0.0), reverse=True)

        # --- optional cross-encoder second pass ---
        if cfg.cross_encoder_enabled and cfg.cross_encoder_model:
            try:
                from managers.rag.pipeline.cross_encoder import CrossEncoderReranker
                ce = CrossEncoderReranker.get(cfg.cross_encoder_model)
                # Adaptive top_k: for large pools cover more than fixed top_k;
                # for small pools never score FEWER than configured top_k.
                # Formula: max(top_k, n*ratio), then hard-capped by ce_max_items.
                # Examples (top_k=75, ratio=0.4, max=150):
                #   pool=62   → max(75,25)=75  → min(62,75)=62   (all, unchanged)
                #   pool=300  → max(75,120)=120 → cap(150)→120   (no change)
                #   pool=1512 → max(75,604)=604 → cap(150)→150   (4× faster)
                effective_top_k = min(len(cands),
                                      max(cfg.cross_encoder_top_k,
                                          int(len(cands) * cfg.ce_top_k_ratio)))
                if cfg.ce_max_items > 0:
                    effective_top_k = min(effective_top_k, cfg.ce_max_items)
                _t_ce0 = _time.perf_counter()
                ce.rerank(qs.user_query, cands, top_k=effective_top_k,
                          alpha=cfg.cross_encoder_alpha,
                          early_exit_score=cfg.ce_early_exit_score)
                self._last_query_timing["rerank_ms"] = (_time.perf_counter() - _t_ce0) * 1000
                cands.sort(key=lambda c: float(c.score or 0.0), reverse=True)
            except Exception as _ce_err:
                logger.debug(f"[RAG][cross_encoder] skipped: {_ce_err}", exc_info=True)

        if cfg.detailed_logs:
            RagDebugLogger(rag=self, cfg=cfg).log(qs, buckets, cands)

        # Enforce graph_min_results: guarantee at least N graph candidates in output
        graph_min = int(cfg.graph_min_results or 0)
        if graph_min > 0 and cfg.search_graph:
            limit = int(cfg.limit)
            top = cands[:limit]
            graph_in_top = sum(1 for c in top if c.source == "graph")
            if graph_in_top < graph_min:
                needed = graph_min - graph_in_top
                extra = [c for c in cands[limit:] if c.source == "graph"][:needed]
                if extra:
                    top = top[:limit - len(extra)] + extra
                    logger.debug(
                        f"[RAG][graph_min] bumped {len(extra)} graph triple(s) into top "
                        f"(had {graph_in_top}/{graph_min} required): "
                        + ", ".join(f'"{c.content}"' for c in extra)
                    )
                else:
                    logger.debug(
                        f"[RAG][graph_min] wanted {graph_min} graph results but only "
                        f"{graph_in_top} available in total"
                    )
            else:
                logger.debug(f"[RAG][graph_min] {graph_in_top} graph result(s) in top — requirement met")
            cands_out = top
        else:
            cands_out = cands[: int(cfg.limit)]

        if cfg.detailed_logs:
            RagDebugLogger(rag=self, cfg=cfg).log_final_output(cands_out)

        # convert to old output format
        out: list[dict] = []
        for c in cands_out:
            out.append(c.to_public_dict())
        return out

    def index_all_missing(self, progress_callback=None) -> int:
        """
        Генерит embedding только для записей без embedding для текущей модели.
        Проверяет таблицу embeddings — если для данной модели нет записи, генерирует.
        Возвращает количество записей, где embedding реально записали (updated_count).
        """
        model = self._current_model_name()
        dims = self._current_dimensions()
        conn = self.db.get_connection()
        cursor = conn.cursor()

        try:
            # History: нет записи в embeddings для текущей модели
            hist_where = "h.character_id=? AND h.content != '' AND h.content IS NOT NULL"
            if "is_deleted" in self._history_cols:
                hist_where += " AND h.is_deleted=0"
            cursor.execute(
                f"""SELECT h.id, h.content FROM history h
                    LEFT JOIN embeddings e
                      ON e.source_table='history' AND e.source_id=h.id
                      AND e.character_id=h.character_id AND e.model_name=?
                    WHERE {hist_where} AND e.id IS NULL""",
                (model, self.character_id),
            )
            hist_rows = cursor.fetchall() or []

            # Memories: нет записи в embeddings для текущей модели
            cursor.execute(
                """SELECT m.eternal_id, m.content FROM memories m
                   LEFT JOIN embeddings e
                     ON e.source_table='memories' AND e.source_id=m.eternal_id
                     AND e.character_id=m.character_id AND e.model_name=?
                   WHERE m.character_id=? AND m.is_deleted=0 AND e.id IS NULL""",
                (model, self.character_id),
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
                extra_meta=f"model={model} | batch_size={batch_size} | hist={len(hist_rows)} | mem={len(mem_rows)}",
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
                        d = dims or (vec.shape[0] if vec is not None else 0)
                        cursor.execute("UPDATE history SET embedding = ? WHERE id = ?", (blob, row_id))
                        cursor.execute(
                            """INSERT OR REPLACE INTO embeddings
                               (source_table, source_id, character_id, model_name, dimensions, embedding, created_at)
                               VALUES ('history', ?, ?, ?, ?, ?, datetime('now'))""",
                            (row_id, self.character_id, model, d, blob),
                        )
                        updated_count += 1

                    processed += 1
                    if progress_callback:
                        try:
                            progress_callback(processed, total)
                        except TaskWorker.CancelledError:
                            raise
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
                        d = dims or (vec.shape[0] if vec is not None else 0)
                        cursor.execute(
                            "UPDATE memories SET embedding = ? WHERE character_id = ? AND eternal_id = ?",
                            (blob, self.character_id, eternal_id),
                        )
                        cursor.execute(
                            """INSERT OR REPLACE INTO embeddings
                               (source_table, source_id, character_id, model_name, dimensions, embedding, created_at)
                               VALUES ('memories', ?, ?, ?, ?, ?, datetime('now'))""",
                            (eternal_id, self.character_id, model, d, blob),
                        )
                        updated_count += 1

                    processed += 1
                    if progress_callback:
                        try:
                            progress_callback(processed, total)
                        except TaskWorker.CancelledError:
                            raise
                        except Exception:
                            pass
                    prog.tick(processed=processed, updated=updated_count, stage="memories")

                conn.commit()

            prog.done(processed=processed, updated=updated_count)

            # --- Sentence-level indexing pass (when RAG_SENTENCE_LEVEL=True) ---
            if SettingsManager.get("RAG_SENTENCE_LEVEL", False):
                updated_count += self._index_sentences_missing(cursor, conn, model, batch_size)

            # --- Graph entity embedding pass (when graph vector search enabled) ---
            if SettingsManager.get("RAG_GRAPH_VECTOR_SEARCH", False):
                self.index_graph_entity_embeddings()

            # Invalidate FAISS cache so next query rebuilds from fresh embeddings
            if updated_count > 0:
                _faiss_invalidate(self.character_id, model, "history")
                _faiss_invalidate(self.character_id, model, "memories")

            return updated_count

        except TaskWorker.CancelledError:
            raise
        except Exception as e:
            logger.error(f"Error during re-indexing: {e}", exc_info=True)
            return 0
        finally:
            try:
                if conn:
                    conn.close()
            except Exception:
                pass

    def index_all(self, progress_callback=None) -> int:
        """
        Полная переиндексация: пересоздаёт embedding для ВСЕХ записей текущей моделью.
        Возвращает количество записей, где embedding реально записали (updated_count).
        """
        model = self._current_model_name()
        dims = self._current_dimensions()
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
                extra_meta=f"model={model} | batch_size={batch_size} | hist={len(hist_rows)} | mem={len(mem_rows)}",
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
                        d = dims or (vec.shape[0] if vec is not None else 0)
                        cursor.execute("UPDATE history SET embedding = ? WHERE id = ?", (blob, row_id))
                        cursor.execute(
                            """INSERT OR REPLACE INTO embeddings
                               (source_table, source_id, character_id, model_name, dimensions, embedding, created_at)
                               VALUES ('history', ?, ?, ?, ?, ?, datetime('now'))""",
                            (row_id, self.character_id, model, d, blob),
                        )
                        updated_count += 1

                    processed += 1
                    if progress_callback:
                        try:
                            progress_callback(processed, total)
                        except TaskWorker.CancelledError:
                            raise
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
                        d = dims or (vec.shape[0] if vec is not None else 0)
                        cursor.execute(
                            "UPDATE memories SET embedding = ? WHERE character_id = ? AND eternal_id = ?",
                            (blob, self.character_id, eternal_id),
                        )
                        cursor.execute(
                            """INSERT OR REPLACE INTO embeddings
                               (source_table, source_id, character_id, model_name, dimensions, embedding, created_at)
                               VALUES ('memories', ?, ?, ?, ?, ?, datetime('now'))""",
                            (eternal_id, self.character_id, model, d, blob),
                        )
                        updated_count += 1

                    processed += 1
                    if progress_callback:
                        try:
                            progress_callback(processed, total)
                        except TaskWorker.CancelledError:
                            raise
                        except Exception:
                            pass
                    prog.tick(processed=processed, updated=updated_count, stage="memories")

                conn.commit()

            prog.done(processed=processed, updated=updated_count)
            return updated_count

        except TaskWorker.CancelledError:
            raise
        except Exception as e:
            logger.error(f"Error during full re-indexing: {e}", exc_info=True)
            return 0
        finally:
            try:
                if conn:
                    conn.close()
            except Exception:
                pass
