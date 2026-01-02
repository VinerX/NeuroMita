import re
import sqlite3
import numpy as np
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


def _resolve_event_name(fallback: str, *path: str) -> str:
    try:
        obj = Events
        for p in path:
            obj = getattr(obj, p)
        return obj
    except Exception:
        return fallback


EMBED_EVENT_NAME = _resolve_event_name("rag.get_embedding", "RAG", "GET_EMBEDDING")


class RAGManager:
    def __init__(self, character_id: str):
        self.character_id = character_id
        self.db = DatabaseManager()

        # Важно: больше НЕ создаём EmbeddingModelHandler в __init__.
        # Доступ к эмбеддингам — через EventBus (предпочтительно) с fallback на Singleton.
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
        if not text:
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
            return EmbeddingModelHandler().get_embedding(text, prefix=prefix)
        except Exception as e:
            logger.error(f"RAGManager: ошибка singleton эмбеддинга: {e}", exc_info=True)
            return None

    def update_memory_embedding(self, eternal_id: int, text: str):
        """Создает и сохраняет эмбеддинг для воспоминания (без падений, RAG опционален)."""
        try:
            vector = self._get_embedding(text, use_event_bus=True)
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
            vector = self._get_embedding(text, use_event_bus=True)
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
          Score = (Sim*K1) + (TimeFactor*K2) + (PriorityBonus*K3) + (EntityBonus*K4) + Noise
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

        include_forgotten = self._get_bool_setting("RAG_INCLUDE_FORGOTTEN", False)
        forgotten_penalty = self._get_float_setting("RAG_FORGOTTEN_PENALTY", -0.15)  # отрицательный = реже всплывает

        # Как искать воспоминания:
        # - "forgotten" (по умолчанию): только is_forgotten=1 (чтобы не дублировать активную память в промпте)
        # - "active": только is_forgotten=0
        # - "all": и те, и те (может давать дубли)
        memory_mode = str(SettingsManager.get("RAG_MEMORY_MODE", "forgotten") or "forgotten").strip().lower()

        noise_max = self._get_float_setting("RAG_NOISE_MAX", 0.05)

        query_text = self._build_query_from_recent(query, tail=2)
        query_vec = self._get_embedding(query_text, use_event_bus=True)
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

        def prio_bonus(p: str) -> float:
            pl = str(p or "Normal").strip().lower()
            if pl in ("critical", "high"):
                return 0.2
            if pl == "low":
                return -0.1
            return 0.0

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
        # ТВОЯ ЗАДУМКА: активные memories уже в промпте, поэтому RAG по умолчанию ищет только забытые.
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
            if sim < float(threshold):
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
            final = (sim * K1) + (tf * K2) + (pb * K3) + (eb * K4) + noise

            scored.append({
                "source": "memory",
                "id": int(eternal_id or 0),
                "content": content,
                "type": mtype,
                "priority": priority,
                "date_created": date_created,
                "score": float(final),
                "_dbg": {
                    "sim": sim, "time": tf, "prio": pb, "entity": eb, "noise": noise,
                    "final": final
                }
            })

        # 2) History (is_active=0 AND is_deleted=0)
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
            if sim < float(threshold):
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
            final = (sim * K1) + (tf * K2) + (eb * K4) + noise

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
                    "sim": sim, "time": tf, "prio": 0.0, "entity": eb, "noise": noise,
                    "final": final
                }
            })

        conn.close()

        scored.sort(key=lambda x: float(x.get("score") or 0.0), reverse=True)

        # --- Detailed logging: Top 5 и Bottom 5
        try:
            if scored and detailed_logs:
                def _clip(s: Any, n: int = 90) -> str:
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
                        f"| Prio:{dbg.get('prio'):.3f} | Ent:{dbg.get('entity'):.3f} | Final:{dbg.get('final'):.3f} "
                        f"| Content:\"{_clip(item.get('content'))}\""
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
    def index_all_missing(self, progress_callback=None) -> int:
        """
        Проходит по всем записям без вектора и генерирует его.
        progress_callback(current, total) - для обновления UI
        Возвращает количество обновленных записей.

        Для эффективности здесь используем прямой доступ к Singleton handler (без EventBus на каждую запись),
        но Singleton уже будет прогрет EmbeddingController'ом при наличии.
        """
        conn = self.db.get_connection()
        cursor = conn.cursor()

        # 1. Собираем ID для обновления
        # История
        hist_where = "character_id=? AND embedding IS NULL AND content != '' AND content IS NOT NULL"
        if "is_deleted" in self._history_cols:
            hist_where += " AND is_deleted=0"
        cursor.execute(
            f"SELECT id, content FROM history WHERE {hist_where}",
            (self.character_id,),
        )
        hist_rows = cursor.fetchall()

        # Воспоминания
        mem_where = "character_id=? AND embedding IS NULL AND is_deleted=0"
        # НЕ фильтруем is_forgotten: забытые тоже должны иметь embedding, раз мы их ищем RAG-ом
        cursor.execute(
            f"SELECT eternal_id, content FROM memories WHERE {mem_where}",
            (self.character_id,),
        )
        mem_rows = cursor.fetchall()

        total = len(hist_rows) + len(mem_rows)
        if total == 0:
            conn.close()
            return 0

        processed = 0

        try:
            # Обработка истории
            for row_id, content in hist_rows:
                if content and isinstance(content, str):
                    # Простая эвристика: если это JSON мультимодальности, берем как есть (или можно извлекать текст отдельно)
                    # content может быть JSON-string — оставляем текущую логику без усложнений
                    vec = self._get_embedding(content, use_event_bus=False)
                    if vec is not None:
                        blob = self._array_to_blob(vec)
                        cursor.execute("UPDATE history SET embedding = ? WHERE id = ?", (blob, row_id))

                processed += 1
                if progress_callback:
                    progress_callback(processed, total)

            conn.commit()  # Промежуточный коммит

            # Обработка воспоминаний
            for eternal_id, content in mem_rows:
                if content:
                    vec = self._get_embedding(content, use_event_bus=False)
                    if vec is not None:
                        blob = self._array_to_blob(vec)
                        cursor.execute(
                            "UPDATE memories SET embedding = ? WHERE character_id = ? AND eternal_id = ?",
                            (blob, self.character_id, eternal_id)
                        )

                processed += 1
                if progress_callback:
                    progress_callback(processed, total)

            conn.commit()

        except Exception as e:
            logger.error(f"Error during re-indexing: {e}", exc_info=True)
        finally:
            conn.close()

        return processed

    def index_all(self, progress_callback=None) -> int:
        """
        Проходит по ВСЕМ записям и пересоздаёт вектора (даже если уже есть).
        progress_callback(current, total) - для обновления UI
        Возвращает количество обновленных записей.
        """
        conn = self.db.get_connection()
        cursor = conn.cursor()

        # История - ВСЕ записи с контентом
        hist_where = "character_id=? AND content != '' AND content IS NOT NULL"
        if "is_deleted" in self._history_cols:
            hist_where += " AND is_deleted=0"
        cursor.execute(
            f"SELECT id, content FROM history WHERE {hist_where}",
            (self.character_id,),
        )
        hist_rows = cursor.fetchall()

        # Воспоминания - ВСЕ
        mem_where = "character_id=? AND is_deleted=0 AND content IS NOT NULL"
        cursor.execute(
            f"SELECT eternal_id, content FROM memories WHERE {mem_where}",
            (self.character_id,),
        )
        mem_rows = cursor.fetchall()

        total = len(hist_rows) + len(mem_rows)
        if total == 0:
            conn.close()
            return 0

        processed = 0

        try:
            for row_id, content in hist_rows:
                if content and isinstance(content, str):
                    vec = self._get_embedding(content, use_event_bus=False)
                    if vec is not None:
                        blob = self._array_to_blob(vec)
                        cursor.execute("UPDATE history SET embedding = ? WHERE id = ?", (blob, row_id))

                processed += 1
                if progress_callback:
                    progress_callback(processed, total)

            conn.commit()

            for eternal_id, content in mem_rows:
                if content:
                    vec = self._get_embedding(content, use_event_bus=False)
                    if vec is not None:
                        blob = self._array_to_blob(vec)
                        cursor.execute(
                            "UPDATE memories SET embedding = ? WHERE character_id = ? AND eternal_id = ?",
                            (blob, self.character_id, eternal_id)
                        )

                processed += 1
                if progress_callback:
                    progress_callback(processed, total)

            conn.commit()

        except Exception as e:
            logger.error(f"Error during full re-indexing: {e}", exc_info=True)
        finally:
            conn.close()

        return processed

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