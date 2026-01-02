import logging
import datetime
from typing import Optional, Tuple, List, Set

from managers.database_manager import DatabaseManager
from managers.rag_manager import RAGManager
from managers.settings_manager import SettingsManager


class MemoryManager:
    """
    Концепция:
    - Активные воспоминания: is_deleted=0 AND is_forgotten=0  (это попадает в промпт целиком в пределах лимита)
    - Забытая память: is_forgotten=1 (не попадает в промпт, но может быть найдена RAG)
    - Ручное удаление: is_deleted=1 (не используется нигде)
    """

    def __init__(self, character_name: str):
        self.character_name = character_name  # фактически это character_id
        self.db = DatabaseManager()

        # гарантируем колонку is_forgotten, но не падаем если не получилось
        self._ensure_memories_schema()

        self.total_characters = 0
        self._calculate_total_characters()

        # RAG опционален
        try:
            self.rag = RAGManager(self.character_name)
        except Exception as e:
            logging.warning(f"RAGManager init failed (RAG disabled for this session): {e}", exc_info=True)
            self.rag = None

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
        """
        Пытаемся добавить колонку is_forgotten, если её нет.
        Не падаем вообще никогда.
        """
        try:
            cols = self._mem_cols()
            if "is_forgotten" in cols:
                return

            # если у тебя есть DatabaseManager.ensure_columns — используем его
            if hasattr(self.db, "ensure_columns"):
                try:
                    self.db.ensure_columns("memories", [("is_forgotten", "INTEGER DEFAULT 0")])
                except Exception:
                    pass

            # перепроверим (на случай, если ensure_columns нет/не сработал)
            cols2 = self._mem_cols()
            if "is_forgotten" not in cols2:
                logging.warning("[MemoryManager] Column memories.is_forgotten is missing; forget mechanism will be disabled.")
        except Exception:
            # вообще ничего не делаем
            pass

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
            params = [self.character_name]
            if "is_forgotten" in cols:
                where += " AND is_forgotten=0"
            cur.execute(f"SELECT SUM(LENGTH(content)) FROM memories WHERE {where}", tuple(params))
            result = cur.fetchone()[0]
            self.total_characters = int(result) if result else 0
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
        self._ensure_memories_schema()
        cols = self._mem_cols()
        if "is_forgotten" not in cols:
            return  # без колонки корректно забывать нельзя

        cap = self._get_memory_capacity()

        conn = self.db.get_connection()
        try:
            cur = conn.cursor()

            # сколько активных сейчас
            cur.execute(
                "SELECT COUNT(*) FROM memories WHERE character_id=? AND is_deleted=0 AND is_forgotten=0",
                (self.character_name,),
            )
            active_count = int(cur.fetchone()[0] or 0)

            # Нам нужно, чтобы ДО добавления новой памяти было active_count < cap
            # То есть забываем need = active_count - (cap - 1)
            need = active_count - (cap - 1)
            if need <= 0:
                return

            # Собираем всех кандидатов (Critical нельзя)
            cur.execute(
                """
                SELECT id, eternal_id, priority, date_created, content
                FROM memories
                WHERE character_id=? AND is_deleted=0 AND is_forgotten=0
                """,
                (self.character_name,),
            )
            rows = cur.fetchall() or []

            candidates: List[Tuple[int, int, str, str, str]] = []
            for rid, eid, prio, dt, content in rows:
                if str(prio or "").strip().lower() == "critical":
                    continue
                candidates.append((int(rid), int(eid or 0), str(prio or "Normal"), str(dt or ""), str(content or "")))

            if not candidates:
                logging.warning(
                    f"[MemoryManager] MEMORY_CAPACITY={cap}, but no non-critical memories to forget. "
                    f"Active={active_count} (cannot prune)."
                )
                return

            # Сортировка как при выбывании: Low->Normal->High, затем самый старый
            candidates.sort(
                key=lambda x: (self._priority_rank_for_forget(x[2]), self._parse_dt(x[3]), x[0])
            )

            victims = candidates[:need]
            victim_ids = [(v[0],) for v in victims]

            # Помечаем забытыми
            cur.executemany("UPDATE memories SET is_forgotten=1 WHERE id=?", victim_ids)
            conn.commit()

            # Обновим total_characters: убираем только тех, кого забыли сейчас (они были активными)
            removed_chars = 0
            for _, _, _, _, content in victims:
                removed_chars += len(content or "")
            try:
                self.total_characters = max(0, int(self.total_characters) - int(removed_chars))
            except Exception:
                self._calculate_total_characters()

            for _, victim_eid, victim_prio, victim_dt, _ in victims:
                logging.info(
                    f"[MemoryManager] Forgot memory eternal_id={victim_eid} (priority={victim_prio}, date={victim_dt})"
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

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def load_memories(self):
        self._calculate_total_characters()

    def save_memories(self):
        pass

    def add_memory(self, content, date=None, priority="Normal", memory_type="fact"):
        # забываем ПЕРЕД добавлением новой
        self._forget_over_limit_memories()

        if date is None:
            date = datetime.datetime.now().strftime("%d.%m.%Y %H:%M:%S")

        conn = self.db.get_connection()
        try:
            cursor = conn.cursor()

            cursor.execute(
                "SELECT MAX(eternal_id) FROM memories WHERE character_id = ?",
                (self.character_name,)
            )
            res = cursor.fetchone()[0]
            new_id = (res + 1) if res is not None else 1

            cols = self._mem_cols()

            insert_cols = ["character_id", "eternal_id", "content", "priority", "type", "date_created", "is_deleted"]
            insert_vals = [self.character_name, new_id, content, priority, memory_type, date, 0]

            if "is_forgotten" in cols:
                insert_cols.append("is_forgotten")
                insert_vals.append(0)

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
        if self.rag:
            try:
                self.rag.update_memory_embedding(new_id, content)
            except Exception as e:
                logging.warning(f"RAG failed to update memory embedding (ignored): {e}", exc_info=True)

    def update_memory(self, number, content, priority=None):
        """
        Обновляем только активные (не забытые) как и раньше.
        Если захочешь — можно расширить на забытые, но это уже другой UX.
        """
        cols = self._mem_cols()
        where = "character_id=? AND eternal_id=? AND is_deleted=0"
        params = [self.character_name, number]
        if "is_forgotten" in cols:
            where += " AND is_forgotten=0"

        conn = self.db.get_connection()
        try:
            cursor = conn.cursor()
            cursor.execute(f"SELECT content FROM memories WHERE {where}", tuple(params))
            row = cursor.fetchone()
            if not row:
                return False

            old_len = len(row[0] or "")

            if priority:
                cursor.execute(
                    """
                    UPDATE memories SET content=?, priority=?, date_created=?
                    WHERE character_id=? AND eternal_id=?
                    """,
                    (content, priority, datetime.datetime.now().strftime("%d.%m.%Y %H:%M:%S"), self.character_name, number)
                )
            else:
                cursor.execute(
                    """
                    UPDATE memories SET content=?, date_created=?
                    WHERE character_id=? AND eternal_id=?
                    """,
                    (content, datetime.datetime.now().strftime("%d.%m.%Y %H:%M:%S"), self.character_name, number)
                )

            conn.commit()

            # обновим символы (только активные)
            self.total_characters = self.total_characters - old_len + len(str(content or ""))

        finally:
            try:
                conn.close()
            except Exception:
                pass

        if self.rag:
            try:
                self.rag.update_memory_embedding(number, content)
            except Exception as e:
                logging.warning(f"RAG failed to update memory embedding (ignored): {e}", exc_info=True)

        return True

    def delete_memory(self, number, save_as_missing=False):
        """
        Ручное удаление (is_deleted=1) — должно работать и для забытых тоже.
        Поэтому НЕ фильтруем по is_forgotten при поиске.
        """
        cols = self._mem_cols()

        conn = self.db.get_connection()
        try:
            cursor = conn.cursor()

            select_cols = ["content"]
            if "is_forgotten" in cols:
                select_cols.append("is_forgotten")

            cursor.execute(
                f"SELECT {', '.join(select_cols)} FROM memories WHERE character_id=? AND eternal_id=? AND is_deleted=0",
                (self.character_name, number)
            )
            row = cursor.fetchone()
            if not row:
                logging.warning(f"Memory {number} not found for deletion.")
                return False

            if "is_forgotten" in cols:
                content, is_forgotten = row[0], int(row[1] or 0)
            else:
                content, is_forgotten = row[0], 0

            cursor.execute(
                "UPDATE memories SET is_deleted=1 WHERE character_id=? AND eternal_id=?",
                (self.character_name, number)
            )
            conn.commit()

            # уменьшаем счётчик только если удалили активную
            if ("is_forgotten" in cols) and (is_forgotten == 0):
                self.total_characters = max(0, self.total_characters - len(content or ""))
            elif "is_forgotten" not in cols:
                # старая схема — считаем что активная
                self.total_characters = max(0, self.total_characters - len(content or ""))

            logging.info(f"Memory {number} deleted (soft delete).")
            return True
        finally:
            try:
                conn.close()
            except Exception:
                pass

    def clear_memories(self):
        conn = self.db.get_connection()
        try:
            cursor = conn.cursor()
            cursor.execute("UPDATE memories SET is_deleted=1 WHERE character_id=?", (self.character_name,))
            conn.commit()
        finally:
            try:
                conn.close()
            except Exception:
                pass
        self.total_characters = 0

    def get_memories_formatted(self):
        """
        Показываем ВСЕ активные воспоминания (is_deleted=0 AND is_forgotten=0).

        Порядок:
        - ВВЕРХУ: самые важные (Critical/High) и более свежие
        - ВНИЗУ: те, кто пойдут на забывание первыми (Low/старые)

        [RISK] помечаем ХВОСТ списка (самые вероятные кандидаты на забывание).
        """
        cols = self._mem_cols()

        where = "character_id=? AND is_deleted=0"
        params = [self.character_name]
        if "is_forgotten" in cols:
            where += " AND is_forgotten=0"

        conn = self.db.get_connection()
        try:
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
        finally:
            try:
                conn.close()
            except Exception:
                pass

        # Сортируем по "важности удержания" (обратная сортировке на забывание):
        # - выше priority => выше
        # - более новый date_created => выше
        #
        # Используем существующий self._priority_rank_for_forget:
        # Low=0, Normal=1, High=2, Critical=999.
        # Чтобы "важное вверх" при обычной сортировке (ascending), делаем -rank.
        def _dt_score(s: str) -> float:
            dt = self._parse_dt(s)
            if dt == datetime.datetime.min:
                return -1e18
            try:
                return dt.timestamp()
            except Exception:
                return -1e18

        rows_sorted = sorted(
            rows,
            key=lambda r: (
                -self._priority_rank_for_forget(r[2]),  # важные выше
                -_dt_score(r[1]),  # свежие выше
                int(r[0] or 0),  # стабильность
            )
        )

        cap = self._get_memory_capacity()
        risk_n = min(len(rows_sorted), max(5, int(round(cap * 0.2))))
        if len(rows_sorted) <= risk_n:
            risk_n = len(rows_sorted)

        risk_start_idx = max(0, len(rows_sorted) - risk_n)

        formatted_memories = []
        for i, (mid, date, prio, content, mtype) in enumerate(rows_sorted):
            risk_tag = "[RISK] " if i >= risk_start_idx else ""
            if mtype == "summary":
                formatted_memories.append(f"{risk_tag}N:{mid}, Date {date}, Type: Summary: {content}")
            else:
                formatted_memories.append(f"{risk_tag}N:{mid}, Date {date}, Priority: {prio}: {content}")

        memory_stats = f"\nMemory status: {len(rows_sorted)} facts, {self.total_characters} characters"

        management_tips = []
        if risk_n > 0:
            management_tips.append(
                f"Risk zone: last {risk_n} memories are most likely to be forgotten next (based on priority+age)."
            )

        if self.total_characters > 10000:
            management_tips.append("CRITICAL: Memory limit exceeded!")
        elif self.total_characters > 5000:
            management_tips.append("WARNING: Memory size is large.")

        if len(rows_sorted) > 75:
            management_tips.append("Too many memories!")

        examples = [
            "Example of memory commands:",
            "<-memory>2</memory>",
            "<+memory>high|content</memory>",
            "<#memory>4|low|content</memory>"
        ]

        full_message = (
                "LongMemory< " +
                "\n".join(formatted_memories) +
                " >EndLongMemory\n" +
                memory_stats + "\n" +
                "\n".join(management_tips) + "\n" +
                "\n".join(examples)
        )
        return full_message