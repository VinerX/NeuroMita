import logging
import datetime
from managers.database_manager import DatabaseManager
from managers.rag_manager import RAGManager


class MemoryManager:
    def __init__(self, character_name):
        self.character_name = character_name  # В новой логике это character_id
        self.db = DatabaseManager()
        self.total_characters = 0
        self._calculate_total_characters()
        self.rag = RAGManager(self.character_name)

    def _calculate_total_characters(self):
        """Считаем символы SQL запросом"""
        conn = self.db.get_connection()
        cursor = conn.cursor()
        cursor.execute(
            "SELECT SUM(LENGTH(content)) FROM memories WHERE character_id = ? AND is_deleted = 0",
            (self.character_name,)
        )
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
        if date is None:
            date = datetime.datetime.now().strftime("%d.%m.%Y %H:%M:%S")

        conn = self.db.get_connection()
        cursor = conn.cursor()

        # 1. Вычисляем новый Eternal ID (Max + 1)
        cursor.execute(
            "SELECT MAX(eternal_id) FROM memories WHERE character_id = ?",
            (self.character_name,)
        )
        res = cursor.fetchone()[0]
        new_id = (res + 1) if res is not None else 1

        # 2. Вставляем
        cursor.execute('''
            INSERT INTO memories (character_id, eternal_id, content, priority, type, date_created, is_deleted)
            VALUES (?, ?, ?, ?, ?, ?, 0)
        ''', (self.character_name, new_id, content, priority, memory_type, date))

        conn.commit()
        conn.close()

        self.total_characters += len(content)
        self.rag.update_memory_embedding(new_id, content)

        # logging.info(f"Memory added for {self.character_name}, ID: {new_id}")

    def update_memory(self, number, content, priority=None):
        conn = self.db.get_connection()
        cursor = conn.cursor()

        # Сначала получим старую длину для коррекции счетчика
        cursor.execute(
            "SELECT content FROM memories WHERE character_id = ? AND eternal_id = ? AND is_deleted = 0",
            (self.character_name, number)
        )
        row = cursor.fetchone()

        if not row:
            conn.close()
            return False

        old_len = len(row[0])

        # Обновляем
        if priority:
            cursor.execute('''
                UPDATE memories SET content = ?, priority = ?, date_created = ?
                WHERE character_id = ? AND eternal_id = ?
            ''', (content, priority, datetime.datetime.now().strftime("%d.%m.%Y %H:%M:%S"), self.character_name, number))
        else:
            cursor.execute('''
                UPDATE memories SET content = ?, date_created = ?
                WHERE character_id = ? AND eternal_id = ?
            ''', (content, datetime.datetime.now().strftime("%d.%m.%Y %H:%M:%S"), self.character_name, number))

        conn.commit()
        conn.close()

        self.total_characters = self.total_characters - old_len + len(content)

        self.rag.update_memory_embedding(number, content)

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
            "SELECT content FROM memories WHERE character_id = ? AND eternal_id = ? AND is_deleted = 0",
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
            WHERE character_id = ? AND is_deleted = 0 
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