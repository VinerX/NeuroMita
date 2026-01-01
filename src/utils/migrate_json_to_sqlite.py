import os
import json
import sqlite3
import sys

# Добавляем корневую папку в путь, чтобы импортировать DatabaseManager
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from managers.database_manager import DatabaseManager


def migrate():
    db = DatabaseManager()
    conn = db.get_connection()
    cursor = conn.cursor()

    histories_dir = "Histories"
    if not os.path.exists(histories_dir):
        print("Folder 'Histories' not found.")
        return

    # Получаем список папок (персонажей)
    character_names = [d for d in os.listdir(histories_dir) if os.path.isdir(os.path.join(histories_dir, d))]

    print(f"Found characters: {character_names}")

    for char_id in character_names:
        char_dir = os.path.join(histories_dir, char_id)
        print(f"Migrating {char_id}...")

        # --- 1. Memories ---
        mem_file = os.path.join(char_dir, f"{char_id}_memories.json")
        if os.path.exists(mem_file):
            with open(mem_file, 'r', encoding='utf-8') as f:
                try:
                    memories = json.load(f)
                    for mem in memories:
                        cursor.execute('''
                            INSERT INTO memories (character_id, eternal_id, content, priority, type, date_created, is_deleted)
                            VALUES (?, ?, ?, ?, ?, ?, 0)
                        ''', (
                        char_id, mem.get('N'), mem.get('content'), mem.get('priority'), mem.get('memory_type', 'fact'),
                        mem.get('date')))
                except Exception as e:
                    print(f"Error reading memories for {char_id}: {e}")

        # --- 2. Missed Memories ---
        miss_mem_file = os.path.join(char_dir, f"{char_id}_missed_memories.json")
        if os.path.exists(miss_mem_file):
            with open(miss_mem_file, 'r', encoding='utf-8') as f:
                try:
                    memories = json.load(f)
                    for mem in memories:
                        cursor.execute('''
                            INSERT INTO memories (character_id, eternal_id, content, priority, type, date_created, is_deleted)
                            VALUES (?, ?, ?, ?, ?, ?, 1)
                        ''', (
                        char_id, mem.get('N'), mem.get('content'), mem.get('priority'), mem.get('memory_type', 'fact'),
                        mem.get('date')))
                except Exception as e:
                    print(f"Error reading missed memories for {char_id}: {e}")

        # --- 3. History & Variables ---
        hist_file = os.path.join(char_dir, f"{char_id}_history.json")
        if os.path.exists(hist_file):
            with open(hist_file, 'r', encoding='utf-8') as f:
                try:
                    data = json.load(f)

                    # Variables
                    vars_dict = data.get("variables", {})
                    for k, v in vars_dict.items():
                        # Сохраняем как JSON строку
                        cursor.execute('''
                            INSERT OR REPLACE INTO variables (character_id, key, value)
                            VALUES (?, ?, ?)
                        ''', (char_id, k, json.dumps(v, ensure_ascii=False)))

                    # Messages
                    messages = data.get("messages", [])
                    for msg in messages:
                        # Пытаемся извлечь meta_data если она вдруг была в старой структуре, или оставляем None
                        meta = None
                        # Если вдруг у тебя уже были поля image в сообщениях
                        if "image" in msg:
                            meta = json.dumps({"image": msg["image"]}, ensure_ascii=False)

                        cursor.execute('''
                            INSERT INTO history (character_id, role, content, timestamp, is_active, meta_data)
                            VALUES (?, ?, ?, ?, 1, ?)
                        ''', (char_id, msg.get("role"), msg.get("content"), None,
                              meta))  # Timestamp не было в старой json-структуре сообщений обычно

                except Exception as e:
                    print(f"Error reading history for {char_id}: {e}")

        # --- 4. Missed History ---
        missed_hist_file = os.path.join(char_dir,
                                        "missed_history.json")  # Он обычно общий в папке или как у тебя в коде
        if os.path.exists(missed_hist_file):
            with open(missed_hist_file, 'r', encoding='utf-8') as f:
                try:
                    messages = json.load(f)
                    for msg in messages:
                        cursor.execute('''
                            INSERT INTO history (character_id, role, content, timestamp, is_active)
                            VALUES (?, ?, ?, ?, 0)
                        ''', (char_id, msg.get("role"), msg.get("content"), None))
                except Exception as e:
                    print(f"Error reading missed history for {char_id}: {e}")

    conn.commit()
    conn.close()
    print("Migration finished successfully.")


if __name__ == "__main__":
    migrate()