import sqlite3
import logging
import os
from threading import Lock


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
        # check_same_thread=False нужен для работы с UI/Events в разных потоках
        return sqlite3.connect(self.db_path, check_same_thread=False)

    def _init_db(self):
        conn = self.get_connection()
        cursor = conn.cursor()

        # 1. Таблица воспоминаний
        # eternal_id - вечный номер N для LLM
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
                embedding_id INTEGER
            )
        ''')
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_mem_char ON memories(character_id)')

        # 2. Таблица истории сообщений
        # meta_data - JSON поле для хранения путей к картинкам, аудио и т.д.
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                character_id TEXT NOT NULL,
                role TEXT NOT NULL,
                content TEXT,
                timestamp TEXT,
                is_active INTEGER DEFAULT 1,
                meta_data TEXT
            )
        ''')
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_hist_char ON history(character_id)')

        # 3. Таблица переменных
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
        logging.info("SQLite Database initialized: world.db")