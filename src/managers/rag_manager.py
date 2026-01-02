import sqlite3
import numpy as np
import json
import struct
from typing import List, Dict, Any, Optional

from managers.database_manager import DatabaseManager
from handlers.embedding_handler import EmbeddingModelHandler, QUERY_PREFIX
from core.events import get_event_bus, Events
from main_logger import logger


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
        Ищет самые похожие записи в memories и history.
        threshold - минимальный порог схожести (0..1), чтобы не тащить мусор.
        """
        query_vec = self._get_embedding(query, use_event_bus=True)
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

        Для эффективности здесь используем прямой доступ к Singleton handler (без EventBus на каждую запись),
        но Singleton уже будет прогрет EmbeddingController'ом при наличии.
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