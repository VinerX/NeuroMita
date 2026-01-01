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