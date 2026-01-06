import logging
import re
import sqlite3
import numpy as np
from threading import Lock
import json
import struct
import random
import datetime
from typing import List, Dict, Any, Optional

from managers.database_manager import DatabaseManager
from handlers.embedding_handler import EmbeddingModelHandler, QUERY_PREFIX
from core.events import get_event_bus, Events
from main_logger import logger
from managers.settings_manager import SettingsManager
from utils.throttled_progress_logger import ThrottledProgressLogger
from managers.rag_keyword_search import extract_keywords, keyword_score


def _resolve_event_name(fallback: str, *path: str) -> str:
    try:
        obj = Events
        for p in path:
            obj = getattr(obj, p)
        return obj
    except Exception:
        return fallback


EMBED_EVENT_NAME = _resolve_event_name("rag.get_embedding", "RAG", "GET_EMBEDDING")
EMBEDS_EVENT_NAME = _resolve_event_name("rag.get_embeddings", "RAG", "GET_EMBEDDINGS")


class RAGManager:
    _fallback_handler: Optional[EmbeddingModelHandler] = None
    _fallback_lock: Lock = Lock()

    @classmethod
    def _get_fallback_handler(cls) -> EmbeddingModelHandler:
        """
        Fallback handler создаём лениво и один раз на процесс.
        EmbeddingModelHandler тяжёлый (грузит модель), нельзя инстанцировать на каждый вызов.
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
        self._history_cols = self._read_table_cols("history")
        self._mem_cols = self._read_table_cols("memories")

    def _get_bool_setting(self, key: str, default: bool) -> bool:
        try:
            v = SettingsManager.get(key, default)
            if isinstance(v, str):
                return v.strip().lower() in ("1", "true", "yes", "on")
            return bool(v)
        except Exception:
            return bool(default)

    def _read_table_cols(self, table: str) -> set[str]:
        conn = self.db.get_connection()
        try:
            cur = conn.cursor()
            cur.execute(f"PRAGMA table_info({table})")
            return set(r[1] for r in cur.fetchall() if r and len(r) > 1)
        except Exception:
            return set()
        finally:
            try:
                conn.close()
            except Exception:
                pass

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

    def _blob_to_array(self, blob) -> np.ndarray:
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
        text = self.rag_clean_text(text)

        if use_event_bus:
            try:
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
                cleaned.append(self.rag_clean_text(str(t)))

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
            for t in cleaned:
                out.append(handler.get_embedding(t, prefix=prefix) if t else None)
            return out
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
        Advanced RAG:
        - query embedding строим из хвоста активного контекста + текущего запроса
        - считаем финальный скор по формуле:
          Score = (Sim*K1) + (TimeFactor*K2) + (PriorityBonus*K3) + (EntityBonus*K4) + (KeywordScore*K5) + Noise
        - RAG правила:
          memories: is_deleted=0 AND is_forgotten=1
          history: s_deleted=0 AND is_active=0
        """
        # weights (SettingsManager)
        K1 = self._get_float_setting("RAG_WEIGHT_SIMILARITY", 1.0)
        K2 = self._get_float_setting("RAG_WEIGHT_TIME", 1.0)
        K3 = self._get_float_setting("RAG_WEIGHT_PRIORITY", 1.0)
        K4 = self._get_float_setting("RAG_WEIGHT_ENTITY", 0.5)
        decay_rate = self._get_float_setting("RAG_TIME_DECAY_RATE", 0.15)
        detailed_logs = self._get_bool_setting("RAG_DETAILED_LOGS", True)
        tail = int(SettingsManager.get("RAG_QUERY_TAIL_MESSAGES",2))

        # Keyword search (SettingsManager)
        KW_ENABLED = bool(SettingsManager.get("RAG_KEYWORD_SEARCH", False))
        K5 = self._get_float_setting("RAG_WEIGHT_KEYWORDS", 0.6)
        kw_max_terms = self._get_int_setting("RAG_KEYWORDS_MAX_TERMS", 8)
        kw_min_score = self._get_float_setting("RAG_KEYWORD_MIN_SCORE", 0.34)  # ~1/3 совпадений
        kw_sql_limit = self._get_int_setting("RAG_KEYWORD_SQL_LIMIT", 250)
        kw_min_len = self._get_int_setting("RAG_KEYWORDS_MIN_LEN", 3)

        memory_mode = str(SettingsManager.get("RAG_MEMORY_MODE", "forgotten") or "forgotten").strip().lower()

        noise_max = self._get_float_setting("RAG_NOISE_MAX", 0.05)

        query_text = self._build_query_from_recent(query, tail=tail)

        keywords: list[str] = []
        if KW_ENABLED:
            try:
                # ВАЖНО: приоритизируем keywords из текущего query (user input),
                # иначе их может "вытеснить" длинный контекст/summary в начале query_text.
                primary = self.rag_clean_text(str(query or ""))
                kw_primary = extract_keywords(primary, max_terms=kw_max_terms, min_len=kw_min_len)

                # добираем из контекста, но с конца (ближе к последним репликам)
                kw_ctx = extract_keywords(query_text, max_terms=kw_max_terms, min_len=kw_min_len, from_end=True)

                merged: list[str] = []
                seen = set()
                for k in (kw_primary + kw_ctx):
                    ks = str(k or "").strip().lower()
                    if not ks or ks in seen:
                        continue
                    merged.append(ks)
                    seen.add(ks)
                    if len(merged) >= int(kw_max_terms):
                        break

                keywords = merged
            except Exception:
                keywords = []

        query_text = self.rag_clean_text(query_text)
        query_vec = self._get_embedding(query_text)
        if query_vec is None:
            return []

        # Контекстные сущности (speaker/target/participants) берём из последнего активного сообщения
        ctx_speaker = ""
        ctx_target = ""
        ctx_participants: list[str] = []
        try:
            conn0 = self.db.get_connection()
            cur0 = conn0.cursor()
            where0 = "character_id=? AND is_active=1"
            params0: list[Any] = [self.character_id]
            if "is_deleted" in self._history_cols:
                where0 += " AND is_deleted=0"

            cols0 = ["speaker", "target", "participants", "sender"]
            cols0 = [c for c in cols0 if c in self._history_cols]
            if cols0:
                cur0.execute(
                    f"SELECT {', '.join(cols0)} FROM history WHERE {where0} ORDER BY id DESC LIMIT 1",
                    tuple(params0),
                )
                row0 = cur0.fetchone()
                if row0:
                    rd0 = dict(zip(cols0, row0))
                    ctx_speaker = str(rd0.get("speaker") or rd0.get("sender") or "").strip()
                    ctx_target = str(rd0.get("target") or "").strip()
                    ctx_participants = self._json_loads_list(rd0.get("participants"))
        except Exception:
            pass
        finally:
            try:
                conn0.close()
            except Exception:
                pass

        ctx_actors = set(x for x in [ctx_speaker, ctx_target, *ctx_participants] if x)

        conn = self.db.get_connection()
        cursor = conn.cursor()
        scored: list[dict] = []

        # Перенос инициализации now для использования в memories
        now = datetime.datetime.now()

        # У воспоминаний преимущество перед просто сообщениями
        def prio_bonus(p: str) -> float:
            pl = str(p or "Normal").strip().lower()
            if pl in ("critical", "high"):
                return 0.25
            if pl == "low":
                return 0
            return 0.1

        def entity_bonus_from_participants(parts: list[str]) -> float:
            if not ctx_actors or not parts:
                return 0.0
            overlap = ctx_actors.intersection(set(parts))
            return 0.1 if overlap else 0.0

        def entity_bonus_history(speaker: str, target: str, parts: list[str]) -> float:
            b = 0.0
            sp = str(speaker or "").strip()
            tg = str(target or "").strip()
            if sp and ctx_speaker and sp == ctx_speaker:
                b += 0.1
            if tg and ctx_target and tg == ctx_target:
                b += 0.1
            b += entity_bonus_from_participants(parts)
            return min(0.2, b)  # небольшой потолок

        # 1) Memories
        if bool(SettingsManager.get("RAG_SEARCH_MEMORY",False)):
            self.find_forgotten_memories(
                K1, K2, K3, K4, cursor, decay_rate, entity_bonus_from_participants, memory_mode,
                noise_max, now, prio_bonus, query_vec, scored, threshold,
                keywords=keywords, KW_ENABLED=KW_ENABLED, kw_min_score=kw_min_score, K5=K5,
            )

        # 1b) Memories keyword-only (embedding IS NULL)
        if KW_ENABLED and bool(SettingsManager.get("RAG_SEARCH_MEMORY", False)):
            self.find_keyword_memories_without_embedding(
                cursor=cursor,
                scored=scored,
                keywords=keywords,
                kw_min_score=kw_min_score,
                K2=K2, K3=K3, K4=K4, K5=K5,
                decay_rate=decay_rate,
                noise_max=noise_max,
                now=now,
                prio_bonus=prio_bonus,
                entity_bonus_from_participants=entity_bonus_from_participants,
                memory_mode=memory_mode,
                sql_limit=kw_sql_limit,
            )

        # 2) History
        if bool(SettingsManager.get("RAG_SEARCH_HISTORY",False)):
            self.find_forgotten_histories(
                K1, K2, K4, cursor, decay_rate, entity_bonus_history, noise_max, now, query_vec,
                scored, threshold,
                keywords=keywords, KW_ENABLED=KW_ENABLED, kw_min_score=kw_min_score, K5=K5,
            )

        # 2b) History keyword-only (embedding IS NULL)
        if KW_ENABLED and bool(SettingsManager.get("RAG_SEARCH_HISTORY", False)):
            self.find_keyword_histories_without_embedding(
                cursor=cursor,
                scored=scored,
                keywords=keywords,
                kw_min_score=kw_min_score,
                K2=K2, K4=K4, K5=K5,
                decay_rate=decay_rate,
                noise_max=noise_max,
                now=now,
                entity_bonus_history=entity_bonus_history,
                sql_limit=kw_sql_limit,
            )

        conn.close()

        # dedup: если запись попала и через embedding, и через keyword-only
        try:
            dedup: dict[tuple[str, int], dict] = {}
            for it in scored:
                try:
                    key = (str(it.get("source")), int(it.get("id") or 0))
                except Exception:
                    continue
                prev = dedup.get(key)
                if prev is None or float(it.get("score") or 0.0) > float(prev.get("score") or 0.0):
                    dedup[key] = it
            scored = list(dedup.values())
        except Exception as e:
            logging.warning(e)

        scored.sort(key=lambda x: float(x.get("score") or 0.0), reverse=True)

        # --- Detailed logging: Top 5 и Bottom 5
        try:
            if scored and detailed_logs:
                def _clip(s: Any, n: int = 200) -> str:
                    t = str(s or "").replace("\n", " ").strip()
                    return (t[:n] + "…") if len(t) > n else t

                sample_top = scored[:5]
                sample_bottom = scored[-5:] if len(scored) > 5 else []

                def _log_one(item: dict):
                    dbg = item.get("_dbg") or {}
                    src = item.get("source")
                    rid = item.get("id")
                    logger.info(
                        f"[RAG] {src}:{rid} | Base:{dbg.get('sim'):.3f} | Time:{dbg.get('time'):.3f} "
                        f"| Prio:{dbg.get('prio'):.3f} | Ent:{dbg.get('entity'):.3f} | KW:{float(dbg.get('kw') or 0.0):.3f} "
                        f"| Final:{dbg.get('final'):.3f} "
                        f"| Content:\"{self.rag_clean_text(_clip(item.get('content')))}\""
                    )

                logger.info("[RAG] ---- TOP 5 ----")
                for it in sample_top:
                    _log_one(it)
                if sample_bottom:
                    logger.info("[RAG] ---- BOTTOM 5 ----")
                    for it in sample_bottom:
                        _log_one(it)
        except Exception:
            pass

        # уберём dbg из результата наружу, чтобы не мусорить
        out = []
        for it in scored[: int(limit)]:
            it2 = dict(it)
            it2.pop("_dbg", None)
            out.append(it2)
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
                "_dbg": {"sim": 0.0, "time": tf, "prio": pb, "entity": eb, "kw": kw, "noise": noise, "final": final}
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
                    "sim": sim, "time": tf, "prio": 0.0, "entity": eb, "kw": kw, "noise": noise,
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
                    "sim": sim, "time": tf, "prio": pb, "entity": eb, "kw": kw, "noise": noise,
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

            prog = self._make_reindex_progress_logger(
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

            prog = self._make_reindex_progress_logger(
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
    def rag_clean_text(self, text: str) -> str:
        if not isinstance(text, str) or not text.strip():
            return ""

        t = text

        # 1) убрать memory-команды целиком (обычно с закрывающим </memory>)
        t = re.sub(r"<[+\-#]memory>.*?</memory>", " ", t, flags=re.S | re.I)

        # 2) убрать pose/числовые векторы (часто повторяющиеся)
        t = re.sub(r"<p>\s*[-0-9\.,\s]+\s*</p>", " ", t, flags=re.I)

        # 3) убрать сами теги, но оставить внутренний текст
        t = re.sub(r"</?[^>]+>", " ", t)

        # 4) схлопнуть пробелы
        t = re.sub(r"\s+", " ", t).strip()
        return t

    def _make_reindex_progress_logger(self, op: str, total: int, extra_meta: str = "") -> ThrottledProgressLogger:
        log_every = self._get_int_setting("RAG_REINDEX_LOG_EVERY", 50)
        log_interval = self._get_float_setting("RAG_REINDEX_LOG_INTERVAL_SEC", 5.0)
        if log_every <= 0:
            log_every = 50
        if log_interval <= 0:
            log_interval = 5.0

        meta = f"character_id={self.character_id}"
        if extra_meta:
            meta = f"{meta} | {extra_meta}"

        return ThrottledProgressLogger(
            info=logger.info,
            op=f"[RAG] {op}",
            total=int(total),
            meta=meta,
            log_every=int(log_every),
            log_interval_sec=float(log_interval),
        )