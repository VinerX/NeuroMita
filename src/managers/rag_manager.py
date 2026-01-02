import sqlite3
import numpy as np
import json
import struct
from typing import List, Dict, Any
from managers.database_manager import DatabaseManager
from handlers.embedding_handler import EmbeddingModelHandler
from main_logger import logger


class RAGManager:
    def __init__(self, character_id: str):
        self.character_id = character_id
        self.db = DatabaseManager()
        # Инициализируем модель (она синглтон или легкая, судя по твоему коду)
        self.embedder = EmbeddingModelHandler()

    def _blob_to_array(self, blob) -> np.ndarray:
        """Конвертирует BLOB из SQLite обратно в numpy array"""
        if not blob:
            return None
        # float32 занимает 4 байта.
        return np.frombuffer(blob, dtype=np.float32)

    def _array_to_blob(self, array: np.ndarray) -> bytes:
        """Конвертирует numpy array в байты для сохранения"""
        return array.astype(np.float32).tobytes()

    def update_memory_embedding(self, eternal_id: int, text: str):
        """Создает и сохраняет эмбеддинг для воспоминания"""
        vector = self.embedder.get_embedding(text)
        if vector is None:
            return

        blob = self._array_to_blob(vector)
        conn = self.db.get_connection()
        conn.execute(
            "UPDATE memories SET embedding = ? WHERE character_id = ? AND eternal_id = ?",
            (blob, self.character_id, eternal_id)
        )
        conn.commit()
        conn.close()

    def update_history_embedding(self, msg_id: int, text: str):
        """Создает и сохраняет эмбеддинг для сообщения истории"""
        vector = self.embedder.get_embedding(text)
        if vector is None:
            return

        blob = self._array_to_blob(vector)
        conn = self.db.get_connection()
        conn.execute(
            "UPDATE history SET embedding = ? WHERE id = ?",
            (blob, msg_id)
        )
        conn.commit()
        conn.close()

    def search_relevant(self, query: str, limit: int = 5, threshold: float = 0.4) -> List[Dict[str, Any]]:
        """
        Ищет самые похожие записи в memories и history.
        threshold - минимальный порог схожести (0..1), чтобы не тащить мусор.
        """
        query_vec = self.embedder.get_embedding(query)
        if query_vec is None:
            return []

        conn = self.db.get_connection()
        cursor = conn.cursor()

        results = []

        # 1. Загружаем воспоминания (Memories)
        cursor.execute(
            "SELECT eternal_id, content, embedding, type FROM memories WHERE character_id = ? AND is_deleted = 0 AND embedding IS NOT NULL",
            (self.character_id,)
        )
        rows = cursor.fetchall()

        for r in rows:
            eternal_id, content, blob, mtype = r
            vec = self._blob_to_array(blob)
            score = np.dot(query_vec, vec)  # Cosine similarity (если вектора нормализованы)

            if score >= threshold:
                results.append({
                    "source": "memory",
                    "id": eternal_id,
                    "content": content,
                    "score": float(score),
                    "type": mtype
                })

        # 2. Загружаем историю (History) - только старую, не активную в текущем окне
        # (Опционально: можно искать по всей истории)
        cursor.execute(
            "SELECT role, content, embedding, timestamp FROM history WHERE character_id = ? AND embedding IS NOT NULL AND is_active = 0",
            (self.character_id,)
        )
        rows = cursor.fetchall()

        for r in rows:
            role, content, blob, ts = r
            vec = self._blob_to_array(blob)
            score = np.dot(query_vec, vec)

            if score >= threshold:
                results.append({
                    "source": "history",
                    "role": role,
                    "content": content,
                    "score": float(score),
                    "date": ts
                })

        conn.close()

        # Сортируем по score (от большего к меньшему) и берем топ
        results.sort(key=lambda x: x["score"], reverse=True)
        return results[:limit]

    def index_all_missing(self, progress_callback=None) -> int:
        """
        Проходит по всем записям без вектора и генерирует его.
        progress_callback(current, total) - для обновления UI
        Возвращает количество обновленных записей.
        """
        conn = self.db.get_connection()
        cursor = conn.cursor()

        # 1. Собираем ID для обновления
        # История
        cursor.execute('''
              SELECT id, content FROM history 
              WHERE character_id = ? AND embedding IS NULL AND content != "" AND content IS NOT NULL
          ''', (self.character_id,))
        hist_rows = cursor.fetchall()

        # Воспоминания
        cursor.execute('''
              SELECT eternal_id, content FROM memories 
              WHERE character_id = ? AND embedding IS NULL AND is_deleted = 0
          ''', (self.character_id,))
        mem_rows = cursor.fetchall()

        total = len(hist_rows) + len(mem_rows)
        if total == 0:
            conn.close()
            return 0

        processed = 0

        try:
            # Обработка истории
            for row in hist_rows:
                row_id, content = row
                # Генерируем вектор
                # (предполагаем, что контент - строка, если JSON - надо парсить, но обычно там строка или JSON-string)
                if content and isinstance(content, str):
                    # Простая эвристика: если это JSON мультимодальности, берем только текст
                    if content.strip().startswith('[') or content.strip().startswith('{'):
                        # Тут можно добавить логику извлечения текста из JSON, если хранится JSON
                        # Для простоты пока берем как есть, эмбеддер обрежет или обработает
                        pass

                    vec = self.embedder.get_embedding(content)
                    if vec is not None:
                        blob = self._array_to_blob(vec)
                        cursor.execute("UPDATE history SET embedding = ? WHERE id = ?", (blob, row_id))

                processed += 1
                if progress_callback:
                    progress_callback(processed, total)

            conn.commit()  # Промежуточный коммит

            # Обработка воспоминаний
            for row in mem_rows:
                eternal_id, content = row
                if content:
                    vec = self.embedder.get_embedding(content)
                    if vec is not None:
                        blob = self._array_to_blob(vec)
                        cursor.execute("UPDATE memories SET embedding = ? WHERE character_id = ? AND eternal_id = ?",
                                       (blob, self.character_id, eternal_id))

                processed += 1
                if progress_callback:
                    progress_callback(processed, total)

            conn.commit()

        except Exception as e:
            logger.error(f"Error during re-indexing: {e}", exc_info=True)
        finally:
            conn.close()

        return processed