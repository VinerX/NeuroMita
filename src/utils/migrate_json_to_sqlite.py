# File: utils/migrate_json_to_sqlite.py

import os
import json
import hashlib
import sqlite3  # kept for backward compatibility / possible external usage
from datetime import datetime
import re
from typing import Optional, Callable, Any, Dict

from managers.database_manager import DatabaseManager
from managers.history_manager import HistoryManager


def get_content_hash(text):
    if not text:
        return ""
    return hashlib.md5(str(text).encode("utf-8")).hexdigest()


def normalize_timestamp(ts_str):
    """
    Превращает старые форматы (01.01.2026_17.57 или 01.01.2026 17:58)
    в единый стандарт: %d.%m.%Y %H:%M:%S
    """
    if not ts_str or not isinstance(ts_str, str):
        return datetime.now().strftime("%d.%m.%Y %H:%M:%S")

    # 1. Заменяем "_" на пробел (01.01.2026_17.57 -> 01.01.2026 17.57)
    ts_str = ts_str.replace("_", " ")

    # 2. Если время разделено точкой (17.57 -> 17:57)
    ts_str = re.sub(r" (\d{2})\.(\d{2})$", r" \1:\2", ts_str)

    # 3. Если нет секунд, добавляем их (17:57 -> 17:57:00)
    if re.search(r" \d{2}:\d{2}$", ts_str):
        ts_str += ":00"

    # 4. Обработка ISO формата (2026-01-01T18:19:05 -> 01.01.2026 18:19:05)
    if "T" in ts_str and "-" in ts_str:
        try:
            dt = datetime.fromisoformat(ts_str.split(".")[0])  # убираем миллисекунды если есть
            return dt.strftime("%d.%m.%Y %H:%M:%S")
        except Exception:
            pass

    return ts_str


def _safe_load_json(path: str):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def _scan_counts_for_character(char_dir: str, char_id: str) -> int:
    """
    Best-effort scan to estimate total items for progress reporting.

    Counts:
      - memories entries (active + missed)
      - variables count
      - history messages (active + missed)
    """
    total = 0

    # memories
    for filename in (f"{char_id}_memories.json", f"{char_id}_missed_memories.json"):
        data = _safe_load_json(os.path.join(char_dir, filename))
        if isinstance(data, list):
            total += len(data)

    # variables + active history messages
    hist_data = _safe_load_json(os.path.join(char_dir, f"{char_id}_history.json"))
    if isinstance(hist_data, dict):
        vars_dict = hist_data.get("variables", {})
        if isinstance(vars_dict, dict):
            total += len(vars_dict)
        msgs = hist_data.get("messages", [])
        if isinstance(msgs, list):
            total += len(msgs)

    # missed history messages
    missed = _safe_load_json(os.path.join(char_dir, "missed_history.json"))
    if isinstance(missed, list):
        total += len(missed)

    return total


