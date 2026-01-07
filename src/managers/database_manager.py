import sqlite3
import logging
import os
from threading import Lock
from typing import Iterable, Tuple, Set, Optional, List

class DatabaseManager:
    _instance = None
    _lock = Lock()

    def __new__(cls):
        with cls._lock:
            if cls._instance is None:
                cls._instance = super(DatabaseManager, cls).__new__(cls)
                cls._instance._initialized = False
            return cls._instance

    # FTS5 capability cache (per-process)
    _fts5_checked: bool = False
    _fts5_supported: bool = False

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

    def _get_table_columns_conn(self, conn: sqlite3.Connection, table: str) -> Set[str]:
        try:
            cur = conn.cursor()
            cur.execute(f"PRAGMA table_info({table})")
            return set(r[1] for r in cur.fetchall() if r and len(r) > 1)
        except Exception:
            return set()

    def sqlite_supports_fts5(self) -> bool:
        """
        Feature-detect FTS5 support in the current SQLite build.
        Must NEVER crash the app: return False on any error.
        """
        with self._lock:
            if self._fts5_checked:
                return bool(self._fts5_supported)

            conn = None
            ok = False
            try:
                conn = self.get_connection()
                # TEMP to avoid touching disk schema; if fts5 is missing -> OperationalError: no such module: fts5
                conn.execute("CREATE VIRTUAL TABLE temp.__fts5_test USING fts5(x)")
                conn.execute("DROP TABLE temp.__fts5_test")
                ok = True
            except Exception as e:
                logging.debug(f"SQLite FTS5 not available (or blocked): {e}")
                ok = False
            finally:
                try:
                    if conn:
                        conn.close()
                except Exception:
                    pass

            self._fts5_supported = bool(ok)
            self._fts5_checked = True
            return bool(ok)

    def _ensure_fts5_schema(self, conn: sqlite3.Connection) -> None:
        """
        Create FTS5 virtual tables + sync triggers for:
          - history_fts (rowid == history.id)
          - memories_fts (rowid == memories.id)  [NOTE: eternal_id is not globally unique across characters]

        Safe fallback:
          - if FTS5 module is missing -> do nothing
          - any SQL errors are logged and ignored
        """
        try:
            if not self.sqlite_supports_fts5():
                return

            cur = conn.cursor()

            hist_cols = self._get_table_columns_conn(conn, "history")
            mem_cols = self._get_table_columns_conn(conn, "memories")
            if not hist_cols or not mem_cols:
                return

            # Optional indexed fields (only if реально есть в таблицах)
            history_fts_cols: List[str] = ["content"]
            for c in ("speaker", "target", "tags", "participants", "event_type"):
                if c in hist_cols:
                    history_fts_cols.append(c)

            memories_fts_cols: List[str] = ["content"]
            for c in ("type", "priority", "tags", "participants"):
                if c in mem_cols:
                    memories_fts_cols.append(c)

            # --- Create virtual tables (IF NOT EXISTS) ---
            try:
                cur.execute(
                    f"CREATE VIRTUAL TABLE IF NOT EXISTS history_fts USING fts5({', '.join(history_fts_cols)})"
                )
                cur.execute(
                    f"CREATE VIRTUAL TABLE IF NOT EXISTS memories_fts USING fts5({', '.join(memories_fts_cols)})"
                )
            except Exception as e:
                logging.warning(f"DB upgrade: failed to create FTS5 tables (ignored): {e}")
                return

            # --- Triggers: keep FTS in sync with base tables ---
            # history_fts: rowid == history.id
            def _coalesce_new(col: str) -> str:
                return f"COALESCE(new.{col}, '')"

            def _coalesce_old(col: str) -> str:
                return f"COALESCE(old.{col}, '')"

            h_cols_sql = ", ".join(history_fts_cols)
            h_new_vals_sql = ", ".join([_coalesce_new(c) for c in history_fts_cols])
            h_old_vals_sql = ", ".join([_coalesce_old(c) for c in history_fts_cols])

            m_cols_sql = ", ".join(memories_fts_cols)
            m_new_vals_sql = ", ".join([_coalesce_new(c) for c in memories_fts_cols])
            m_old_vals_sql = ", ".join([_coalesce_old(c) for c in memories_fts_cols])

            try:
                cur.executescript(
                    f"""
                    CREATE TRIGGER IF NOT EXISTS history_fts_ai AFTER INSERT ON history BEGIN
                        INSERT INTO history_fts(rowid, {h_cols_sql}) VALUES (new.id, {h_new_vals_sql});
                    END;
                    CREATE TRIGGER IF NOT EXISTS history_fts_ad AFTER DELETE ON history BEGIN
                        INSERT INTO history_fts(history_fts, rowid, {h_cols_sql}) VALUES ('delete', old.id, {h_old_vals_sql});
                    END;
                    CREATE TRIGGER IF NOT EXISTS history_fts_au AFTER UPDATE ON history BEGIN
                        INSERT INTO history_fts(history_fts, rowid, {h_cols_sql}) VALUES ('delete', old.id, {h_old_vals_sql});
                        INSERT INTO history_fts(rowid, {h_cols_sql}) VALUES (new.id, {h_new_vals_sql});
                    END;
                    """
                )
            except Exception as e:
                logging.warning(f"DB upgrade: failed to create history FTS triggers (ignored): {e}")

            # memories_fts: rowid == memories.id (PK). We DO NOT use eternal_id here because it is per-character.
            try:
                cur.executescript(
                    f"""
                    CREATE TRIGGER IF NOT EXISTS memories_fts_ai AFTER INSERT ON memories BEGIN
                        INSERT INTO memories_fts(rowid, {m_cols_sql}) VALUES (new.id, {m_new_vals_sql});
                    END;
                    CREATE TRIGGER IF NOT EXISTS memories_fts_ad AFTER DELETE ON memories BEGIN
                        INSERT INTO memories_fts(memories_fts, rowid, {m_cols_sql}) VALUES ('delete', old.id, {m_old_vals_sql});
                    END;
                    CREATE TRIGGER IF NOT EXISTS memories_fts_au AFTER UPDATE ON memories BEGIN
                        INSERT INTO memories_fts(memories_fts, rowid, {m_cols_sql}) VALUES ('delete', old.id, {m_old_vals_sql});
                        INSERT INTO memories_fts(rowid, {m_cols_sql}) VALUES (new.id, {m_new_vals_sql});
                    END;
                    """
                )
            except Exception as e:
                logging.warning(f"DB upgrade: failed to create memories FTS triggers (ignored): {e}")

            # --- Backfill (only if index is empty) ---
            # This keeps upgrades safe for old DBs without forcing a heavy rebuild every startup.
            try:
                cur.execute("SELECT COUNT(*) FROM history_fts")
                h_cnt = int(cur.fetchone()[0] or 0)
            except Exception:
                h_cnt = -1
            try:
                cur.execute("SELECT COUNT(*) FROM memories_fts")
                m_cnt = int(cur.fetchone()[0] or 0)
            except Exception:
                m_cnt = -1

            if h_cnt == 0:
                try:
                    sel_cols = ", ".join([f"COALESCE({c}, '')" for c in history_fts_cols])
                    cur.execute(
                        f"INSERT INTO history_fts(rowid, {h_cols_sql}) SELECT id, {sel_cols} FROM history"
                    )
                    logging.info("DB upgrade: history_fts backfill done")
                except Exception as e:
                    logging.warning(f"DB upgrade: history_fts backfill failed (ignored): {e}")

            if m_cnt == 0:
                try:
                    sel_cols = ", ".join([f"COALESCE({c}, '')" for c in memories_fts_cols])
                    cur.execute(
                        f"INSERT INTO memories_fts(rowid, {m_cols_sql}) SELECT id, {sel_cols} FROM memories"
                    )
                    logging.info("DB upgrade: memories_fts backfill done")
                except Exception as e:
                    logging.warning(f"DB upgrade: memories_fts backfill failed (ignored): {e}")

            try:
                conn.commit()
            except Exception:
                pass

        except Exception as e:
            logging.warning(f"DB upgrade: ensure FTS5 schema failed (ignored): {e}")

    def rebuild_fts_indexes(self) -> bool:
        """
        Manual full rebuild for both FTS tables (safe no-op if FTS5 is unavailable).
        Returns True if rebuild was attempted successfully, else False.
        """
        if not self.sqlite_supports_fts5():
            return False

        conn = None
        try:
            conn = self.get_connection()
            self._ensure_fts5_schema(conn)
            cur = conn.cursor()

            # Check tables exist
            cur.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='history_fts'")
            if not cur.fetchone():
                return False
            cur.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='memories_fts'")
            if not cur.fetchone():
                return False

            # Clear + backfill (best-effort; columns may differ by DB history)
            cur.execute("DELETE FROM history_fts")
            cur.execute("DELETE FROM memories_fts")

            # Re-run ensure to know actual column sets (by introspecting base tables)
            hist_cols = self._get_table_columns_conn(conn, "history")
            mem_cols = self._get_table_columns_conn(conn, "memories")
            history_fts_cols: List[str] = ["content"]
            for c in ("speaker", "target", "tags", "participants", "event_type"):
                if c in hist_cols:
                    history_fts_cols.append(c)
            memories_fts_cols: List[str] = ["content"]
            for c in ("type", "priority", "tags", "participants"):
                if c in mem_cols:
                    memories_fts_cols.append(c)

            h_cols_sql = ", ".join(history_fts_cols)
            h_sel_cols = ", ".join([f"COALESCE({c}, '')" for c in history_fts_cols])
            m_cols_sql = ", ".join(memories_fts_cols)
            m_sel_cols = ", ".join([f"COALESCE({c}, '')" for c in memories_fts_cols])

            cur.execute(f"INSERT INTO history_fts(rowid, {h_cols_sql}) SELECT id, {h_sel_cols} FROM history")
            cur.execute(f"INSERT INTO memories_fts(rowid, {m_cols_sql}) SELECT id, {m_sel_cols} FROM memories")
            conn.commit()
            return True
        except Exception as e:
            logging.warning(f"DB: rebuild FTS indexes failed (ignored): {e}", exc_info=True)
            try:
                if conn:
                    conn.rollback()
            except Exception:
                pass
            return False
        finally:
            try:
                if conn:
                    conn.close()
            except Exception:
                pass

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

            # --- FTS5 lexical indexes (safe, optional) ---
            self._ensure_fts5_schema(conn)

            conn.commit()
        finally:
            try:
                conn.close()
            except Exception:
                pass