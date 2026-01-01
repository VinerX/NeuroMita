import sys
import os
import sqlite3
import numpy as np
import time


from managers.database_manager import DatabaseManager
from handlers.embedding_handler import EmbeddingModelHandler
from main_logger import logger


def array_to_blob(array: np.ndarray) -> bytes:
    """Конвертирует numpy array в байты (float32)"""
    return array.astype(np.float32).tobytes()


def ensure_schema(conn):
    """Гарантирует, что колонки embedding существуют"""
    cursor = conn.cursor()

    tables = ["memories", "history"]
    for table in tables:
        try:
            # Проверяем, есть ли колонка
            cursor.execute(f"PRAGMA table_info({table})")
            columns = [info[1] for info in cursor.fetchall()]

            if "embedding" not in columns:
                print(f"🛠 Добавляем колонку 'embedding' в таблицу {table}...")
                cursor.execute(f"ALTER TABLE {table} ADD COLUMN embedding BLOB")
                conn.commit()
        except Exception as e:
            print(f"Ошибка при проверке схемы таблицы {table}: {e}")

    conn.close()


def process_table(db_manager, model_handler, table_name, id_column, content_column):
    """Обрабатывает таблицу пачками"""
    conn = db_manager.get_connection()
    cursor = conn.cursor()

    # Считаем, сколько работы
    cursor.execute(
        f"SELECT COUNT(*) FROM {table_name} WHERE embedding IS NULL AND {content_column} IS NOT NULL AND {content_column} != ''")
    total = cursor.fetchone()[0]

    if total == 0:
        print(f"✅ Таблица {table_name}: всё уже векторизовано.")
        conn.close()
        return

    print(f"🚀 Начало обработки {table_name}. Всего записей для обработки: {total}")

    # Берем данные
    cursor.execute(
        f"SELECT {id_column}, {content_column} FROM {table_name} WHERE embedding IS NULL AND {content_column} IS NOT NULL AND {content_column} != ''")

    # Фетчим всё сразу (если база не гигантская) или можно пачками. Для SQLite fetchall обычно ок до 100к строк.
    rows = cursor.fetchall()

    count = 0
    start_time = time.time()

    # Используем одну транзакцию для скорости
    try:
        for row in rows:
            row_id = row[0]
            text = row[1]

            # Генерация вектора
            vector = model_handler.get_embedding(text)

            if vector is not None:
                blob = array_to_blob(vector)

                # Обновление
                cursor.execute(f"UPDATE {table_name} SET embedding = ? WHERE {id_column} = ?", (blob, row_id))
                count += 1

            if count % 100 == 0:
                print(f"   Processed {count}/{total} rows...", end='\r')

        conn.commit()
        print(f"\n✅ Готово! Обработано {count} записей в {table_name} за {time.time() - start_time:.2f} сек.")

    except Exception as e:
        print(f"\n❌ Ошибка при обработке {table_name}: {e}")
    finally:
        conn.close()


def main():
    print("=== ЗАПУСК МИГРАЦИИ ВЕКТОРОВ ===")

    # 1. Инициализация БД
    db = DatabaseManager()

    # 2. Проверка схемы (на всякий случай)
    print("1. Проверка структуры базы данных...")
    ensure_schema(db.get_connection())

    # 3. Загрузка модели (Синглтон должен сработать тут)
    print("2. Инициализация нейросети (может занять время)...")
    try:
        model = EmbeddingModelHandler()
    except Exception as e:
        print(f"CRITICAL ERROR: Не удалось загрузить модель: {e}")
        return

    # 4. Обработка History
    print("3. Обработка истории переписки...")
    process_table(db, model, "history", "id", "content")

    # 5. Обработка Memories
    print("4. Обработка памяти персонажей...")
    # У тебя в memories ключ называется eternal_id, а не id
    process_table(db, model, "memories", "id", "content")

    print("\n=== МИГРАЦИЯ ЗАВЕРШЕНА ===")


if __name__ == "__main__":
    main()