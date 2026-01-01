import os
import json
import hashlib
import sqlite3
from datetime import datetime
import re

from managers.database_manager import DatabaseManager
from managers.history_manager import HistoryManager


def get_content_hash(text):
    if not text:
        return ""
    return hashlib.md5(str(text).encode('utf-8')).hexdigest()


def normalize_timestamp(ts_str):
    """
    Превращает старые форматы (01.01.2026_17.57 или 01.01.2026 17:58)
    в единый стандарт: %d.%m.%Y %H:%M:%S
    """
    if not ts_str or not isinstance(ts_str, str):
        return datetime.now().strftime("%d.%m.%Y %H:%M:%S")

    # 1. Заменяем "_" на пробел (01.01.2026_17.57 -> 01.01.2026 17.57)
    ts_str = ts_str.replace('_', ' ')

    # 2. Если время разделено точкой (17.57 -> 17:57)
    # Ищем паттерн " 17.57" в конце строки
    ts_str = re.sub(r' (\d{2})\.(\d{2})$', r' \1:\2', ts_str)

    # 3. Если нет секунд, добавляем их (17:57 -> 17:57:00)
    if re.search(r' \d{2}:\d{2}$', ts_str):
        ts_str += ":00"

    # 4. Обработка ISO формата (2026-01-01T18:19:05 -> 01.01.2026 18:19:05)
    if 'T' in ts_str and '-' in ts_str:
        try:
            dt = datetime.fromisoformat(ts_str.split('.')[0])  # убираем миллисекунды если есть
            return dt.strftime("%d.%m.%Y %H:%M:%S")
        except:
            pass

    return ts_str

def migrate():
    db_manager = DatabaseManager()
    conn = db_manager.get_connection()
    cursor = conn.cursor()

    histories_dir = "Histories"
    if not os.path.exists(histories_dir):
        print(f"Directory '{histories_dir}' not found.")
        return

    # Получаем список папок персонажей
    character_folders = [d for d in os.listdir(histories_dir) if os.path.isdir(os.path.join(histories_dir, d))]
    print(f"Found character folders: {character_folders}")

    for char_id in character_folders:
        char_dir = os.path.join(histories_dir, char_id)
        print(f"--- Processing character: {char_id} ---")

        # Создаем временный HistoryManager для этого персонажа,
        # чтобы использовать его логику обработки контента и сохранения картинок
        h_manager = HistoryManager(character_name=char_id, character_id=char_id)

        # --- 1. MEMORIES (Active & Missed) ---
        memory_files = [
            (f"{char_id}_memories.json", 0),  # (имя файла, is_deleted)
            (f"{char_id}_missed_memories.json", 1)
        ]

        for filename, is_deleted in memory_files:
            filepath = os.path.join(char_dir, filename)
            if os.path.exists(filepath):
                print(f"Migrating memories from {filename}...")
                with open(filepath, 'r', encoding='utf-8') as f:
                    try:
                        mem_list = json.load(f)
                        for mem in mem_list:
                            content = mem.get('content', '')
                            date = normalize_timestamp(mem.get('date', ''))
                            eternal_id = mem.get('N')

                            # Проверка на дубликат (по персонажу, дате и контенту)
                            cursor.execute('''
                                SELECT id FROM memories 
                                WHERE character_id = ? AND date_created = ? AND content = ?
                            ''', (char_id, date, content))

                            if cursor.fetchone():
                                continue

                            cursor.execute('''
                                INSERT INTO memories (
                                    character_id, eternal_id, content, priority, 
                                    type, date_created, is_deleted
                                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                            ''', (
                                char_id,
                                eternal_id,
                                content,
                                mem.get('priority', 'Normal'),
                                mem.get('memory_type', 'fact'),
                                date,
                                is_deleted
                            ))
                    except Exception as e:
                        print(f"Error in {filename}: {e}")

        # --- 2. VARIABLES ---
        hist_file = os.path.join(char_dir, f"{char_id}_history.json")
        if os.path.exists(hist_file):
            print(f"Migrating variables from {char_id}_history.json...")
            with open(hist_file, 'r', encoding='utf-8') as f:
                try:
                    data = json.load(f)
                    vars_dict = data.get("variables", {})
                    for k, v in vars_dict.items():
                        cursor.execute('''
                            INSERT OR REPLACE INTO variables (character_id, key, value)
                            VALUES (?, ?, ?)
                        ''', (char_id, k, json.dumps(v, ensure_ascii=False)))
                except Exception as e:
                    print(f"Error reading variables: {e}")

        # --- 3. HISTORY MESSAGES (Active & Missed) ---
        # Формируем список сообщений для обработки
        messages_to_process = []

        # Загружаем активную историю
        if os.path.exists(hist_file):
            with open(hist_file, 'r', encoding='utf-8') as f:
                try:
                    d = json.load(f)
                    for m in d.get("messages", []):
                        messages_to_process.append((m, 1))  # (сообщение, is_active)
                except:
                    pass

        # Загружаем потерянную историю
        missed_hist_file = os.path.join(char_dir, "missed_history.json")
        if os.path.exists(missed_hist_file):
            with open(missed_hist_file, 'r', encoding='utf-8') as f:
                try:
                    d = json.load(f)
                    for m in d:
                        messages_to_process.append((m, 0))
                except:
                    pass

        if messages_to_process:
            print(f"Migrating {len(messages_to_process)} history messages...")
            for msg_data, is_active in messages_to_process:
                role = msg_data.get("role", "user")
                raw_content = msg_data.get("content", "")

                # Метаданные из JSON (если были)
                temp_meta = {}
                if "image" in msg_data:
                    temp_meta["image"] = msg_data["image"]

                # Используем логику HistoryManager для:
                # 1. Извлечения текста в db_content
                # 2. Сохранения Base64 картинок на диск и замены их на пути в db_meta
                db_content, db_meta = h_manager._prepare_message_for_db(role, raw_content, temp_meta)

                # В старых JSON нет timestamp. Для миграции используем заглушку или текущее время,
                # если хотим избежать дублей при повторном запуске.
                # Но лучше оставить NULL, если даты нет.
                raw_ts = msg_data.get("time") or msg_data.get("timestamp")
                timestamp = normalize_timestamp(raw_ts)

                # Проверка на дубликат сообщения
                cursor.execute('''
                    SELECT id FROM history 
                    WHERE character_id = ? AND role = ? AND content = ? AND is_active = ?
                ''', (char_id, role, db_content, is_active))

                if cursor.fetchone():
                    continue

                cursor.execute('''
                    INSERT INTO history (
                        character_id, role, content, timestamp, is_active, meta_data
                    ) VALUES (?, ?, ?, ?, ?, ?)
                ''', (char_id, role, db_content, timestamp, is_active, db_meta))

    conn.commit()
    conn.close()
    print("--- Migration finished successfully ---")


if __name__ == "__main__":
    migrate()