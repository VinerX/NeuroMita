import json
import logging
import datetime
from concurrent.futures import ThreadPoolExecutor
from threading import Lock
from typing import Optional, Tuple, List, Set, ClassVar

from managers.database_manager import DatabaseManager
from managers.settings_manager import SettingsManager
from managers.character_scoped_service import CharacterScopedService

try:
    from utils.ru_stem import ru_stem as _ru_light_stem
except Exception:  # стеммер опционален — без него дедуп работает по сырым токенам
    def _ru_light_stem(word: str) -> str:  # type: ignore
        return str(word or "").lower()


_ISLAND_PREFIX = "island:"
_ISLAND_TYPES = ("relationship", "opinion", "preferences", "commitments_conflicts")


def is_island(memory_type: Optional[str]) -> bool:
    return str(memory_type or "").strip().lower().startswith(_ISLAND_PREFIX)


def island_subtype(memory_type: Optional[str]) -> Optional[str]:
    raw = str(memory_type or "").strip().lower()
    if raw.startswith(_ISLAND_PREFIX):
        raw = raw[len(_ISLAND_PREFIX):]
    return raw if raw in _ISLAND_TYPES else None


def make_island_type(subtype: str) -> str:
    return f"{_ISLAND_PREFIX}{subtype}"


class MemoryManager(CharacterScopedService):
    """
    Концепция:
    - Активные воспоминания: is_deleted=0 AND is_forgotten=0  (это попадает в промпт целиком в пределах лимита)
    - Забытая память: is_forgotten=1 (не попадает в промпт, но может быть найдена RAG)
    - Ручное удаление: is_deleted=1 (не используется нигде)
    """

    # Process-wide executor для фоновой векторизации памяти (не блокирует UI/генерацию).
    # max_workers=1: сохраняем порядок и не устраиваем параллельный инференс.
    _EMBED_EXECUTOR: ClassVar[Optional[ThreadPoolExecutor]] = None
    _EMBED_EXECUTOR_LOCK: ClassVar[Lock] = Lock()

    def __init__(self, character_name: str = ""):
        super().__init__(
            default_character_id=str(character_name or ""),
            default_character_name=str(character_name or ""),
        )
        self.db = DatabaseManager()
        self._total_characters: dict[str, int] = {}
        self._rags: dict[str, object | None] = {}
        self._rag_initialized: set[str] = set()

        # Схема общая для всех персонажей и проверяется один раз.
        self._ensure_memories_schema()

    @property
    def total_characters(self) -> int:
        key = self.character_id
        if key not in self._total_characters:
            self._calculate_total_characters()
        return int(self._total_characters.get(key, 0))

    @total_characters.setter
    def total_characters(self, value: int) -> None:
        self._total_characters[self.character_id] = max(0, int(value or 0))

    @property
    def rag(self):
        key = self.character_id
        if key in self._rag_initialized:
            return self._rags.get(key)
        self._rag_initialized.add(key)
        try:
            from managers.rag.rag_manager import RAGManager

            self._rags[key] = RAGManager.for_character(key)
        except Exception as exc:
            logging.warning(
                f"RAGManager init failed for {key} (RAG disabled for this session): {exc}",
                exc_info=True,
            )
            self._rags[key] = None
        return self._rags.get(key)

    @rag.setter
    def rag(self, value) -> None:
        key = self.character_id
        self._rag_initialized.add(key)
        self._rags[key] = value

    # ------------------------------------------------------------------
    # Embedding async helpers
    # ------------------------------------------------------------------
    @classmethod
    def shutdown_executor(cls) -> None:
        with cls._EMBED_EXECUTOR_LOCK:
            executor = cls._EMBED_EXECUTOR
            cls._EMBED_EXECUTOR = None
        if executor is not None:
            executor.shutdown(wait=False, cancel_futures=True)

    @classmethod
    def _get_embed_executor(cls) -> ThreadPoolExecutor:
        ex = cls._EMBED_EXECUTOR
        if ex is not None:
            return ex
        with cls._EMBED_EXECUTOR_LOCK:
            ex = cls._EMBED_EXECUTOR
            if ex is None:
                cls._EMBED_EXECUTOR = ThreadPoolExecutor(
                    max_workers=1,
                    thread_name_prefix="rag-embed-mem",
                )
            return cls._EMBED_EXECUTOR

    # ------------------------------------------------------------------
    # Schema helpers (never crash)
    # ------------------------------------------------------------------

    def _mem_cols(self) -> Set[str]:
        """Читаем фактическую схему таблицы memories без зависимости от методов DBManager."""
        conn = self.db.get_connection()
        try:
            cur = conn.cursor()
            cur.execute("PRAGMA table_info(memories)")
            return set(r[1] for r in cur.fetchall() if r and len(r) > 1)
        except Exception:
            return set()
        finally:
            try:
                conn.close()
            except Exception:
                pass

    def _ensure_memories_schema(self) -> None:
        """Ensure memory columns and the one-active-island invariant."""
        try:
            cols = self._mem_cols()
            needed = []
            if "is_forgotten" not in cols:
                needed.append(("is_forgotten", "INTEGER DEFAULT 0"))
            if "access_count" not in cols:
                needed.append(("access_count", "INTEGER DEFAULT 0"))
            if "last_accessed" not in cols:
                needed.append(("last_accessed", "TEXT"))

            if needed and hasattr(self.db, "ensure_columns"):
                try:
                    self.db.ensure_columns("memories", needed)
                except Exception:
                    pass

            cols2 = self._mem_cols()
            if "is_forgotten" not in cols2:
                logging.warning("[MemoryManager] Column memories.is_forgotten is missing; forget mechanism will be disabled.")
                return

            self._ensure_island_uniqueness()
        except Exception as e:
            logging.warning(f"[MemoryManager] Schema check failed (ignored): {e}", exc_info=True)

    def _ensure_island_uniqueness(self) -> None:
        """Collapse legacy duplicates and enforce one active island per type.

        The newest non-deleted row wins by date_created, then eternal_id/id.
        Older duplicates are soft-deleted. A partial unique index protects the
        invariant from every write path, not only ``upsert_island``.
        """
        cols = self._mem_cols()
        required = {"id", "character_id", "eternal_id", "type", "date_created", "is_deleted", "is_forgotten"}
        if not required.issubset(cols):
            return

        island_types = tuple(make_island_type(t) for t in _ISLAND_TYPES)
        placeholders = ",".join("?" for _ in island_types)
        index_types = ", ".join(f"'{t}'" for t in island_types)

        with self.db.connection() as conn:
            cur = conn.cursor()
            cur.execute(
                f"""
                SELECT id, character_id, eternal_id, type, date_created, is_forgotten
                FROM memories
                WHERE is_deleted=0 AND type IN ({placeholders})
                """,
                island_types,
            )
            groups = {}
            for row in (cur.fetchall() or []):
                groups.setdefault((str(row[1]), str(row[3])), []).append(row)

            removed = 0
            for rows in groups.values():
                if not rows:
                    continue
                keep = max(
                    rows,
                    key=lambda r: (self._parse_dt(r[4]), int(r[2] or 0), int(r[0] or 0)),
                )
                keep_id = int(keep[0])
                duplicate_ids = [int(r[0]) for r in rows if int(r[0]) != keep_id]
                if duplicate_ids:
                    cur.executemany(
                        "UPDATE memories SET is_deleted=1 WHERE id=?",
                        [(rid,) for rid in duplicate_ids],
                    )
                    removed += len(duplicate_ids)
                cur.execute(
                    "UPDATE memories SET is_deleted=0, is_forgotten=0 WHERE id=?",
                    (keep_id,),
                )

            cur.execute(
                f"""
                CREATE UNIQUE INDEX IF NOT EXISTS idx_memories_unique_active_island
                ON memories(character_id, type)
                WHERE is_deleted=0 AND is_forgotten=0
                  AND type IN ({index_types})
                """
            )
            conn.commit()

        if removed:
            logging.info(f"[MemoryManager] Removed {removed} duplicate island memories.")

    # ------------------------------------------------------------------
    # Config / ranking
    # ------------------------------------------------------------------

    def _get_memory_capacity(self) -> int:
        """Максимум активных (не удалённых и не забытых) воспоминаний."""
        try:
            cap = int(SettingsManager.get("MEMORY_CAPACITY", 50))
            return max(1, cap)
        except Exception:
            return 50

    def _parse_dt(self, s: Optional[str]) -> datetime.datetime:
        if not s:
            return datetime.datetime.min
        raw = str(s).strip()
        if not raw:
            return datetime.datetime.min
        fmts = ("%d.%m.%Y %H:%M:%S", "%d.%m.%Y_%H.%M", "%d.%m.%Y %H:%M")
        for f in fmts:
            try:
                return datetime.datetime.strptime(raw, f)
            except Exception:
                continue
        return datetime.datetime.min

    def _priority_rank_for_forget(self, prio: str) -> int:
        """
        Чем меньше — тем раньше "умирает".
        Low < Normal < High. Critical исключаем из авто-забывания.
        """
        p = str(prio or "Normal").strip().lower()
        if p == "low":
            return 0
        if p == "high":
            return 2
        if p == "critical":
            return 999
        return 1  # Normal/unknown

    _PRIORITY_ORDER = {"low": 0, "normal": 1, "high": 2, "critical": 3}

    def _max_priority(self, a: str, b: str) -> str:
        """Возвращает более высокий из двух приоритетов (для merge при дедупе)."""
        ra = self._PRIORITY_ORDER.get(str(a or "normal").strip().lower(), 1)
        rb = self._PRIORITY_ORDER.get(str(b or "normal").strip().lower(), 1)
        return a if ra >= rb else b

    # ------------------------------------------------------------------
    # Dedup on insert (lexical similarity, no ML dependency)
    # ------------------------------------------------------------------

    @staticmethod
    def _dedup_tokens(text: str) -> frozenset:
        """
        Нормализуем текст в набор токенов для дешёвого сравнения похожести.
        Чистый Python, работает и в боевом libs/python без torch.
        """
        import re as _re
        raw = str(text or "").lower()
        # оставляем буквы/цифры (в т.ч. кириллицу), остальное — разделители
        parts = _re.split(r"[^0-9a-zа-яё]+", raw)
        toks = set()
        for p in parts:
            p = p.strip()
            if len(p) < 3:
                continue
            # лёгкая ru-нормализация окончаний, если стеммер доступен
            toks.add(_ru_light_stem(p))
        return frozenset(toks)

    @staticmethod
    def _dedup_similarity(a: frozenset, b: frozenset) -> float:
        """Jaccard-похожесть двух наборов токенов (0..1)."""
        if not a or not b:
            return 0.0
        inter = len(a & b)
        if inter == 0:
            return 0.0
        return inter / float(len(a | b))

    def _find_duplicate_memory(self, content: str, threshold: float):
        """
        Ищем среди активных воспоминаний ближайший дубль по лексической похожести.
        Возвращает (eternal_id, priority, similarity) для лучшего совпадения >= threshold,
        иначе None. Острова и summary исключаем — у них своя гигиена.
        """
        cand_tokens = self._dedup_tokens(content)
        if not cand_tokens:
            return None

        cols = self._mem_cols()
        where = "character_id=? AND is_deleted=0"
        params = [self.storage_key]
        if "is_forgotten" in cols:
            where += " AND is_forgotten=0"
        where += f" AND (type IS NULL OR (type NOT LIKE '{_ISLAND_PREFIX}%' AND type != 'summary'))"

        conn = self.db.get_connection()
        try:
            cur = conn.cursor()
            cur.execute(
                f"SELECT eternal_id, priority, content FROM memories WHERE {where}",
                tuple(params),
            )
            rows = cur.fetchall() or []
        except Exception:
            return None
        finally:
            try:
                conn.close()
            except Exception:
                pass

        best = None
        for eid, prio, existing in rows:
            sim = self._dedup_similarity(cand_tokens, self._dedup_tokens(existing))
            if sim >= threshold and (best is None or sim > best[2]):
                best = (int(eid), str(prio or "Normal"), sim)
        return best

    # ------------------------------------------------------------------
    # Counters
    # ------------------------------------------------------------------

    def _calculate_total_characters(self) -> None:
        """Считаем символы только по активным воспоминаниям."""
        cols = self._mem_cols()
        conn = self.db.get_connection()
        try:
            cur = conn.cursor()
            where = "character_id=? AND is_deleted=0"
            params = [self.storage_key]
            if "is_forgotten" in cols:
                where += " AND is_forgotten=0"
            where += f" AND (type IS NULL OR type NOT LIKE '{_ISLAND_PREFIX}%')"
            cur.execute(f"SELECT SUM(LENGTH(content)) FROM memories WHERE {where}", tuple(params))
            result = cur.fetchone()[0]
            self._total_characters[self.character_id] = int(result) if result else 0
        finally:
            try:
                conn.close()
            except Exception:
                pass

    # ------------------------------------------------------------------
    # Forget mechanism
    # ------------------------------------------------------------------

    def _forget_over_limit_memories(self) -> None:
        """
        Делает место ПЕРЕД добавлением новой памяти:
        - хотим, чтобы после INSERT получилось <= cap активных
        - значит ДО INSERT должно быть < cap активных
        - поэтому забываем, пока active_count < cap

        Правила:
        - забываем только среди is_deleted=0 AND is_forgotten=0
        - Critical не трогаем
        - сортировка жертвы: Low -> Normal -> High, затем самый старый
        """
        # гарантируем колонку (и не падаем, если не получилось)
        cols = self._mem_cols()
        if "is_forgotten" not in cols:
            return  # без колонки корректно забывать нельзя

        cap = self._get_memory_capacity()

        conn = self.db.get_connection()
        try:
            cur = conn.cursor()

            # сколько активных сейчас
            cur.execute(
                f"SELECT COUNT(*) FROM memories "
                f"WHERE character_id=? AND is_deleted=0 AND is_forgotten=0 "
                f"AND (type IS NULL OR type NOT LIKE '{_ISLAND_PREFIX}%')",
                (self.storage_key,),
            )
            active_count = int(cur.fetchone()[0] or 0)

            # Нам нужно, чтобы ДО добавления новой памяти было active_count < cap
            # То есть забываем need = active_count - (cap - 1)
            need = active_count - (cap - 1)
            if need <= 0:
                return

            # Собираем всех кандидатов (Critical нельзя; islands защищены).
            # access_count (если есть) — сигнал «полезности»: сколько раз RAG
            # поднимал эту память. Он populated в rag_manager при ретриве.
            use_retrieval = self._forget_use_retrieval() and ("access_count" in cols)
            access_sel = ", access_count" if use_retrieval else ""
            cur.execute(
                f"""
                SELECT id, eternal_id, priority, date_created, content{access_sel}
                FROM memories
                WHERE character_id=? AND is_deleted=0 AND is_forgotten=0
                  AND (type IS NULL OR type NOT LIKE '{_ISLAND_PREFIX}%')
                """,
                (self.storage_key,),
            )
            rows = cur.fetchall() or []

            candidates: List[Tuple[int, int, str, str, str, int]] = []
            for row in rows:
                rid, eid, prio, dt, content = row[0], row[1], row[2], row[3], row[4]
                if str(prio or "").strip().lower() == "critical":
                    continue
                acc = int(row[5] or 0) if use_retrieval and len(row) > 5 else 0
                candidates.append((int(rid), int(eid or 0), str(prio or "Normal"), str(dt or ""), str(content or ""), acc))

            if not candidates:
                logging.warning(
                    f"[MemoryManager] MEMORY_CAPACITY={cap}, but no non-critical memories to forget. "
                    f"Active={active_count} (cannot prune)."
                )
                return

            # Сортировка жертвы: сначала приоритет (Low->Normal->High). Затем, если
            # включён учёт полезности — грубый бакет «поднимался ли RAG'ом» (0=ни разу
            # забываем раньше, 1=был полезен — бережём), и только потом возраст. Так
            # часто всплывающая память переживает старую, но ни разу не пригодившуюся,
            # а свежесозданная (access=0) конкурирует с прочими access=0 по возрасту.
            def _retr_bucket(acc: int) -> int:
                return 1 if (use_retrieval and acc > 0) else 0
            candidates.sort(
                key=lambda x: (self._priority_rank_for_forget(x[2]), _retr_bucket(x[5]), self._parse_dt(x[3]), x[0])
            )

            victims = candidates[:need]
            victim_ids = [(v[0],) for v in victims]

            # Помечаем забытыми
            cur.executemany("UPDATE memories SET is_forgotten=1 WHERE id=?", victim_ids)
            conn.commit()

            # Обновим total_characters: убираем только тех, кого забыли сейчас (они были активными)
            removed_chars = 0
            for _, _, _, _, content, _acc in victims:
                removed_chars += len(content or "")
            try:
                self.total_characters = max(0, int(self.total_characters) - int(removed_chars))
            except Exception:
                self._calculate_total_characters()

            for _, victim_eid, victim_prio, victim_dt, _, victim_acc in victims:
                logging.info(
                    f"[MemoryManager] Forgot memory eternal_id={victim_eid} "
                    f"(priority={victim_prio}, date={victim_dt}, access={victim_acc})"
                )

            # Если не хватило кандидатов (например, почти всё Critical) — предупредим
            if len(victims) < need:
                logging.warning(
                    f"[MemoryManager] Needed to forget {need}, but forgot only {len(victims)} "
                    f"(likely because remaining are Critical)."
                )

        except Exception as e:
            logging.warning(f"[MemoryManager] prune failed (ignored): {e}", exc_info=True)
        finally:
            try:
                conn.close()
            except Exception:
                pass

        # TTL-очистка (опционально, если включена)
        try:
            self.apply_ttl_cleanup()
        except Exception as e:
            logging.warning(f"[MemoryManager] TTL cleanup in prune failed (ignored): {e}", exc_info=True)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def load_memories(self):
        self._calculate_total_characters()
        try:
            self._forget_over_limit_memories()
        except Exception:
            pass

    def save_memories(self):
        pass

    def _dedup_enabled(self) -> bool:
        try:
            v = SettingsManager.get("MEMORY_DEDUP_ENABLED", True)
            return str(v).strip().lower() not in ("false", "0", "", "none")
        except Exception:
            return True

    def _forget_use_retrieval(self) -> bool:
        """Учитывать ли «полезность» (access_count от RAG) при выборе жертвы забывания."""
        try:
            v = SettingsManager.get("MEMORY_FORGET_USE_RETRIEVAL", True)
            return str(v).strip().lower() not in ("false", "0", "", "none")
        except Exception:
            return True

    def _dedup_threshold(self) -> float:
        try:
            t = float(SettingsManager.get("MEMORY_DEDUP_THRESHOLD", 0.8))
            return min(1.0, max(0.5, t))
        except Exception:
            return 0.8

    def add_memory(self, content, date=None, priority="Normal", memory_type="fact", skip_if_exists=False, entities=None):
        """Add a new memory. Returns the eternal_id of the created memory, or None."""
        memory_type = str(memory_type or "fact").strip() or "fact"
        if is_island(memory_type):
            return self.upsert_island(memory_type, content, priority)

        # Дедуп на вставке: близкий по смыслу дубль обновляем на месте, а не плодим.
        # Только для обычных фактов (острова/summary/сиды — своя гигиена).
        if (
            content and not skip_if_exists
            and memory_type == "fact"
            and self._dedup_enabled()
        ):
            try:
                dup = self._find_duplicate_memory(str(content), self._dedup_threshold())
            except Exception:
                dup = None
            if dup:
                dup_eid, dup_prio, sim = dup
                merged_prio = self._max_priority(dup_prio, priority)
                # Обновляем существующую формулировкой посвежее, поднимаем приоритет.
                self.update_memory(number=dup_eid, content=str(content), priority=merged_prio)
                logging.info(
                    f"[MemoryManager] Dedup: merged new memory into #{dup_eid} "
                    f"(similarity={sim:.2f}, priority={merged_prio})"
                )
                return dup_eid

        if skip_if_exists and content:
            with self.db.connection() as conn:
                cur = conn.cursor()
                cur.execute(
                    "SELECT id, is_deleted, is_forgotten FROM memories WHERE character_id=? AND content=? LIMIT 1",
                    (self.storage_key, str(content)),
                )
                row = cur.fetchone()
                if row:
                    mem_id, is_deleted, is_forgotten = row
                    if is_deleted or is_forgotten:
                        # Восстанавливаем удалённое/забытое воспоминание вместо создания дубля
                        cur.execute(
                            "UPDATE memories SET is_deleted=0, is_forgotten=0, priority=? WHERE id=?",
                            (priority, mem_id),
                        )
                        conn.commit()
                        self._calculate_total_characters()
                    return mem_id

        # забываем ПЕРЕД добавлением новой
        self._forget_over_limit_memories()

        if date is None:
            date = datetime.datetime.now().strftime("%d.%m.%Y %H:%M:%S")

        # NOTE: эмбеддинги считаем ПОСЛЕ успешного commit, но в фоне (см. ниже),
        # чтобы не блокировать основной поток (UI/генерацию).

        conn = self.db.get_connection()
        try:
            cursor = conn.cursor()

            cursor.execute(
                "SELECT MAX(eternal_id) FROM memories WHERE character_id = ?",
                (self.storage_key,)
            )
            res = cursor.fetchone()[0]
            new_id = (res + 1) if res is not None else 1

            cols = self._mem_cols()

            insert_cols = ["character_id", "eternal_id", "content", "priority", "type", "date_created", "is_deleted"]
            insert_vals = [self.storage_key, new_id, content, priority, memory_type, date, 0]

            if "is_forgotten" in cols:
                insert_cols.append("is_forgotten")
                insert_vals.append(0)

            if "entities" in cols and entities:
                insert_cols.append("entities")
                if isinstance(entities, str):
                    insert_vals.append(entities)
                else:
                    insert_vals.append(json.dumps(list(entities), ensure_ascii=False))

            placeholders = ",".join(["?"] * len(insert_cols))
            sql = f"INSERT INTO memories ({', '.join(insert_cols)}) VALUES ({placeholders})"
            cursor.execute(sql, tuple(insert_vals))

            conn.commit()

            # активная память увеличилась
            self.total_characters += len(str(content or ""))

        finally:
            try:
                conn.close()
            except Exception:
                pass

        # RAG опционален и не должен валить основной флоу
        self._schedule_embed(new_id, content)

        return new_id

    def _schedule_embed(self, eternal_id, content) -> None:
        """Schedule a background RAG (re)embedding for a memory. No-op without RAG."""
        if not self.rag:
            return
        try:
            rag = self.rag
            eid = int(eternal_id)
            txt = str(content or "")

            def _embed_job():
                try:
                    rag.update_memory_embedding(eid, txt)
                except Exception as e:
                    logging.warning(f"RAG failed to update memory embedding (ignored): {e}", exc_info=True)

            self._get_embed_executor().submit(_embed_job)
        except Exception as e:
            logging.warning(f"RAG failed to schedule memory embedding (ignored): {e}", exc_info=True)

    def seed_rag_memory(self, content, priority="normal", entities=None) -> Optional[int]:
        """Create a RAG-only memory: indexed and retrievable by search, but never
        part of the always-on ``<active_memory>`` block.

        Stored as ``is_forgotten=1`` so it stays out of the active block yet is
        found by RAG (search ignores the forgotten flag). Deduplicates by exact
        content — re-seeding the same fact updates it in place (no duplicates)
        and keeps it RAG-only rather than promoting it into the active block.
        """
        if not content or not str(content).strip():
            return None
        content = str(content).strip()

        cols = self._mem_cols()
        has_forgotten = "is_forgotten" in cols
        if not has_forgotten:
            # Without the forget column we cannot keep a memory out of the active
            # block; fall back to a normal (skip-if-exists) memory.
            return self.add_memory(content, priority=priority, skip_if_exists=True, entities=entities)

        with self.db.connection() as conn:
            cur = conn.cursor()
            cur.execute(
                "SELECT eternal_id FROM memories WHERE character_id=? AND content=? LIMIT 1",
                (self.storage_key, content),
            )
            row = cur.fetchone()
            if row:
                eid = int(row[0])
                # Keep it RAG-only: undelete but force forgotten, refresh priority.
                cur.execute(
                    "UPDATE memories SET is_deleted=0, is_forgotten=1, priority=? "
                    "WHERE character_id=? AND eternal_id=?",
                    (priority, self.storage_key, eid),
                )
                conn.commit()
                self._schedule_embed(eid, content)
                self._calculate_total_characters()
                return eid

            cur.execute(
                "SELECT MAX(eternal_id) FROM memories WHERE character_id = ?",
                (self.storage_key,),
            )
            res = cur.fetchone()[0]
            new_id = (res + 1) if res is not None else 1

            date = datetime.datetime.now().strftime("%d.%m.%Y %H:%M:%S")
            insert_cols = ["character_id", "eternal_id", "content", "priority",
                           "type", "date_created", "is_deleted", "is_forgotten"]
            insert_vals = [self.storage_key, new_id, content, priority,
                           "fact", date, 0, 1]
            if "entities" in cols and entities:
                insert_cols.append("entities")
                insert_vals.append(
                    entities if isinstance(entities, str)
                    else json.dumps(list(entities), ensure_ascii=False)
                )
            placeholders = ",".join(["?"] * len(insert_cols))
            cur.execute(
                f"INSERT INTO memories ({', '.join(insert_cols)}) VALUES ({placeholders})",
                tuple(insert_vals),
            )
            conn.commit()

        self._schedule_embed(new_id, content)
        return new_id

    # Fixed, small set of running-summary "island" memories.
    ISLAND_TYPES = _ISLAND_TYPES

    def upsert_island(self, island_type: str, content: str, priority: str = "high") -> Optional[int]:
        """Atomically insert or update the sole active island of this type.

        Islands do not consume normal-memory capacity, are not counted in the
        normal character budget, and are deliberately not embedded for RAG.
        On failure this method returns None instead of falling back to a second
        insert that could create a duplicate.
        """
        short = island_subtype(island_type)
        if short is None:
            logging.warning(f"[MemoryManager] upsert_island: unknown island type {island_type!r}, ignored.")
            return None
        if not content or not str(content).strip():
            return None

        self._ensure_memories_schema()
        cols = self._mem_cols()
        has_forgotten = "is_forgotten" in cols
        full_type = make_island_type(short)
        content = str(content).strip()
        now = datetime.datetime.now().strftime("%d.%m.%Y %H:%M:%S")

        try:
            with self.db.connection() as conn:
                cur = conn.cursor()
                select_cols = "id, eternal_id, date_created" + (", is_forgotten" if has_forgotten else "")
                cur.execute(
                    f"SELECT {select_cols} FROM memories "
                    "WHERE character_id=? AND type=? AND is_deleted=0",
                    (self.storage_key, full_type),
                )
                rows = cur.fetchall() or []

                if rows:
                    keep = max(
                        rows,
                        key=lambda r: (self._parse_dt(r[2]), int(r[1] or 0), int(r[0] or 0)),
                    )
                    row_id = int(keep[0])
                    eternal_id = int(keep[1])
                    duplicate_ids = [int(r[0]) for r in rows if int(r[0]) != row_id]
                    if duplicate_ids:
                        cur.executemany(
                            "UPDATE memories SET is_deleted=1 WHERE id=?",
                            [(rid,) for rid in duplicate_ids],
                        )

                    assignments = "content=?, priority=?, date_created=?, is_deleted=0"
                    values = [content, priority, now]
                    if has_forgotten:
                        assignments += ", is_forgotten=0"
                    cur.execute(
                        f"UPDATE memories SET {assignments} WHERE id=?",
                        tuple(values + [row_id]),
                    )
                else:
                    cur.execute(
                        "SELECT MAX(eternal_id) FROM memories WHERE character_id=?",
                        (self.storage_key,),
                    )
                    res = cur.fetchone()[0]
                    eternal_id = (int(res) + 1) if res is not None else 1
                    insert_cols = [
                        "character_id", "eternal_id", "content", "priority",
                        "type", "date_created", "is_deleted",
                    ]
                    insert_vals = [
                        self.storage_key, eternal_id, content, priority,
                        full_type, now, 0,
                    ]
                    if has_forgotten:
                        insert_cols.append("is_forgotten")
                        insert_vals.append(0)
                    placeholders = ",".join("?" for _ in insert_cols)
                    cur.execute(
                        f"INSERT INTO memories ({', '.join(insert_cols)}) VALUES ({placeholders})",
                        tuple(insert_vals),
                    )
                conn.commit()

            return eternal_id
        except Exception as e:
            logging.warning(f"[MemoryManager] upsert_island failed: {e}", exc_info=True)
            return None

    def seed_island(self, island_type: str, content: str, priority: str = "high") -> Optional[int]:
        """Create a starting island only when no row of this type ever existed."""
        short = island_subtype(island_type)
        if short is None:
            logging.warning(f"[MemoryManager] seed_island: unknown island type {island_type!r}, ignored.")
            return None
        if not content or not str(content).strip():
            return None

        full_type = make_island_type(short)
        try:
            with self.db.connection() as conn:
                cur = conn.cursor()
                cur.execute(
                    "SELECT eternal_id FROM memories WHERE character_id=? AND type=? LIMIT 1",
                    (self.storage_key, full_type),
                )
                if cur.fetchone():
                    return None
        except Exception as e:
            logging.warning(f"[MemoryManager] seed_island lookup failed: {e}", exc_info=True)
            return None

        return self.upsert_island(short, str(content).strip(), priority)

    def tag_with_entities(self, eternal_id: int, entity_names: list) -> bool:
        """Merge entity names into the entities column for a given memory."""
        if not entity_names:
            return False

        cols = self._mem_cols()
        if "entities" not in cols:
            return False

        new_names = {str(n).lower().strip() for n in entity_names if str(n).strip()}
        if not new_names:
            return False

        conn = self.db.get_connection()
        try:
            cur = conn.cursor()
            cur.execute(
                "SELECT entities FROM memories WHERE character_id = ? AND eternal_id = ? AND is_deleted = 0",
                (self.storage_key, eternal_id),
            )
            row = cur.fetchone()
            if not row:
                return False

            try:
                existing = set(json.loads(row[0] or "[]"))
            except (json.JSONDecodeError, TypeError):
                existing = set()

            merged = existing | new_names
            merged_json = json.dumps(sorted(merged), ensure_ascii=False)

            cur.execute(
                "UPDATE memories SET entities = ? WHERE character_id = ? AND eternal_id = ?",
                (merged_json, self.storage_key, eternal_id),
            )
            conn.commit()
            return True
        except Exception as e:
            logging.warning(f"[MemoryManager] tag_with_entities failed (ignored): {e}", exc_info=True)
            return False
        finally:
            try:
                conn.close()
            except Exception:
                pass

    def update_memory(self, number, content, priority=None):
        """
        Обновляем только активные (не забытые) как и раньше.
        Если захочешь — можно расширить на забытые, но это уже другой UX.
        """
        cols = self._mem_cols()
        where = "character_id=? AND eternal_id=? AND is_deleted=0"
        params = [self.storage_key, number]
        if "is_forgotten" in cols:
            where += " AND is_forgotten=0"

        conn = self.db.get_connection()
        try:
            cursor = conn.cursor()
            cursor.execute(f"SELECT content, type FROM memories WHERE {where}", tuple(params))
            row = cursor.fetchone()
            if not row:
                return False

            old_len = len(row[0] or "")
            memory_type = row[1]

            if priority:
                cursor.execute(
                    """
                    UPDATE memories SET content=?, priority=?, date_created=?
                    WHERE character_id=? AND eternal_id=?
                    """,
                    (content, priority, datetime.datetime.now().strftime("%d.%m.%Y %H:%M:%S"), self.storage_key, number)
                )
            else:
                cursor.execute(
                    """
                    UPDATE memories SET content=?, date_created=?
                    WHERE character_id=? AND eternal_id=?
                    """,
                    (content, datetime.datetime.now().strftime("%d.%m.%Y %H:%M:%S"), self.storage_key, number)
                )

            conn.commit()

            # Островки ведут отдельный бюджет и не входят в normal-memory chars.
            if not is_island(memory_type):
                self.total_characters = self.total_characters - old_len + len(str(content or ""))

        finally:
            try:
                conn.close()
            except Exception:
                pass

        if (not is_island(memory_type)) and self.rag:
            try:
                rag = self.rag
                eid = int(number)
                txt = str(content or "")

                def _embed_job():
                    try:
                        rag.update_memory_embedding(eid, txt)
                    except Exception as e:
                        logging.warning(f"RAG failed to update memory embedding (ignored): {e}", exc_info=True)

                # В фон: не блокируем UI/генерацию ответа
                self._get_embed_executor().submit(_embed_job)
            except Exception as e:
                logging.warning(f"RAG failed to schedule memory embedding (ignored): {e}", exc_info=True)

        return True

    def get_memory_content(self, number: int):
        """Return content of an active memory by eternal_id, or None if not found."""
        cols = self._mem_cols()
        where = "character_id=? AND eternal_id=? AND is_deleted=0"
        params = [self.storage_key, number]
        if "is_forgotten" in cols:
            where += " AND is_forgotten=0"
        conn = self.db.get_connection()
        try:
            cursor = conn.cursor()
            cursor.execute(f"SELECT content FROM memories WHERE {where}", tuple(params))
            row = cursor.fetchone()
            return row[0] if row else None
        finally:
            try:
                conn.close()
            except Exception:
                pass

    def delete_memory(self, number, save_as_missing=False):
        """
        Ручное удаление (is_deleted=1) — должно работать и для забытых тоже.
        Поэтому НЕ фильтруем по is_forgotten при поиске.
        """
        cols = self._mem_cols()

        conn = self.db.get_connection()
        try:
            cursor = conn.cursor()

            select_cols = ["content", "type"]
            if "is_forgotten" in cols:
                select_cols.append("is_forgotten")

            cursor.execute(
                f"SELECT {', '.join(select_cols)} FROM memories WHERE character_id=? AND eternal_id=? AND is_deleted=0",
                (self.storage_key, number)
            )
            row = cursor.fetchone()
            if not row:
                logging.warning(f"Memory {number} not found for deletion.")
                return False

            content, memory_type = row[0], row[1]
            if "is_forgotten" in cols:
                is_forgotten = int(row[2] or 0)
            else:
                is_forgotten = 0

            cursor.execute(
                "UPDATE memories SET is_deleted=1 WHERE character_id=? AND eternal_id=?",
                (self.storage_key, number)
            )
            conn.commit()

            # уменьшаем normal-memory счётчик только для активного не-островка
            if not is_island(memory_type):
                if ("is_forgotten" in cols) and (is_forgotten == 0):
                    self.total_characters = max(0, self.total_characters - len(content or ""))
                elif "is_forgotten" not in cols:
                    self.total_characters = max(0, self.total_characters - len(content or ""))

            logging.info(f"Memory {number} deleted (soft delete).")
            return True
        finally:
            try:
                conn.close()
            except Exception:
                pass

    def merge_memories(self, source_id: int, target_id: int, new_content: Optional[str] = None) -> bool:
        """
        Merge source memory into target:
        - Update target content (if new_content provided, otherwise keep target's)
        - Transfer entities from source to target
        - Re-embed target in background
        - Soft-delete source (is_deleted=1)
        Returns True on success.
        """
        if source_id == target_id:
            logging.warning(f"[MemoryManager] merge_memories: source == target ({source_id}), skipped.")
            return False

        cols = self._mem_cols()
        final_content = None
        target_type = None

        try:
            with self.db.connection() as conn:
                cur = conn.cursor()

                # Fetch source
                cur.execute(
                    "SELECT content, entities FROM memories WHERE character_id=? AND eternal_id=? AND is_deleted=0",
                    (self.storage_key, source_id),
                )
                src = cur.fetchone()
                if not src:
                    logging.warning(f"[MemoryManager] merge_memories: source #{source_id} not found or deleted.")
                    return False

                # Fetch target
                cur.execute(
                    "SELECT content, entities, type FROM memories WHERE character_id=? AND eternal_id=? AND is_deleted=0",
                    (self.storage_key, target_id),
                )
                tgt = cur.fetchone()
                if not tgt:
                    logging.warning(f"[MemoryManager] merge_memories: target #{target_id} not found or deleted.")
                    return False

                # Merge entity sets
                try:
                    src_ents = set(json.loads(src[1] or "[]"))
                except (json.JSONDecodeError, TypeError):
                    src_ents = set()
                try:
                    tgt_ents = set(json.loads(tgt[1] or "[]"))
                except (json.JSONDecodeError, TypeError):
                    tgt_ents = set()
                merged_ents_json = json.dumps(sorted(src_ents | tgt_ents), ensure_ascii=False)

                final_content = new_content if new_content is not None else tgt[0]
                target_type = tgt[2]
                now = datetime.datetime.now().strftime("%d.%m.%Y %H:%M:%S")

                if "entities" in cols:
                    cur.execute(
                        "UPDATE memories SET content=?, entities=?, date_created=? WHERE character_id=? AND eternal_id=?",
                        (final_content, merged_ents_json, now, self.storage_key, target_id),
                    )
                else:
                    cur.execute(
                        "UPDATE memories SET content=?, date_created=? WHERE character_id=? AND eternal_id=?",
                        (final_content, now, self.storage_key, target_id),
                    )

                # Soft-delete source
                cur.execute(
                    "UPDATE memories SET is_deleted=1 WHERE character_id=? AND eternal_id=?",
                    (self.storage_key, source_id),
                )
                conn.commit()

        except Exception as e:
            logging.warning(f"[MemoryManager] merge_memories failed: {e}", exc_info=True)
            return False

        # Recalculate since source was deleted and target content may have changed
        self._calculate_total_characters()

        # Re-embed target in background
        if (not is_island(target_type)) and self.rag and final_content is not None:
            try:
                rag = self.rag
                eid = int(target_id)
                txt = str(final_content)

                def _embed_job():
                    try:
                        rag.update_memory_embedding(eid, txt)
                    except Exception as e:
                        logging.warning(f"RAG failed to update memory embedding (ignored): {e}", exc_info=True)

                self._get_embed_executor().submit(_embed_job)
            except Exception as e:
                logging.warning(f"RAG failed to schedule memory embedding (ignored): {e}", exc_info=True)

        logging.info(f"[MemoryManager] Merged memory #{source_id} into #{target_id}")
        return True

    def _maintenance_enabled(self) -> bool:
        try:
            v = SettingsManager.get("MEMORY_MAINTENANCE_ENABLED", True)
            return str(v).strip().lower() not in ("false", "0", "", "none")
        except Exception:
            return True

    def run_maintenance(self) -> dict:
        """
        Фоновая ревизия активной памяти БЕЗ LLM: находит накопившиеся дубли и
        схлопывает их (полный проход, а не только на вставке). Кластеризует активные
        факты по лексической похожести, в каждой группе оставляет «лучший» экземпляр
        (приоритет → свежесть → длина), остальные merge'ит в него.

        Возвращает {"merged": N, "clusters": M}. Безопасно вызывать из BACKGROUND_LLM.
        """
        result = {"merged": 0, "clusters": 0}
        if not self._maintenance_enabled():
            return result

        threshold = self._dedup_threshold()

        cols = self._mem_cols()
        where = "character_id=? AND is_deleted=0"
        params = [self.storage_key]
        if "is_forgotten" in cols:
            where += " AND is_forgotten=0"
        where += f" AND (type IS NULL OR (type NOT LIKE '{_ISLAND_PREFIX}%' AND type != 'summary'))"

        conn = self.db.get_connection()
        try:
            cur = conn.cursor()
            cur.execute(
                f"SELECT eternal_id, priority, content, date_created FROM memories WHERE {where}",
                tuple(params),
            )
            rows = cur.fetchall() or []
        except Exception as e:
            logging.warning(f"[MemoryManager] run_maintenance fetch failed (ignored): {e}", exc_info=True)
            return result
        finally:
            try:
                conn.close()
            except Exception:
                pass

        if len(rows) < 2:
            return result

        # Собираем элементы с токенами
        items = []
        for eid, prio, content, date in rows:
            toks = self._dedup_tokens(content)
            if not toks:
                continue
            items.append({
                "eid": int(eid),
                "prio": str(prio or "Normal"),
                "content": str(content or ""),
                "date": str(date or ""),
                "tokens": toks,
            })

        # Жадная кластеризация по представителям
        clusters: List[list] = []
        for it in items:
            placed = False
            for cl in clusters:
                if self._dedup_similarity(it["tokens"], cl[0]["tokens"]) >= threshold:
                    cl.append(it)
                    placed = True
                    break
            if not placed:
                clusters.append([it])

        def _score(m):
            return (
                self._PRIORITY_ORDER.get(m["prio"].strip().lower(), 1),
                self._parse_dt(m["date"]),
                len(m["content"]),
            )

        merged_total = 0
        cluster_count = 0
        for cl in clusters:
            if len(cl) < 2:
                continue
            cluster_count += 1
            keeper = max(cl, key=_score)
            keeper_prio = keeper["prio"]
            keeper_content = keeper["content"]
            for m in cl:
                if m["eid"] == keeper["eid"]:
                    continue
                keeper_prio = self._max_priority(keeper_prio, m["prio"])
                if self.merge_memories(source_id=m["eid"], target_id=keeper["eid"], new_content=keeper_content):
                    merged_total += 1
            # обновим приоритет кипера, если поднялся
            if keeper_prio.strip().lower() != keeper["prio"].strip().lower():
                self.update_memory(number=keeper["eid"], content=keeper_content, priority=keeper_prio)

        if merged_total:
            logging.info(
                f"[MemoryManager] Maintenance: merged {merged_total} duplicate memories "
                f"in {cluster_count} clusters for '{self.storage_key}'"
            )
        result["merged"] = merged_total
        result["clusters"] = cluster_count
        return result

    def apply_ttl_cleanup(self) -> int:
        """
        Mark old memories as forgotten (is_forgotten=1) based on TTL settings.
        Controlled by MEMORY_TTL_ENABLED, MEMORY_TTL_LOW/NORMAL/HIGH_DAYS, MEMORY_TTL_MODE.

        MEMORY_TTL_MODE options:
          "date_created"    — age from date_created (default)
          "access_weighted" — effective_days = base * (1 + log(1 + access_count) * weight)
          "last_accessed"   — age from last_accessed (fallback to date_created if NULL)

        Returns count of newly forgotten memories.
        """
        try:
            enabled = SettingsManager.get("MEMORY_TTL_ENABLED", False)
            if str(enabled).lower() in ("false", "0", "", "none"):
                return 0
        except Exception:
            return 0

        cols = self._mem_cols()
        if "is_forgotten" not in cols:
            return 0

        try:
            ttl_low    = int(SettingsManager.get("MEMORY_TTL_LOW_DAYS",    30))
            ttl_normal = int(SettingsManager.get("MEMORY_TTL_NORMAL_DAYS",  0))
            ttl_high   = int(SettingsManager.get("MEMORY_TTL_HIGH_DAYS",    0))
        except Exception:
            ttl_low, ttl_normal, ttl_high = 30, 0, 0

        ttl_mode = str(SettingsManager.get("MEMORY_TTL_MODE", "date_created")).strip().lower()
        try:
            ttl_weight = float(SettingsManager.get("MEMORY_TTL_ACCESS_WEIGHT", 0.5))
        except Exception:
            ttl_weight = 0.5

        has_access = "access_count" in cols
        has_la     = "last_accessed" in cols

        def _norm_date_expr(col: str) -> str:
            """SQLite expression: convert dd.mm.yyyy HH:MM:SS → ISO for julianday()."""
            return (
                f"CASE WHEN {col} LIKE '__.__.____ __:__:__' "
                f"THEN substr({col},7,4)||'-'||substr({col},4,2)||'-'||substr({col},1,2)||' '||substr({col},12) "
                f"ELSE {col} END"
            )

        _date_created_expr = _norm_date_expr("date_created")

        # For last_accessed mode: use last_accessed if present, else fallback to date_created
        if ttl_mode == "last_accessed" and has_la:
            _age_expr = (
                f"julianday('now') - julianday(CASE WHEN last_accessed IS NOT NULL AND last_accessed != '' "
                f"THEN {_norm_date_expr('last_accessed')} ELSE {_date_created_expr} END)"
            )
        else:
            _age_expr = f"julianday('now') - julianday({_date_created_expr})"

        priorities = []
        if ttl_low    > 0: priorities.append(("low",    ttl_low))
        if ttl_normal > 0: priorities.append(("normal", ttl_normal))
        if ttl_high   > 0: priorities.append(("high",   ttl_high))

        total = 0

        if ttl_mode == "access_weighted" and has_access:
            # Python-side filtering: pull candidates, compute effective_days
            import math as _math
            try:
                with self.db.connection() as conn:
                    for prio, base_days in priorities:
                        pre_days = base_days * 0.5
                        extra = ", access_count" if has_access else ""
                        rows = conn.execute(
                            f"SELECT eternal_id, {_age_expr} as age{extra} "
                            f"FROM memories WHERE character_id=? AND is_deleted=0 AND is_forgotten=0 "
                            f"AND (type IS NULL OR type NOT LIKE '{_ISLAND_PREFIX}%') "
                            f"AND LOWER(priority)=? AND {_age_expr} > ?",
                            (self.storage_key, prio, pre_days),
                        ).fetchall()

                        to_forget = []
                        for row in rows:
                            eid = row[0]
                            age = row[1]
                            ac  = row[2] if has_access else 0
                            effective = base_days * (1.0 + _math.log(1 + ac) * ttl_weight)
                            if age > effective:
                                to_forget.append(eid)

                        BATCH = 900
                        for i in range(0, len(to_forget), BATCH):
                            chunk = to_forget[i:i + BATCH]
                            ph = ",".join("?" * len(chunk))
                            conn.execute(
                                f"UPDATE memories SET is_forgotten=1 WHERE eternal_id IN ({ph})",
                                chunk,
                            )
                        total += len(to_forget)

                    if total > 0:
                        conn.commit()
            except Exception as e:
                logging.warning(f"[MemoryManager] apply_ttl_cleanup (access_weighted) failed: {e}", exc_info=True)
        else:
            # Pure SQL path (date_created or last_accessed)
            try:
                with self.db.connection() as conn:
                    cur = conn.cursor()
                    for prio, base_days in priorities:
                        cur.execute(
                            f"""
                            UPDATE memories SET is_forgotten=1
                            WHERE character_id=? AND is_deleted=0 AND is_forgotten=0
                              AND (type IS NULL OR type NOT LIKE '{_ISLAND_PREFIX}%')
                              AND LOWER(priority)=?
                              AND {_age_expr} > ?
                            """,
                            (self.storage_key, prio, base_days),
                        )
                        total += cur.rowcount

                    if total > 0:
                        conn.commit()
            except Exception as e:
                logging.warning(f"[MemoryManager] apply_ttl_cleanup failed: {e}", exc_info=True)

        if total > 0:
            self._calculate_total_characters()
            logging.info(f"[MemoryManager] TTL cleanup: forgot {total} memories for '{self.storage_key}' (mode={ttl_mode})")

        return total

    def clear_memories(self):
        conn = self.db.get_connection()
        try:
            cursor = conn.cursor()
            cursor.execute("UPDATE memories SET is_deleted=1 WHERE character_id=?", (self.storage_key,))
            conn.commit()
        finally:
            try:
                conn.close()
            except Exception:
                pass
        self.total_characters = 0

    def purge_deleted(self, *, backup: bool = True, backup_dir: str | None = None) -> dict:
        """Physically DELETE is_deleted=1 memories + their embeddings. Optionally backup to JSON first."""
        backed_up = None
        if backup:
            backed_up = self.db.backup_deleted_to_json(
                character_id=self.storage_key,
                backup_dir=backup_dir,
                include_history=False,
                include_memories=True,
            )
            logging.info(f"[MemoryManager] Backup written to: {backed_up}")
        with self.db.connection() as conn:
            cur = conn.cursor()
            for emb_table in ("embeddings", "sentence_embeddings"):
                try:
                    cur.execute(
                        f"DELETE FROM {emb_table} WHERE source_table='memories' AND character_id=?"
                        " AND source_id IN (SELECT id FROM memories WHERE character_id=? AND is_deleted=1)",
                        (self.storage_key, self.storage_key),
                    )
                except Exception as e:
                    logging.warning(f"[MemoryManager] purge_deleted: {emb_table} cleanup failed: {e}")
            cur.execute(
                "DELETE FROM memories WHERE character_id=? AND is_deleted=1",
                (self.storage_key,),
            )
            purged = cur.rowcount
            conn.commit()
        logging.info(f"[MemoryManager] Purged {purged} deleted memories for '{self.storage_key}'")
        return {"backed_up": backed_up, "purged_memories": purged}

    # Default templates (used when no custom file is found in prompt set)
    _DEFAULT_ITEM_TEMPLATE = "{risk_tag}N:{id} [{priority_cap}] {date_short}: {content}"
    _DEFAULT_SUMMARY_TEMPLATE = "{risk_tag}N:{id} [Summary] {date_short}: {content}"
    _DEFAULT_ISLAND_ITEM_TEMPLATE = "[{island_type_cap}] N:{id} {date_short}: {content}"
    _DEFAULT_ISLAND_WRAPPER_TEMPLATE = "<memory_islands>\n{items}\n</memory_islands>"
    _DEFAULT_WRAPPER_TEMPLATE = "<active_memory>\n{items}\n</active_memory>"

    def get_memories_formatted(self) -> str:
        """Единой строкой (для тестов/логов): блоки памяти, склеенные через '\\n'."""
        return "\n".join(self.get_memory_message_blocks())

    def get_memory_message_blocks(self) -> list[str]:
        """Отдельные блоки памяти — острова и активная память идут РАЗНЫМИ
        system-сообщениями, чтобы в просмотрщике контекста быть двумя разделами
        активного контекста, а не одним. Каждый блок начинается со своего тега
        (<memory_islands> / <active_memory>) — по нему classify_message_section
        относит его к «памяти» (активный контекст), а не к истории.

        A final in-memory deduplication protects the prompt even if a legacy or
        externally modified database temporarily contains duplicate islands.
        """
        from utils.template_loader import load_optional_template

        item_tpl = load_optional_template(
            self.prompt_set_path, "Structural/memory_template.txt", self._DEFAULT_ITEM_TEMPLATE
        )
        summary_tpl = load_optional_template(
            self.prompt_set_path, "Structural/memory_summary_template.txt", self._DEFAULT_SUMMARY_TEMPLATE
        )
        island_item_tpl = load_optional_template(
            self.prompt_set_path, "Structural/memory_island_template.txt", self._DEFAULT_ISLAND_ITEM_TEMPLATE
        )
        island_wrapper_tpl = load_optional_template(
            self.prompt_set_path, "Structural/memory_island_wrapper.txt", self._DEFAULT_ISLAND_WRAPPER_TEMPLATE
        )
        wrapper_tpl = load_optional_template(
            self.prompt_set_path, "Structural/memory_wrapper.txt", self._DEFAULT_WRAPPER_TEMPLATE
        )

        try:
            self._forget_over_limit_memories()
        except Exception:
            pass

        cols = self._mem_cols()
        where = "character_id=? AND is_deleted=0"
        params = [self.storage_key]
        if "is_forgotten" in cols:
            where += " AND is_forgotten=0"

        with self.db.connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                f"""
                SELECT eternal_id, date_created, priority, content, type
                FROM memories
                WHERE {where}
                """,
                tuple(params),
            )
            rows = cursor.fetchall() or []

        def _dt_score(s: str) -> float:
            dt = self._parse_dt(s)
            if dt == datetime.datetime.min:
                return -1e18
            try:
                return dt.timestamp()
            except Exception:
                return -1e18

        fact_rows = [r for r in rows if not is_island(r[4])]

        # Safety dedup: newest row wins for each island type.
        island_by_type = {}
        for row in rows:
            if not is_island(row[4]):
                continue
            key = str(row[4] or "").strip().lower()
            previous = island_by_type.get(key)
            if previous is None or (_dt_score(row[1]), int(row[0] or 0)) > (
                _dt_score(previous[1]), int(previous[0] or 0)
            ):
                island_by_type[key] = row

        island_order = {make_island_type(t): i for i, t in enumerate(_ISLAND_TYPES)}
        island_rows = sorted(
            island_by_type.values(),
            key=lambda r: (island_order.get(str(r[4] or "").lower(), len(island_order)), str(r[4] or "")),
        )
        facts_sorted = sorted(
            fact_rows,
            key=lambda r: (
                -self._priority_rank_for_forget(r[2]),
                -_dt_score(r[1]),
                int(r[0] or 0),
            ),
        )

        cap = self._get_memory_capacity()
        risk_n = min(len(facts_sorted), max(5, int(round(cap * 0.2))))
        if len(facts_sorted) <= risk_n:
            risk_n = len(facts_sorted)
        risk_start_idx = max(0, len(facts_sorted) - risk_n)

        formatted_facts = []
        for i, (mid, date, prio, content, mtype) in enumerate(facts_sorted):
            risk_tag = "[RISK] " if i >= risk_start_idx else ""
            tpl = summary_tpl if mtype == "summary" else item_tpl
            priority_cap = (prio or "normal").capitalize()
            date_short = (((date or "")[:5] + " " + (date or "")[11:16]).strip()) if date else "?"
            try:
                formatted_facts.append(tpl.format(
                    risk_tag=risk_tag, id=mid, date=date, date_short=date_short,
                    priority=prio, priority_cap=priority_cap,
                    content=content, type=mtype,
                ))
            except (KeyError, IndexError):
                formatted_facts.append(f"{risk_tag}N:{mid} [{priority_cap}] {date_short}: {content}")

        formatted_islands = []
        for mid, date, prio, content, mtype in island_rows:
            sub = island_subtype(mtype) or str(mtype or "").removeprefix(_ISLAND_PREFIX)
            island_type_cap = sub.replace("_", " ").title()
            date_short = (((date or "")[:5] + " " + (date or "")[11:16]).strip()) if date else "?"
            try:
                formatted_islands.append(island_item_tpl.format(
                    id=mid, date=date, date_short=date_short,
                    priority=prio, content=content, type=mtype,
                    island_type=sub, island_type_cap=island_type_cap,
                ))
            except (KeyError, IndexError):
                formatted_islands.append(f"[{island_type_cap}] N:{mid} {date_short}: {content}")

        memory_stats = (
            f"\nMemory status: {len(fact_rows)}/{cap} facts"
            + (f" + {len(island_rows)} islands" if island_rows else "")
            + f", {self.total_characters} characters"
        )

        management_tips = []
        if risk_n > 0:
            management_tips.append(
                f"Risk zone: last {risk_n} memories are most likely to be forgotten next (based on priority+age)."
            )
        if self.total_characters > 10000:
            management_tips.append("CRITICAL: Memory limit exceeded!")
        elif self.total_characters > 5000:
            management_tips.append("WARNING: Memory size is large.")
        if len(fact_rows) > 75:
            management_tips.append("Too many memories!")

        examples = [
            "Memory ops (JSON response fields):",
            'memory_add: ["high|content"]        — add (low/normal/high/critical)',
            'memory_update: ["4|new text"]       — replace N:4 content',
            'memory_delete: ["2"]                — delete N:2; range: "3-7"; multi: "2,5"',
            'memory_merge: ["3,7,12:merged text"] — merge into first ID; rest deleted; content optional',
            'memory_add: ["island:relationship|summary"] — replace one running island',
            "Use English to save tokens.",
        ]

        island_block = None
        if formatted_islands:
            islands_text = "\n".join(formatted_islands)
            try:
                island_block = island_wrapper_tpl.format(items=islands_text)
            except (KeyError, IndexError):
                island_block = f"<memory_islands>\n{islands_text}\n</memory_islands>"

        facts_text = "\n".join(formatted_facts)
        tips_text = "\n".join(management_tips)
        examples_text = "\n".join(examples)
        try:
            active_block = wrapper_tpl.format(
                items=facts_text, stats=memory_stats, tips=tips_text, examples=examples_text,
            )
        except (KeyError, IndexError):
            active_block = f"<active_memory>\n{facts_text}\n</active_memory>"
        # Статус/подсказки — трейлер к активной памяти (не к островам).
        active_block += f"\n{memory_stats}\n{tips_text}\n{examples_text}"

        blocks = []
        if island_block:
            blocks.append(island_block)
        blocks.append(active_block)
        return blocks
