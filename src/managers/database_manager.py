import sqlite3
import logging
import os
from threading import Lock
from typing import Iterable, Tuple, Set, Optional, List


class DatabaseManager:
    _instance = None
    _lock = Lock()

    # FTS5 capability cache (per-process)
    _fts5_checked: bool = False
    _fts5_supported: bool = False

    # Required for concurrent QtSql reads while sqlite3 writes
    _BUSY_TIMEOUT_MS: int = 5000

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

        # Ensure WAL + timeout are applied early
        self._init_db()
        self._initialized = True

    def _apply_sqlite_pragmas(self, conn: sqlite3.Connection) -> None:
        """
        Enforce WAL mode + busy timeout for better concurrent read/write behavior.
        - journal_mode=WAL is persisted in the database, but applying per-connection is safe.
        - busy_timeout is per-connection, must be applied for every connection.
        """
        try:
            # WAL is the key to allowing readers while another connection writes.
            cur = conn.execute("PRAGMA journal_mode=WAL;")
            row = cur.fetchone()
            if row and str(row[0]).lower() != "wal":
                logging.warning(f"SQLite PRAGMA journal_mode returned '{row[0]}' (expected 'wal').")
        except Exception as e:
            logging.warning(f"Failed to set PRAGMA journal_mode=WAL: {e}")

        try:
            conn.execute(f"PRAGMA busy_timeout = {int(self._BUSY_TIMEOUT_MS)};")
        except Exception as e:
            logging.warning(f"Failed to set PRAGMA busy_timeout={self._BUSY_TIMEOUT_MS}: {e}")

    def get_connection(self):
        # timeout (seconds) is sqlite3's busy timeout; we also set PRAGMA busy_timeout explicitly.
        conn = sqlite3.connect(
            self.db_path,
            check_same_thread=False,
            timeout=self._BUSY_TIMEOUT_MS / 1000.0,
        )
        self._apply_sqlite_pragmas(conn)
        return conn

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

    @staticmethod
    def _q_ident(ident: str) -> str:
        """Safely quote SQLite identifiers (table/column names)."""
        return '"' + str(ident).replace('"', '""') + '"'

    @staticmethod
    def table_exists(cursor: sqlite3.Cursor, name: str) -> bool:
        """
        Check table existence via sqlite_master (safe no-throw).
        Designed to be used with an existing connection/cursor (no extra connections).
        """
        try:
            cursor.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
                (str(name),),
            )
            return bool(cursor.fetchone())
        except Exception:
            return False

    def fts5_ready(self, cursor: sqlite3.Cursor, *, tables: Optional[List[str]] = None) -> bool:
        """
        Runtime check that FTS5 can be queried on the *current* connection:
          - SQLite build supports FTS5 (feature-detect, cached)
          - at least one requested FTS table exists
          - simple SELECT from existing FTS tables doesn't crash

        Safe fallback: returns False on any error.
        """
        try:
            if not self.sqlite_supports_fts5():
                return False

            tnames = tables or ["history_fts", "memories_fts"]
            existing: List[str] = []
            for t in tnames:
                if self.table_exists(cursor, t):
                    existing.append(t)
            if not existing:
                return False

            # Sanity query (covers cases like "no such module: fts5" / broken virtual table)
            for t in existing:
                cursor.execute(f"SELECT rowid FROM {self._q_ident(t)} LIMIT 1")
                cursor.fetchone()

            return True
        except Exception as e:
            logging.debug(f"DB: fts5_ready() failed (ignored): {e}")
            return False

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
        Create/maintain FTS5 tables + sync triggers safely.

        Safety rules:
        - If FTS5 is NOT available: drop FTS triggers and return (so UPDATE/INSERT on base tables work).
        - If FTS tables already exist with older/different columns: build triggers using ACTUAL FTS columns.
        """

        def q(ident: str) -> str:
            return '"' + str(ident).replace('"', '""') + '"'

        def table_cols(name: str) -> list[str]:
            try:
                cur = conn.cursor()
                cur.execute(f"PRAGMA table_info({q(name)})")
                return [r[1] for r in (cur.fetchall() or []) if r and len(r) > 1 and r[1]]
            except Exception:
                return []

        try:
            # If current SQLite build can't do FTS5, triggers must NOT exist (they break base writes).
            if not self.sqlite_supports_fts5():
                try:
                    self._drop_fts_triggers(conn)
                    conn.commit()
                except Exception:
                    pass
                return

            cur = conn.cursor()

            hist_cols = self._get_table_columns_conn(conn, "history")
            mem_cols = self._get_table_columns_conn(conn, "memories")
            if not hist_cols or not mem_cols:
                return

            # Desired columns (based on base table availability)
            history_desired = ["content"]
            for c in ("speaker", "target", "tags", "participants", "event_type"):
                if c in hist_cols:
                    history_desired.append(c)

            memories_desired = ["content"]
            for c in ("type", "priority", "tags", "participants"):
                if c in mem_cols:
                    memories_desired.append(c)

            # Ensure FTS tables exist (but don't assume their schema matches "desired")
            try:
                cur.execute(
                    f"CREATE VIRTUAL TABLE IF NOT EXISTS {q('history_fts')} USING fts5({', '.join(map(q, history_desired))})"
                )
                cur.execute(
                    f"CREATE VIRTUAL TABLE IF NOT EXISTS {q('memories_fts')} USING fts5({', '.join(map(q, memories_desired))})"
                )
            except Exception as e:
                # If we can't create FTS tables, DO NOT leave triggers around.
                logging.warning(f"DB upgrade: failed to create FTS5 tables (disabling FTS triggers): {e}")
                try:
                    self._drop_fts_triggers(conn)
                    conn.commit()
                except Exception:
                    pass
                return

            # Use ACTUAL FTS columns
            history_fts_cols = table_cols("history_fts") or ["content"]
            memories_fts_cols = table_cols("memories_fts") or ["content"]

            # Also make sure we don't reference a base column that doesn't exist (extra safety)
            history_fts_cols = [c for c in history_fts_cols if c in hist_cols] or ["content"]
            memories_fts_cols = [c for c in memories_fts_cols if c in mem_cols] or ["content"]

            h_cols_sql = ", ".join(map(q, history_fts_cols))
            m_cols_sql = ", ".join(map(q, memories_fts_cols))

            def coalesce_new(c: str) -> str:
                return f"COALESCE(new.{q(c)}, '')"

            h_new_vals = ", ".join(coalesce_new(c) for c in history_fts_cols)
            m_new_vals = ", ".join(f"COALESCE(new.{q(c)}, '')" for c in memories_fts_cols)

            # Recreate triggers
            self._drop_fts_triggers(conn)

            cur.executescript(
                f"""
                CREATE TRIGGER history_fts_ai AFTER INSERT ON {q('history')} BEGIN
                    INSERT INTO {q('history_fts')}(rowid, {h_cols_sql}) VALUES (new.id, {h_new_vals});
                END;
                CREATE TRIGGER history_fts_ad AFTER DELETE ON {q('history')} BEGIN
                    DELETE FROM {q('history_fts')} WHERE rowid = old.id;
                END;
                CREATE TRIGGER history_fts_au AFTER UPDATE ON {q('history')} BEGIN
                    DELETE FROM {q('history_fts')} WHERE rowid = old.id;
                    INSERT INTO {q('history_fts')}(rowid, {h_cols_sql}) VALUES (new.id, {h_new_vals});
                END;

                CREATE TRIGGER memories_fts_ai AFTER INSERT ON {q('memories')} BEGIN
                    INSERT INTO {q('memories_fts')}(rowid, {m_cols_sql}) VALUES (new.id, {m_new_vals});
                END;
                CREATE TRIGGER memories_fts_ad AFTER DELETE ON {q('memories')} BEGIN
                    DELETE FROM {q('memories_fts')} WHERE rowid = old.id;
                END;
                CREATE TRIGGER memories_fts_au AFTER UPDATE ON {q('memories')} BEGIN
                    DELETE FROM {q('memories_fts')} WHERE rowid = old.id;
                    INSERT INTO {q('memories_fts')}(rowid, {m_cols_sql}) VALUES (new.id, {m_new_vals});
                END;
                """
            )

            # Backfill only if empty (best-effort)
            try:
                cur.execute(f"SELECT COUNT(*) FROM {q('history_fts')}")
                h_cnt = int(cur.fetchone()[0] or 0)
            except Exception:
                h_cnt = -1
            try:
                cur.execute(f"SELECT COUNT(*) FROM {q('memories_fts')}")
                m_cnt = int(cur.fetchone()[0] or 0)
            except Exception:
                m_cnt = -1

            if h_cnt == 0:
                try:
                    h_sel = ", ".join([f"COALESCE({q(c)}, '')" for c in history_fts_cols])
                    cur.execute(
                        f"INSERT INTO {q('history_fts')}(rowid, {h_cols_sql}) "
                        f"SELECT id, {h_sel} FROM {q('history')}"
                    )
                    logging.info("DB upgrade: history_fts backfill done")
                except Exception as e:
                    logging.warning(f"DB upgrade: history_fts backfill failed (ignored): {e}")

            if m_cnt == 0:
                try:
                    m_sel = ", ".join([f"COALESCE({q(c)}, '')" for c in memories_fts_cols])
                    cur.execute(
                        f"INSERT INTO {q('memories_fts')}(rowid, {m_cols_sql}) "
                        f"SELECT id, {m_sel} FROM {q('memories')}"
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

            # Clear + backfill
            cur.execute("DELETE FROM history_fts")
            cur.execute("DELETE FROM memories_fts")

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

    def _init_db(self):
        conn = self.get_connection()
        cursor = conn.cursor()

        cursor.execute(
            '''
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
           '''
        )

        cursor.execute(
            '''
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
           '''
        )

        cursor.execute(
            '''
               CREATE TABLE IF NOT EXISTS variables (
                   character_id TEXT NOT NULL,
                   key TEXT NOT NULL,
                   value TEXT,
                   PRIMARY KEY (character_id, key)
               )
           '''
        )

        conn.commit()
        conn.close()

        self._upgrade_schema()

    def _upgrade_schema(self):
        """Добавляет недостающие колонки, если они не были созданы ранее.
        Принцип: если не хватает столбца — пытаемся добавить; если не получилось — не падаем.
        """
        conn = self.get_connection()
        cursor = conn.cursor()

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
                    logging.warning(f"DB upgrade: failed to create UNIQUE index idx_history_unique_msg (ignored): {e}")

            # --- FTS5 lexical indexes (safe, optional) ---
            self._ensure_fts5_schema(conn)

            conn.commit()
        finally:
            try:
                conn.close()
            except Exception:
                pass

    def _drop_fts_triggers(self, conn: sqlite3.Connection) -> None:
        """Drop FTS sync triggers so base table writes never fail (safe no-op)."""
        try:
            cur = conn.cursor()
            cur.executescript(
                """
                DROP TRIGGER IF EXISTS history_fts_ai;
                DROP TRIGGER IF EXISTS history_fts_ad;
                DROP TRIGGER IF EXISTS history_fts_au;

                DROP TRIGGER IF EXISTS memories_fts_ai;
                DROP TRIGGER IF EXISTS memories_fts_ad;
                DROP TRIGGER IF EXISTS memories_fts_au;
                """
            )
        except Exception as e:
            logging.warning(f"DB: failed to drop FTS triggers (ignored): {e}")