def migrate(
    character_id: Optional[str] = None,
    *,
    progress_callback: Optional[Callable[[int, int], Any]] = None,
) -> Dict[str, Any]:
    """
    Migrate JSON histories from Histories/<character_id>/ into SQLite (Histories/world.db).

    Params:
      - character_id:
          * None/"" -> migrate all character folders inside "Histories/"
          * "Crazy" -> migrate only Histories/Crazy/
      - progress_callback(curr, total):
          Called frequently for UI progress + cooperative cancellation (TaskWorker checks interruption there).
          total may be 0 if it couldn't be pre-scanned.

    Returns dict with stats:
      {
        "characters_processed": int,
        "history_inserted": int,
        "history_skipped": int,
        "memories_inserted": int,
        "memories_skipped": int,
        "variables_written": int,
        "errors": [str, ...]
      }
    """
    db_manager = DatabaseManager()
    conn = db_manager.get_connection()
    cursor = conn.cursor()

    histories_dir = "Histories"
    if not os.path.exists(histories_dir):
        raise FileNotFoundError(f"Directory '{histories_dir}' not found.")

    cid = str(character_id).strip() if character_id is not None else ""

    # list character folders
    if cid:
        character_folders = [cid] if os.path.isdir(os.path.join(histories_dir, cid)) else []
    else:
        character_folders = [
            d for d in os.listdir(histories_dir) if os.path.isdir(os.path.join(histories_dir, d))
        ]

    if cid and not character_folders:
        raise FileNotFoundError(f"Character folder '{cid}' not found in '{histories_dir}'.")

    stats: Dict[str, Any] = {
        "characters_processed": 0,
        "history_inserted": 0,
        "history_skipped": 0,
        "memories_inserted": 0,
        "memories_skipped": 0,
        "variables_written": 0,
        "errors": [],
    }

    # Pre-scan counts for progress (best-effort)
    total_items = 0
    try:
        for char_id in character_folders:
            char_dir = os.path.join(histories_dir, char_id)
            total_items += _scan_counts_for_character(char_dir, char_id)
    except Exception:
        total_items = 0

    done = 0

    def tick():
        nonlocal done
        done += 1
        if progress_callback:
            progress_callback(done, total_items)

    # Initial checkpoint (also serves as cooperative-cancel check in TaskWorker)
    if progress_callback:
        progress_callback(0, total_items)

    try:
        for char_id in character_folders:
            char_dir = os.path.join(histories_dir, char_id)
            stats["characters_processed"] += 1

            # Temporary HistoryManager for content normalization & image extraction
            h_manager = HistoryManager(character_name=char_id, character_id=char_id)

            # --- 1. MEMORIES (Active & Missed) ---
            memory_files = [
                (f"{char_id}_memories.json", 0),         # (filename, is_deleted)
                (f"{char_id}_missed_memories.json", 1),
            ]

            for filename, is_deleted in memory_files:
                filepath = os.path.join(char_dir, filename)
                if not os.path.exists(filepath):
                    continue

                mem_list = _safe_load_json(filepath)
                if not isinstance(mem_list, list):
                    stats["errors"].append(f"Invalid JSON in {filepath}")
                    continue

                for mem in mem_list:
                    try:
                        content = mem.get("content", "")
                        date = normalize_timestamp(mem.get("date", ""))
                        eternal_id = mem.get("N")

                        # Duplicate check: (character_id, date_created, content)
                        cursor.execute(
                            """
                            SELECT id FROM memories
                            WHERE character_id=? AND date_created=? AND content=?
                            """,
                            (char_id, date, content),
                        )
                        if cursor.fetchone():
                            stats["memories_skipped"] += 1
                            continue

                        cursor.execute(
                            """
                            INSERT INTO memories (
                                character_id, eternal_id, content, priority,
                                type, date_created, is_deleted
                            ) VALUES (?, ?, ?, ?, ?, ?, ?)
                            """,
                            (
                                char_id,
                                eternal_id,
                                content,
                                mem.get("priority", "Normal"),
                                mem.get("memory_type", "fact"),
                                date,
                                is_deleted,
                            ),
                        )
                        stats["memories_inserted"] += 1
                    except Exception as e:
                        stats["errors"].append(f"Error in memories {filepath}: {e}")
                    finally:
                        tick()

            # --- 2. VARIABLES ---
            hist_file = os.path.join(char_dir, f"{char_id}_history.json")
            if os.path.exists(hist_file):
                data = _safe_load_json(hist_file)
                if isinstance(data, dict):
                    vars_dict = data.get("variables", {})
                    if isinstance(vars_dict, dict):
                        for k, v in vars_dict.items():
                            try:
                                cursor.execute(
                                    """
                                    INSERT OR REPLACE INTO variables (character_id, key, value)
                                    VALUES (?, ?, ?)
                                    """,
                                    (char_id, k, json.dumps(v, ensure_ascii=False)),
                                )
                                stats["variables_written"] += 1
                            except Exception as e:
                                stats["errors"].append(f"Error writing variable {char_id}.{k}: {e}")
                            finally:
                                tick()
                else:
                    stats["errors"].append(f"Invalid JSON in {hist_file}")

            # --- 3. HISTORY MESSAGES (Active & Missed) ---
            messages_to_process = []

            # Active history messages
            if os.path.exists(hist_file):
                d = _safe_load_json(hist_file)
                if isinstance(d, dict):
                    for m in (d.get("messages", []) or []):
                        messages_to_process.append((m, 1))  # (message, is_active)

            # Missed history messages
            missed_hist_file = os.path.join(char_dir, "missed_history.json")
            if os.path.exists(missed_hist_file):
                d = _safe_load_json(missed_hist_file)
                if isinstance(d, list):
                    for m in d:
                        messages_to_process.append((m, 0))

            for msg_data, is_active in messages_to_process:
                try:
                    role = msg_data.get("role", "user")
                    raw_content = msg_data.get("content", "")

                    # metadata from JSON (if present)
                    temp_meta = {}
                    if "image" in msg_data:
                        temp_meta["image"] = msg_data["image"]

                    # prepare content + meta (extract base64 images to disk etc.)
                    db_content, db_meta = h_manager._prepare_message_for_db(role, raw_content, temp_meta)

                    raw_ts = msg_data.get("time") or msg_data.get("timestamp")
                    timestamp = normalize_timestamp(raw_ts)

                    # Duplicate check:
                    # include timestamp to avoid collapsing same text different times
                    cursor.execute(
                        """
                        SELECT id FROM history
                        WHERE character_id=? AND role=? AND content=? AND timestamp=? AND is_active=?
                        """,
                        (char_id, role, db_content, timestamp, is_active),
                    )
                    if cursor.fetchone():
                        stats["history_skipped"] += 1
                        continue

                    cursor.execute(
                        """
                        INSERT INTO history (
                            character_id, role, content, timestamp, is_active, meta_data
                        ) VALUES (?, ?, ?, ?, ?, ?)
                        """,
                        (char_id, role, db_content, timestamp, is_active, db_meta),
                    )
                    stats["history_inserted"] += 1
                except Exception as e:
                    stats["errors"].append(f"Error in history for {char_id}: {e}")
                finally:
                    tick()

        try:
            conn.commit()
        except Exception:
            pass

        return stats

    finally:
        try:
            conn.close()
        except Exception:
            pass


if __name__ == "__main__":
    # CLI usage: migrate all
    res = migrate()
    print("--- Migration finished successfully ---")
    print(res)