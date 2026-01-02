import sqlite3
import logging
import os
from threading import Lock
from typing import List, Tuple

class DatabaseManager:
    _instance = None
    _lock = Lock()

    def __new__(cls):
        with cls._lock:
            if cls._instance is None:
                cls._instance = super(DatabaseManager, cls).__new__(cls)
                cls._instance._initialized = False
            return cls._instance

    def __init__(self):
        if self._initialized:
            return

        os.makedirs("Histories", exist_ok=True)
        self.db_path = os.path.join("Histories", "world.db")
        self._init_db()
        self._initialized = True

    def get_connection(self):
        # timeout + busy_timeout: чтобы не падать сразу при конкурирующих записях
        conn = sqlite3.connect(self.db_path, check_same_thread=False, timeout=30)
        try:
            conn.execute("PRAGMA busy_timeout = 30000")
        except Exception:
            pass
        return conn

    def _init_db(self):
        conn = self.get_connection()
        cursor = conn.cursor()

        cursor.execute('''
               CREATE TABLE IF NOT EXISTS memories (
                   id INTEGER PRIMARY KEY AUTOINCREMENT,
                   character_id TEXT NOT NULL,
                   eternal_id INTEGER NOT NULL,
                   content TEXT NOT NULL,
                   priority TEXT DEFAULT 'Normal',
                   type TEXT DEFAULT 'fact',
                   date_created TEXT,
                   is_deleted INTEGER DEFAULT 0,
                   embedding_id INTEGER,
                   tags TEXT,
                   participants TEXT,
                   embedding BLOB
               )
           ''')

        cursor.execute('''
               CREATE TABLE IF NOT EXISTS history (
                   id INTEGER PRIMARY KEY AUTOINCREMENT,
                   character_id TEXT NOT NULL,
                   role TEXT NOT NULL,
                   target TEXT,
                   participants TEXT,
                   tags TEXT,
                   rag_id TEXT,
                   message_id TEXT,
                   speaker TEXT,
                   sender TEXT,
                   event_type TEXT,
                   req_id TEXT,
                   task_uid TEXT,
                   content TEXT,
                   timestamp TEXT,
                   is_active INTEGER DEFAULT 1,
                   is_deleted INTEGER DEFAULT 0,
                   meta_data TEXT
                   ,embedding BLOB
               )
           ''')

        cursor.execute('''
               CREATE TABLE IF NOT EXISTS variables (
                   character_id TEXT NOT NULL,
                   key TEXT NOT NULL,
                   value TEXT,
                   PRIMARY KEY (character_id, key)
               )
           ''')

        conn.commit()
        conn.close()

        self._upgrade_schema()

    def _upgrade_schema(self):
        """Добавляет недостающие колонки, если они не были созданы ранее"""
        conn = self.get_connection()
        cursor = conn.cursor()

        # Добавлен ("history", "target", "TEXT") в список обновлений
        updates = [
            ("history", "target", "TEXT"),
            ("history", "rag_id", "TEXT"),
            ("history", "tags", "TEXT"),
            ("history", "participants", "TEXT"),
            ("history", "is_deleted", "INTEGER DEFAULT 0"),
            ("memories", "tags", "TEXT"),
            ("memories", "participants", "TEXT"),

            ("memories", "embedding", "BLOB"),  # Храним вектор как байты
            ("history", "embedding", "BLOB")  # Храним вектор сообщения
        ]

        for table, column, col_type in updates:
            cursor.execute(f"PRAGMA table_info({table})")
            columns = [info[1] for info in cursor.fetchall()]

            if column not in columns:
                logging.info(f"Adding column {column} to table {table}...")
                try:
                    cursor.execute(f"ALTER TABLE {table} ADD COLUMN {column} {col_type}")
                except Exception as e:
                    logging.error(f"Error upgrading {table}.{column}: {e}")

        conn.commit()
        conn.close()