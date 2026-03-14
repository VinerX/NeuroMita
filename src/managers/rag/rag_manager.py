import logging
import math
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
from ui.task_worker import TaskWorker


from managers.rag.rag_utils import rag_clean_text, make_reindex_progress_logger, extract_keywords, keyword_score
from managers.settings_manager import SettingsManager


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
                    cls._fallback_handler = EmbeddingModelHandler.shared()
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
                logger.debug(f"[RAG][PIPE] retriever \'{r.name}\' failed (ignored): {e}", exc_info=True)
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
                logger.debug(f"[RAG][PIPE] enricher \'{enr.name}\' failed (ignored): {e}", exc_info=True)

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

    def index_all_missing(self, progress_callback=None) -> int:
        """
        Генерит embedding только для записей без embedding.
        Возвращает количество записей, где embedding реально записали (updated_count).
        """
        conn = self.db.get_connection()
        cursor = conn.cursor()

        try:
            # History: только пустые embedding
            hist_where = "character_id=? AND embedding IS NULL AND content != \'\' AND content IS NOT NULL"
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
                        except TaskWorker.CancelledError:
                            raise  # Пробрасываем для прерывания
                        except Exception:
                            pass  # Другие исключения подавляем
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
                        except TaskWorker.CancelledError:
                            raise  # Пробрасываем для прерывания
                        except Exception:
                            pass  # Другие исключения подавляем
                    prog.tick(processed=processed, updated=updated_count, stage="memories")

                conn.commit()

            prog.done(processed=processed, updated=updated_count)
            return updated_count

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
        Полная переиндексация: пересоздаёт embedding для ВСЕХ записей.
        Возвращает количество записей, где embedding реально записали (updated_count).
        """
        conn = self.db.get_connection()
        cursor = conn.cursor()

        try:
            # History: все записи с контентом
            hist_where = "character_id=? AND content != \'\' AND content IS NOT NULL"
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
                        except TaskWorker.CancelledError:
                            raise  # Пробрасываем для прерывания
                        except Exception:
                            pass  # Другие исключения подавляем
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
                        except TaskWorker.CancelledError:
                            raise  # Пробрасываем для прерывания
                        except Exception:
                            pass  # Другие исключения подавляем
                    prog.tick(processed=processed, updated=updated_count, stage="memories")

                conn.commit()

            prog.done(processed=processed, updated=updated_count)
            return updated_count

        except Exception as e:
            logger.error(f"Error during full re-indexing: {e}", exc_info=True)
            return 0
        finally:
            try:
                if conn:
                    conn.close()
            except Exception:
                pass
