import sqlite3
import logging
import os
from threading import Lock
from typing import Iterable, Tuple, Set

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

    def get_table_columns(self, table: str) -> Set[str]:
        """Возвращает set фактических колонок таблицы (не падает)."""
        conn = self.get_connection()
        try:
            cur = conn.cursor()
            cur.execute(f"PRAGMA table_info({table})")
            return set(r[1] for r in cur.fetchall() if r and len(r) > 1)
        except Exception as e:
            logging.warning(f"Failed to read schema for table '{table}': {e}")
            return set()
        finally:
            try:
                conn.close()
            except Exception:
                pass

    def ensure_columns(self, table: str, columns: Iterable[Tuple[str, str]]) -> Set[str]:
        """
        Гарантирует наличие колонок:
        - если колонки нет -> пытаемся ALTER TABLE ADD COLUMN
        - любые ошибки логируем, но НЕ валим приложение
        Возвращает актуальный набор колонок после попытки.
        """
        with self._lock:
            existing = self.get_table_columns(table)
            to_add = [(c, t) for (c, t) in columns if c not in existing]
            if not to_add:
                return existing

            conn = self.get_connection()
            try:
                cur = conn.cursor()
                for col, col_type in to_add:
                    try:
                        logging.info(f"DB ensure: adding column {table}.{col} {col_type}")
                        cur.execute(f"ALTER TABLE {table} ADD COLUMN {col} {col_type}")
                    except Exception as e:
                        logging.warning(f"DB ensure: failed to add {table}.{col}: {e}")
                conn.commit()
            except Exception as e:
                logging.warning(f"DB ensure: failed to ensure columns for {table}: {e}")
            finally:
                try:
                    conn.close()
                except Exception:
                    pass

            return self.get_table_columns(table)

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
        """Добавляет недостающие колонки, если они не были созданы ранее.
        Принцип: если не хватает столбца — пытаемся добавить; если не получилось — не падаем.
        """
        conn = self.get_connection()
        cursor = conn.cursor()

        # Полный список "желаемых" колонок по таблицам.
        # ВАЖНО: SQLite позволяет ADD COLUMN, но не позволяет легко добавлять constraints/primary keys задним числом.
        desired = {
            "memories": [
                ("character_id", "TEXT"),
                ("eternal_id", "INTEGER"),
                ("content", "TEXT"),
                ("priority", "TEXT DEFAULT 'Normal'"),
                ("type", "TEXT DEFAULT 'fact'"),
                ("date_created", "TEXT"),
                ("is_deleted", "INTEGER DEFAULT 0"),
                ("is_forgotten", "INTEGER DEFAULT 0"),
                ("embedding_id", "INTEGER"),
                ("tags", "TEXT"),
                ("participants", "TEXT"),
                ("embedding", "BLOB"),
            ],
            "history": [
                ("character_id", "TEXT"),
                ("role", "TEXT"),
                ("target", "TEXT"),
                ("participants", "TEXT"),
                ("tags", "TEXT"),
                ("rag_id", "TEXT"),
                ("message_id", "TEXT"),
                ("speaker", "TEXT"),
                ("sender", "TEXT"),
                ("event_type", "TEXT"),
                ("req_id", "TEXT"),
                ("task_uid", "TEXT"),
                ("content", "TEXT"),
                ("timestamp", "TEXT"),
                ("is_active", "INTEGER DEFAULT 1"),
                ("is_deleted", "INTEGER DEFAULT 0"),
                ("meta_data", "TEXT"),
                ("embedding", "BLOB"),
            ],
            "variables": [
                ("character_id", "TEXT"),
                ("key", "TEXT"),
                ("value", "TEXT"),
            ],
        }

        try:
            # --- Индекс против дублей history по (character_id, message_id, timestamp) ---
            try:
                cursor.execute("PRAGMA table_info(history)")
                hist_cols = {row[1] for row in cursor.fetchall() if row and len(row) > 1}
            except Exception:
                hist_cols = set()

            if {"character_id", "message_id", "timestamp"}.issubset(hist_cols):
                try:
                    cursor.execute(
                        """
                        CREATE UNIQUE INDEX IF NOT EXISTS idx_history_unique_msg
                        ON history(character_id, message_id, timestamp)
                        WHERE message_id IS NOT NULL AND TRIM(message_id) != ''
                          AND timestamp  IS NOT NULL AND TRIM(timestamp)  != ''
                        """
                    )
                    logging.info("DB upgrade: ensured UNIQUE index idx_history_unique_msg")
                except Exception as e:
                    # Если в БД уже есть дубли — индекс не создастся, это ок.
                    logging.warning(f"DB upgrade: failed to create UNIQUE index idx_history_unique_msg (ignored): {e}")

            conn.commit()
        finally:
            try:
                conn.close()
            except Exception:
                pass