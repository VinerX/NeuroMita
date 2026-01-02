import logging
import datetime
from managers.database_manager import DatabaseManager
from managers.rag_manager import RAGManager
from managers.settings_manager import SettingsManager
from typing import Optional, Tuple, List

class MemoryManager:
    def __init__(self, character_name):
        self.character_name = character_name  # В новой логике это character_id
        self.db = DatabaseManager()
        self.total_characters = 0
        self._calculate_total_characters()

        # RAG опционален
        try:
            self.rag = RAGManager(self.character_name)
        except Exception as e:
            logging.warning(f"RAGManager init failed (RAG disabled for this session): {e}", exc_info=True)
            self.rag = None

    def _get_memory_capacity(self) -> int:
        """
        Максимум "активных" (не удалённых и не забытых) memories для персонажа.
        """
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
        # поддерживаем пару форматов из проекта
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
        Low < Normal < High. Critical исключаем вообще.
        """
        p = str(prio or "Normal").strip().lower()
        if p == "low":
            return 0
        if p == "high":
            return 2
        if p == "critical":
            return 999
        return 1  # Normal/unknown

    def _prune_one_if_needed(self) -> None:
        cap = self._get_memory_capacity()
        conn = self.db.get_connection()
        try:
            cur = conn.cursor()
            cur.execute(
                "SELECT COUNT(*) FROM memories WHERE character_id=? AND is_deleted=0 AND is_forgotten=0",
                (self.character_name,),
            )
            active_count = int(cur.fetchone()[0] or 0)
            if active_count < cap:
                return

            # кандидаты на "забыть" (Critical нельзя)
            cur.execute(
                """
                SELECT id, eternal_id, priority, date_created
                FROM memories
                WHERE character_id=? AND is_deleted=0 AND is_forgotten=0
                """,
                (self.character_name,),
            )
            rows = cur.fetchall() or []
            candidates: List[Tuple[int, int, str, str]] = []
            for rid, eid, prio, dt in rows:
                if str(prio or "").strip().lower() == "critical":
                    continue
                candidates.append((int(rid), int(eid or 0), str(prio or "Normal"), str(dt or "")))

            if not candidates:
                logging.warning(
                    f"[MemoryManager] MEMORY_CAPACITY reached ({cap}), but no non-critical memories to forget."
                )
                return

            # сортировка: Low->Normal->High, затем самый старый
            candidates.sort(
                key=lambda x: (self._priority_rank_for_forget(x[2]), self._parse_dt(x[3]), x[0])
            )
            victim_id, victim_eid, victim_prio, victim_dt = candidates[0]

            cur.execute("UPDATE memories SET is_forgotten=1 WHERE id=?", (victim_id,))
            conn.commit()
            logging.info(
                f"[MemoryManager] Forgot memory eternal_id={victim_eid} (priority={victim_prio}, date={victim_dt})"
            )
        finally:
            try:
                conn.close()
            except Exception:
                pass

    def _mem_cols(self) -> set[str]:
        # читаем фактическую схему (и не падаем)
        try:
            return self.db.get_table_columns("memories")
        except Exception:
            return set()

    def _calculate_total_characters(self):
        """Считаем символы SQL запросом"""
        cols = self._mem_cols()
        conn = self.db.get_connection()
        cursor = conn.cursor()
        where = "character_id = ? AND is_deleted = 0"
        if "is_forgotten" in cols:
            where += " AND is_forgotten = 0"
        cursor.execute(f"SELECT SUM(LENGTH(content)) FROM memories WHERE {where}", (self.character_name,))
        result = cursor.fetchone()[0]
        self.total_characters = result if result else 0
        conn.close()

    def load_memories(self):
        # В SQL версии явная загрузка не нужна, данные всегда там.
        # Но обновляем счетчик для верности.
        self._calculate_total_characters()

    def save_memories(self):
        # Пустышка для совместимости
        pass

    def add_memory(self, content, date=None, priority="Normal", memory_type="fact"):
        self._prune_one_if_needed()
        if date is None:
            date = datetime.datetime.now().strftime("%d.%m.%Y %H:%M:%S")

        # Пробуем обеспечить колонку и сделать pruning безопасно
        try:
            self.db.ensure_columns("memories", [("is_forgotten", "INTEGER DEFAULT 0")])
        except Exception:
            pass
        self._prune_if_needed_safe()

        conn = self.db.get_connection()
        cursor = conn.cursor()

        cursor.execute(
            "SELECT MAX(eternal_id) FROM memories WHERE character_id = ?",
            (self.character_name,)
        )
        res = cursor.fetchone()[0]
        new_id = (res + 1) if res is not None else 1

        cols = self._mem_cols()
        # Динамический INSERT: если is_forgotten колонки нет — не вставляем её.
        insert_cols = ["character_id", "eternal_id", "content", "priority", "type", "date_created", "is_deleted"]
        insert_vals = [self.character_name, new_id, content, priority, memory_type, date, 0]

        if "is_forgotten" in cols:
            insert_cols.append("is_forgotten")
            insert_vals.append(0)

        placeholders = ",".join(["?"] * len(insert_cols))
        sql = f"INSERT INTO memories ({', '.join(insert_cols)}) VALUES ({placeholders})"
        cursor.execute(sql, tuple(insert_vals))

        conn.commit()
        conn.close()

        self.total_characters += len(content)

        # RAG опционален и не должен валить основной флоу
        if self.rag:
            try:
                self.rag.update_memory_embedding(new_id, content)
            except Exception as e:
                logging.warning(f"RAG failed to update memory embedding (ignored): {e}", exc_info=True)

    def _prune_if_needed_safe(self) -> None:
        """
        Forget mechanism (Phase 2), но:
        - если колонки is_forgotten реально нет и не смогли добавить -> НЕ падаем
        """
        cols = self._mem_cols()
        if "is_forgotten" not in cols:
            # не можем забывать корректно без колонки — лучше пропустить, чем падать
            return

        try:
            capacity = int(SettingsManager.get("MEMORY_CAPACITY", 50))
            capacity = max(1, capacity)
        except Exception:
            capacity = 50

        conn = self.db.get_connection()
        try:
            cur = conn.cursor()
            cur.execute(
                "SELECT COUNT(*) FROM memories WHERE character_id=? AND is_deleted=0 AND is_forgotten=0",
                (self.character_name,),
            )
            active = int(cur.fetchone()[0] or 0)
            if active < capacity:
                return

            # выбираем жертву: Critical нельзя, Low умирает первым, затем Normal, затем High, потом самый старый
            cur.execute(
                """
                SELECT id, eternal_id, priority, date_created
                FROM memories
                WHERE character_id=? AND is_deleted=0 AND is_forgotten=0
                """,
                (self.character_name,),
            )
            rows = cur.fetchall() or []

            def prio_rank(p: str) -> int:
                pl = str(p or "Normal").strip().lower()
                if pl == "critical":
                    return 999
                if pl == "low":
                    return 0
                if pl == "high":
                    return 2
                return 1

            def parse_dt(s: str) -> datetime.datetime:
                raw = str(s or "").strip()
                for f in ("%d.%m.%Y %H:%M:%S", "%d.%m.%Y_%H.%M", "%d.%m.%Y %H:%M"):
                    try:
                        return datetime.datetime.strptime(raw, f)
                    except Exception:
                        pass
                return datetime.datetime.min

            candidates = []
            for rid, eid, prio, dt in rows:
                if str(prio or "").strip().lower() == "critical":
                    continue
                candidates.append((int(rid), int(eid or 0), str(prio or "Normal"), str(dt or "")))

            if not candidates:
                return

            candidates.sort(key=lambda x: (prio_rank(x[2]), parse_dt(x[3]), x[0]))
            victim_id, victim_eid, victim_prio, victim_dt = candidates[0]

            cur.execute("UPDATE memories SET is_forgotten=1 WHERE id=?", (victim_id,))
            conn.commit()
            logging.info(
                f"[MemoryManager] Forgot memory eternal_id={victim_eid} (priority={victim_prio}, date={victim_dt})"
            )
        except Exception as e:
            logging.warning(f"[MemoryManager] prune failed (ignored): {e}", exc_info=True)
        finally:
            try:
                conn.close()
            except Exception:
                pass

    def update_memory(self, number, content, priority=None):
        conn = self.db.get_connection()
        cursor = conn.cursor()

        cursor.execute(
            "SELECT content FROM memories WHERE character_id = ? AND eternal_id = ? AND is_deleted = 0 AND is_forgotten = 0",
            (self.character_name, number)
        )
        row = cursor.fetchone()

        if not row:
            conn.close()
            return False

        old_len = len(row[0])

        if priority:
            cursor.execute(
                '''
                UPDATE memories SET content = ?, priority = ?, date_created = ?
                WHERE character_id = ? AND eternal_id = ?
                ''',
                (content, priority, datetime.datetime.now().strftime("%d.%m.%Y %H:%M:%S"), self.character_name, number)
            )
        else:
            cursor.execute(
                '''
                UPDATE memories SET content = ?, date_created = ?
                WHERE character_id = ? AND eternal_id = ?
                ''',
                (content, datetime.datetime.now().strftime("%d.%m.%Y %H:%M:%S"), self.character_name, number)
            )

        conn.commit()
        conn.close()

        self.total_characters = self.total_characters - old_len + len(content)

        # RAG опционален и не должен валить основной флоу
        if self.rag:
            try:
                self.rag.update_memory_embedding(number, content)
            except Exception as e:
                logging.warning(f"RAG failed to update memory embedding (ignored): {e}", exc_info=True)

        return True

    def delete_memory(self, number, save_as_missing=False):
        """
        В SQL версии save_as_missing по сути не нужен,
        так как мы просто ставим is_deleted=1, и данные остаются в базе.
        Но флаг is_deleted=1 как раз и выполняет роль 'missed'.
        """
        conn = self.db.get_connection()
        cursor = conn.cursor()

        cursor.execute(
            "SELECT content FROM memories WHERE character_id = ? AND eternal_id = ? AND is_deleted = 0 AND is_forgotten = 0",
            (self.character_name, number)
        )
        row = cursor.fetchone()

        if not row:
            conn.close()
            logging.warning(f"Memory {number} not found for deletion.")
            return False

        # Soft Delete
        cursor.execute(
            "UPDATE memories SET is_deleted = 1 WHERE character_id = ? AND eternal_id = ?",
            (self.character_name, number)
        )
        conn.commit()
        conn.close()

        self.total_characters -= len(row[0])
        logging.info(f"Memory {number} deleted (soft delete).")
        return True

    def clear_memories(self):
        # Удаляем (soft delete) всё
        conn = self.db.get_connection()
        cursor = conn.cursor()
        cursor.execute(
            "UPDATE memories SET is_deleted = 1 WHERE character_id = ?",
            (self.character_name,)
        )
        conn.commit()
        conn.close()
        self.total_characters = 0

    def get_memories_formatted(self):
        conn = self.db.get_connection()
        cursor = conn.cursor()

        cursor.execute('''
            SELECT eternal_id, date_created, priority, content, type 
            FROM memories 
            WHERE character_id = ? AND is_deleted = 0 AND is_forgotten = 0
            ORDER BY eternal_id ASC
        ''', (self.character_name,))

        rows = cursor.fetchall()
        conn.close()

        formatted_memories = []
        for r in rows:
            mid, date, prio, content, mtype = r
            if mtype == "summary":
                formatted_memories.append(f"N:{mid}, Date {date}, Type: Summary: {content}")
            else:
                formatted_memories.append(f"N:{mid}, Date {date}, Priority: {prio}: {content}")

        memory_stats = f"\nMemory status: {len(rows)} facts, {self.total_characters} characters"

        # Правила (копируем из старого кода)
        management_tips = []
        if self.total_characters > 10000:
            management_tips.append("CRITICAL: Memory limit exceeded!")
        elif self.total_characters > 5000:
            management_tips.append("WARNING: Memory size is large.")

        if len(rows) > 75:
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