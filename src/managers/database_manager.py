import json
import sqlite3
import logging
import os
from datetime import datetime
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

    # ---------------------------
    # UI-facing DB helpers
    # ---------------------------
    def dedupe_history(self, character_id: Optional[str] = None) -> int:
        """
        Remove duplicate rows in `history` using criteria:
          - same (character_id, content, timestamp)
          - keep row with minimal id

        If `character_id` is None/empty -> dedupe for ALL characters.
        Returns number of deleted rows (best-effort; 0 on error).
        """
        cid = (str(character_id).strip() if character_id is not None else "")
        conn = None
        try:
            conn = self.get_connection()
            cur = conn.cursor()

            # Be conservative: only dedupe meaningful rows (avoid deleting "empty" placeholders)
            base_filter = """
                content   IS NOT NULL AND TRIM(content)   != ''
                AND timestamp IS NOT NULL AND TRIM(timestamp) != ''
            """.strip()

            params: list = []
            if cid:
                base_filter = f"({base_filter}) AND character_id=?"
                params.append(cid)

            # base_filter is duplicated in CTE + DELETE -> params must be duplicated as well
            all_params = params + params

            sql = f"""
            WITH keep AS (
                SELECT MIN(id) AS id
                FROM history
                WHERE {base_filter}
                GROUP BY character_id, content, timestamp
            )
            DELETE FROM history
            WHERE {base_filter}
              AND id NOT IN (SELECT id FROM keep)
            """

            cur.execute(sql, all_params)
            cur.execute("SELECT changes()")
            deleted = int((cur.fetchone() or [0])[0] or 0)

            try:
                conn.commit()
            except Exception:
                pass

            return deleted
        except Exception as e:
            logging.warning(f"DB: dedupe_history failed (ignored): {e}", exc_info=True)
            try:
                if conn:
                    conn.rollback()
            except Exception:
                pass
            return 0
        finally:
            try:
                if conn:
                    conn.close()
            except Exception:
                pass

    def count_missing_embeddings(self, character_id: str) -> Tuple[int, int]:
        """
        Counts rows that likely require embedding generation:
          - history: embedding IS NULL and content is not empty
          - memories: embedding IS NULL
        Returns (history_missing, memories_missing). Safe fallback: (0, 0).
        """
        cid = str(character_id or "").strip()
        if not cid:
            return (0, 0)

        conn = None
        try:
            conn = self.get_connection()
            cur = conn.cursor()

            # Динамическая проверка наличия колонок is_deleted,
            # чтобы не ломать старые БД, если миграция не прошла.
            hist_cols = self._get_table_columns_conn(conn, "history")
            mem_cols = self._get_table_columns_conn(conn, "memories")

            # Для истории: пропускаем удаленные, если колонка есть
            extra_h = " AND is_deleted=0" if "is_deleted" in hist_cols else ""

            # Для памяти: пропускаем удаленные, если колонка есть
            extra_m = " AND is_deleted=0" if "is_deleted" in mem_cols else ""

            cur.execute(
                f"""
                SELECT COUNT(*)
                FROM history
                WHERE character_id=?
                  AND embedding IS NULL
                  AND content IS NOT NULL
                  AND TRIM(content) != ''
                  {extra_h}
                """,
                (cid,),
            )
            h = int((cur.fetchone() or [0])[0] or 0)

            cur.execute(
                f"""
                SELECT COUNT(*)
                FROM memories
                WHERE character_id=?
                  AND embedding IS NULL
                  {extra_m}
                """,
                (cid,),
            )
            m = int((cur.fetchone() or [0])[0] or 0)

            return (h, m)
        except Exception as e:
            logging.debug(f"DB: count_missing_embeddings failed (ignored): {e}")
            return (0, 0)
        finally:
            try:
                if conn:
                    conn.close()
            except Exception:
                pass

    def count_records_for_full_reindex(self, character_id: str) -> Tuple[int, int]:
        """
        Counts rows that will be processed by a *full* reindex (re-embed everything):
          - history: content not empty
          - memories: is_deleted=0
        Returns (history_total, memories_total). Safe fallback: (0, 0).
        """
        cid = str(character_id or "").strip()
        if not cid:
            return (0, 0)

        conn = None
        try:
            conn = self.get_connection()
            cur = conn.cursor()

            hist_cols = self._get_table_columns_conn(conn, "history")
            extra_h = " AND is_deleted=0" if "is_deleted" in hist_cols else ""

            cur.execute(
                f"""
                SELECT COUNT(*)
                FROM history
                WHERE character_id=?
                  AND content IS NOT NULL
                  AND TRIM(content) != ''
                  {extra_h}
                """,
                (cid,),
            )
            h = int((cur.fetchone() or [0])[0] or 0)

            cur.execute(
                """
                SELECT COUNT(*)
                FROM memories
                WHERE character_id=?
                  AND is_deleted=0
                """,
                (cid,),
            )
            m = int((cur.fetchone() or [0])[0] or 0)

            return (h, m)
        except Exception as e:
            logging.debug(f"DB: count_records_for_full_reindex failed (ignored): {e}")
            return (0, 0)
        finally:
            try:
                if conn:
                    conn.close()
            except Exception:
                pass

    def _export_excluded_columns(self, cols: list[str]) -> list[str]:
        # Не выгружаем эмбеддинги и связанные поля (embedding, embedding_id, etc.)
        out = []
        for c in cols:
            lc = str(c).lower()
            if "embedding" in lc:
                continue
            out.append(c)
        return out

    def _build_status_where(self, table: str, table_cols: set[str], *,
                            active: bool, forgotten: bool, deleted: bool) -> tuple[str, list]:
        """
        Возвращает SQL-кусок (без WHERE) и параметры для статусов.
        """
        parts = []
        params: list = []

        if table == "history":
            # history: active/forgotten via is_active, deleted via is_deleted
            # active: is_deleted=0 AND is_active=1
            # forgotten: is_deleted=0 AND is_active=0
            # deleted: is_deleted=1
            if deleted and "is_deleted" in table_cols:
                parts.append("(is_deleted=1)")
            if active and {"is_deleted", "is_active"}.issubset(table_cols):
                parts.append("(is_deleted=0 AND is_active=1)")
            if forgotten and {"is_deleted", "is_active"}.issubset(table_cols):
                parts.append("(is_deleted=0 AND is_active=0)")

        elif table == "memories":
            # memories: forgotten via is_forgotten (если есть), deleted via is_deleted
            # active: is_deleted=0 AND (is_forgotten=0 if exists)
            if deleted and "is_deleted" in table_cols:
                parts.append("(is_deleted=1)")

            if active and "is_deleted" in table_cols:
                if "is_forgotten" in table_cols:
                    parts.append("(is_deleted=0 AND is_forgotten=0)")
                else:
                    parts.append("(is_deleted=0)")

            if forgotten and "is_deleted" in table_cols and "is_forgotten" in table_cols:
                parts.append("(is_deleted=0 AND is_forgotten=1)")

        if not parts:
            # если колонок нет/ничего не выбрано — вернём "ложь"
            return "1=0", []

        return "(" + " OR ".join(parts) + ")", params

    def _build_date_where(self, table: str, table_cols: set[str], *,
                          date_mode: str, date_from: str, date_to: str) -> tuple[str, list]:
        """
        date_mode: all/from/range
        history -> timestamp
        memories -> date_created
        """
        if date_mode not in ("all", "from", "range"):
            date_mode = "all"
        if date_mode == "all":
            return "", []

        col = None
        if table == "history" and "timestamp" in table_cols:
            col = "timestamp"
        if table == "memories" and "date_created" in table_cols:
            col = "date_created"
        if not col:
            return "", []

        if date_mode == "from":
            return f"({col} IS NOT NULL AND TRIM({col})!='' AND {col} >= ?)", [date_from]
        # range
        return f"({col} IS NOT NULL AND TRIM({col})!='' AND {col} >= ? AND {col} <= ?)", [date_from, date_to]

    def _build_column_filters_where(self, table: str, table_cols: set[str], filters_obj: dict | None) -> tuple[str, list]:
        """
        filters_obj expected:
          {
            "history": {"role": ["user","assistant"], "speaker": {"like":"Alice%"}},
            "memories": {...},
            "variables": {...}
          }
        """
        if not isinstance(filters_obj, dict):
            return "", []

        tf = filters_obj.get(table)
        if not isinstance(tf, dict) or not tf:
            return "", []

        parts = []
        params: list = []

        for col, val in tf.items():
            if col not in table_cols:
                continue
            if isinstance(val, dict):
                # {"like": "..."}
                if "like" in val:
                    parts.append(f"({col} LIKE ?)")
                    params.append(str(val.get("like") or ""))
                continue

            if isinstance(val, list):
                cleaned = [v for v in val]
                if not cleaned:
                    continue
                placeholders = ",".join(["?"] * len(cleaned))
                parts.append(f"({col} IN ({placeholders}))")
                params.extend(cleaned)
                continue

            # scalar -> equals
            parts.append(f"({col} = ?)")
            params.append(val)

        if not parts:
            return "", []
        return "(" + " AND ".join(parts) + ")", params

    def export_to_json_file(
        self,
        *,
        out_path: str,
        character_id: str | None,
        include_history: bool,
        include_memories: bool,
        include_variables: bool,
        status_active: bool,
        status_forgotten: bool,
        status_deleted: bool,
        date_mode: str,
        date_from: str,
        date_to: str,
        column_filters: dict | None = None,
        progress_callback=None
    ) -> str:
        """
        Экспорт в JSON (стримингом, без загрузки всех данных в память).
        Возвращает компактное текстовое резюме (для QMessageBox).
        """
        out_path = str(out_path or "").strip()
        if not out_path:
            raise ValueError("out_path is empty")

        os.makedirs(os.path.dirname(out_path) or ".", exist_ok=True)

        conn = None
        try:
            conn = self.get_connection()
            conn.row_factory = sqlite3.Row
            cur = conn.cursor()

            plan = []
            if include_history:
                plan.append("history")
            if include_memories:
                plan.append("memories")
            if include_variables:
                plan.append("variables")

            # --- предварительный подсчёт для прогресса (best-effort)
            total = 0
            counts: dict[str, int] = {}

            def _count_rows(table: str) -> int:
                cols = self._get_table_columns_conn(conn, table)
                where = []
                params = []

                if character_id and "character_id" in cols:
                    where.append("character_id=?")
                    params.append(str(character_id))

                if table in ("history", "memories"):
                    st_sql, st_params = self._build_status_where(
                        table, cols,
                        active=status_active, forgotten=status_forgotten, deleted=status_deleted
                    )
                    where.append(st_sql)
                    params.extend(st_params)

                    dt_sql, dt_params = self._build_date_where(
                        table, cols, date_mode=date_mode, date_from=date_from, date_to=date_to
                    )
                    if dt_sql:
                        where.append(dt_sql)
                        params.extend(dt_params)

                cf_sql, cf_params = self._build_column_filters_where(table, cols, column_filters)
                if cf_sql:
                    where.append(cf_sql)
                    params.extend(cf_params)

                wsql = " WHERE " + " AND ".join(where) if where else ""
                cur.execute(f"SELECT COUNT(*) FROM {self._q_ident(table)}{wsql}", tuple(params))
                return int((cur.fetchone() or [0])[0] or 0)

            for t in plan:
                try:
                    c = _count_rows(t)
                except Exception:
                    c = 0
                counts[t] = c
                total += c

            done = 0
            if progress_callback:
                progress_callback(0, max(total, 1))

            export_meta = {
                "format": "world-db-export",
                "version": 1,
                "created_at": datetime.utcnow().isoformat() + "Z",
                "scope": {"character_id": character_id},
                "options": {
                    "include_history": bool(include_history),
                    "include_memories": bool(include_memories),
                    "include_variables": bool(include_variables),
                    "status_active": bool(status_active),
                    "status_forgotten": bool(status_forgotten),
                    "status_deleted": bool(status_deleted),
                    "date_mode": str(date_mode),
                    "date_from": str(date_from),
                    "date_to": str(date_to),
                },
                "tables": {}
            }

            with open(out_path, "w", encoding="utf-8") as f:
                # Пишем заголовок без tables (tables будем стримить вручную)
                head = dict(export_meta)
                head["tables"] = None
                head_json = json.dumps(head, ensure_ascii=False)
                # заменим "tables": null на "tables":{
                head_json = head_json.replace('"tables": null', '"tables": {')
                f.write(head_json)
                first_table = True

                def _write_table(table: str):
                    nonlocal done, first_table
                    cols_all = list(self._get_table_columns_conn(conn, table))
                    cols_all = [c for c in cols_all if c]  # safety
                    cols_use = self._export_excluded_columns(cols_all)

                    # WHERE
                    where = []
                    params = []

                    if character_id and "character_id" in cols_all:
                        where.append("character_id=?")
                        params.append(str(character_id))

                    if table in ("history", "memories"):
                        st_sql, st_params = self._build_status_where(
                            table, set(cols_all),
                            active=status_active, forgotten=status_forgotten, deleted=status_deleted
                        )
                        where.append(st_sql)
                        params.extend(st_params)

                        dt_sql, dt_params = self._build_date_where(
                            table, set(cols_all),
                            date_mode=date_mode, date_from=date_from, date_to=date_to
                        )
                        if dt_sql:
                            where.append(dt_sql)
                            params.extend(dt_params)

                    cf_sql, cf_params = self._build_column_filters_where(table, set(cols_all), column_filters)
                    if cf_sql:
                        where.append(cf_sql)
                        params.extend(cf_params)

                    wsql = " WHERE " + " AND ".join(where) if where else ""
                    cols_sql = ", ".join([self._q_ident(c) for c in cols_use])

                    # table header
                    if not first_table:
                        f.write(",")
                    first_table = False

                    f.write(json.dumps(table, ensure_ascii=False))
                    f.write(":")
                    f.write("{")
                    f.write('"columns":')
                    f.write(json.dumps(cols_use, ensure_ascii=False))
                    f.write(',"rows":[')

                    # rows streaming
                    cur2 = conn.cursor()
                    order_by = ""
                    if "id" in cols_all:
                        order_by = " ORDER BY id ASC"
                    elif table == "variables" and "key" in cols_all:
                        order_by = " ORDER BY key ASC"
                    else:
                        order_by = " ORDER BY rowid ASC"

                    cur2.execute(
                        f"SELECT {cols_sql} FROM {self._q_ident(table)}{wsql}{order_by}",
                        tuple(params)
                    )
                    first_row = True
                    batch = cur2.fetchmany(500)
                    while batch:
                        for r in batch:
                            d = dict(r)
                            # safety: на всякий
                            d = {k: v for k, v in d.items() if "embedding" not in str(k).lower()}
                            if not first_row:
                                f.write(",")
                            first_row = False
                            f.write(json.dumps(d, ensure_ascii=False))
                            done += 1
                        if progress_callback:
                            progress_callback(done, max(total, 1))
                        batch = cur2.fetchmany(500)

                    f.write("]}")
                    # done

                for t in plan:
                    _write_table(t)

                # закрываем "tables": { ... }
                f.write("}}")

            parts = [f"OK: {out_path}"]
            if "history" in counts:
                parts.append(f"history: {counts['history']}")
            if "memories" in counts:
                parts.append(f"memories: {counts['memories']}")
            if "variables" in counts:
                parts.append(f"variables: {counts['variables']}")
            return "\n".join(parts)

        finally:
            try:
                if conn:
                    conn.close()
            except Exception:
                pass

    def import_from_json_file(self, *, path: str, override_character_id: str | None = None, progress_callback=None) -> str:
        """
        Импорт из JSON формата export_to_json_file().
        override_character_id:
          - None: импортируем как есть
          - str: принудительно выставляем character_id для history/memories/variables
        """
        path = str(path or "").strip()
        if not path or not os.path.exists(path):
            raise ValueError("File does not exist")

        with open(path, "r", encoding="utf-8") as f:
            payload = json.load(f)

        if not isinstance(payload, dict) or "tables" not in payload:
            raise ValueError("Invalid export file: missing 'tables'")

        tables = payload.get("tables") or {}
        if not isinstance(tables, dict):
            raise ValueError("Invalid export file: 'tables' must be object")

        conn = None
        try:
            conn = self.get_connection()
            cur = conn.cursor()

            inserted = {"history": 0, "memories": 0, "variables": 0}

            def _insert_table(table: str, mode: str):
                if table not in tables:
                    return
                tdata = tables.get(table) or {}
                rows = tdata.get("rows") or []
                if not isinstance(rows, list) or not rows:
                    return

                existing_cols = self.get_table_columns(table)
                # не импортируем id и embedding*
                banned = {"id"}
                use_cols = [c for c in (tdata.get("columns") or []) if c in existing_cols and c not in banned and "embedding" not in str(c).lower()]
                if "character_id" in existing_cols and "character_id" not in use_cols:
                    # если в файле нет character_id в колонках — добавим сами
                    use_cols.append("character_id")

                if not use_cols:
                    return

                qcols = ", ".join([self._q_ident(c) for c in use_cols])
                placeholders = ", ".join(["?"] * len(use_cols))

                if table == "variables":
                    sql = f"INSERT OR REPLACE INTO {self._q_ident(table)} ({qcols}) VALUES ({placeholders})"
                elif table == "history":
                    sql = f"INSERT OR IGNORE INTO {self._q_ident(table)} ({qcols}) VALUES ({placeholders})"
                else:
                    # memories: без уникального ключа — просто INSERT
                    sql = f"INSERT INTO {self._q_ident(table)} ({qcols}) VALUES ({placeholders})"

                values = []
                ocid = (str(override_character_id).strip() if override_character_id else None)

                for r in rows:
                    if not isinstance(r, dict):
                        continue
                    rr = dict(r)
                    # вычищаем embedding на всякий
                    rr = {k: v for k, v in rr.items() if "embedding" not in str(k).lower()}
                    if ocid and "character_id" in existing_cols:
                        rr["character_id"] = ocid

                    values.append(tuple(rr.get(c) for c in use_cols))

                if not values:
                    return

                before = conn.total_changes
                cur.executemany(sql, values)
                after = conn.total_changes
                inserted[table] += max(0, after - before)

            if progress_callback:
                progress_callback(0, 1)

            _insert_table("history", "history")
            _insert_table("memories", "memories")
            _insert_table("variables", "variables")

            conn.commit()

            msg = [
                f"OK: {path}",
                f"history inserted: {inserted['history']}",
                f"memories inserted: {inserted['memories']}",
                f"variables written: {inserted['variables']}",
            ]
            if override_character_id:
                msg.append(f"override_character_id: {override_character_id}")
            return "\n".join(msg)

        except Exception:
            try:
                if conn:
                    conn.rollback()
            except Exception:
                pass
            raise
        finally:
            try:
                if conn:
                    conn.close()
            except Exception:
                pass