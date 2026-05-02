# src/utils/migrate_tags_to_structured_in_db.py
"""
Миграция истории в БД: парсит старые теги из content → structured_data колонка.

Обрабатывает два случая:
  1. Строки где content содержит теги (<e>...</e>, <a>...</a> и т.д.)
     → content очищается, structured_data заполняется.
  2. Строки где structured_data уже есть в meta_data (JSON), но не в колонке
     → structured_data переносится из meta_data в колонку, meta_data очищается от этого ключа.

Пропускает строки где structured_data уже есть в колонке.
"""
from __future__ import annotations

import json
import logging
from typing import Callable, Optional

logger = logging.getLogger(__name__)


def migrate(
    character_id: Optional[str] = None,
    *,
    progress_callback: Optional[Callable[[int, int], None]] = None,
) -> dict:
    """
    Запускает миграцию тегов → structured_data для всех (или конкретного) персонажей.

    Args:
        character_id: если задан — обрабатываем только этого персонажа.
                      None — обрабатываем всех.
        progress_callback: fn(current, total) — для UI прогресс-бара.

    Returns:
        dict со статистикой: rows_processed, rows_updated, rows_skipped, errors.
    """
    from managers.database_manager import DatabaseManager
    from utils.history_migration import migrate_content, has_old_tags

    db = DatabaseManager()
    stats = {"rows_processed": 0, "rows_updated": 0, "rows_skipped": 0, "errors": []}

    with db.connection() as conn:
        # Убедиться что колонка structured_data есть (могли запустить до апгрейда схемы)
        try:
            conn.execute("ALTER TABLE history ADD COLUMN structured_data TEXT")
            conn.commit()
        except Exception:
            pass  # уже есть

        # Получаем строки для обработки
        if character_id:
            cursor = conn.execute(
                """
                SELECT id, content, meta_data
                FROM history
                WHERE role = 'assistant'
                  AND character_id = ?
                  AND (structured_data IS NULL OR structured_data = '')
                ORDER BY id ASC
                """,
                (character_id,),
            )
        else:
            cursor = conn.execute(
                """
                SELECT id, content, meta_data
                FROM history
                WHERE role = 'assistant'
                  AND (structured_data IS NULL OR structured_data = '')
                ORDER BY id ASC
                """
            )

        rows = cursor.fetchall()
        total = len(rows)

        if progress_callback:
            progress_callback(0, max(total, 1))

        for i, (row_id, content, meta_data_raw) in enumerate(rows):
            stats["rows_processed"] += 1

            try:
                new_content = content
                structured_data_str = None
                new_meta_data_raw = meta_data_raw

                # Случай 1: structured_data уже лежит в meta_data — перенести в колонку
                if meta_data_raw:
                    try:
                        meta = json.loads(meta_data_raw)
                    except Exception:
                        meta = {}

                    if "structured_data" in meta:
                        sd = meta.pop("structured_data")
                        if isinstance(sd, str):
                            structured_data_str = sd
                        elif sd is not None:
                            try:
                                structured_data_str = json.dumps(sd, ensure_ascii=False)
                            except Exception:
                                structured_data_str = None

                        try:
                            new_meta_data_raw = json.dumps(meta, ensure_ascii=False) if meta else None
                        except Exception:
                            new_meta_data_raw = meta_data_raw  # не трогаем при ошибке

                # Случай 2: content содержит старые теги — распарсить
                if structured_data_str is None and isinstance(content, str) and has_old_tags(content):
                    clean_text, structured_data = migrate_content(content)
                    new_content = clean_text
                    try:
                        structured_data_str = json.dumps(structured_data, ensure_ascii=False)
                    except Exception:
                        structured_data_str = None

                if structured_data_str is not None:
                    conn.execute(
                        """
                        UPDATE history
                        SET content = ?, structured_data = ?, meta_data = ?
                        WHERE id = ?
                        """,
                        (new_content, structured_data_str, new_meta_data_raw, row_id),
                    )
                    stats["rows_updated"] += 1
                else:
                    stats["rows_skipped"] += 1

            except Exception as e:
                msg = f"Row {row_id}: {e}"
                logger.error(f"[migrate_tags_to_structured_in_db] {msg}", exc_info=True)
                stats["errors"].append(msg)
                stats["rows_skipped"] += 1

            if progress_callback and (i % 50 == 0 or i == total - 1):
                progress_callback(i + 1, max(total, 1))

        conn.commit()

    if progress_callback:
        progress_callback(total, max(total, 1))

    logger.info(
        f"[migrate_tags_to_structured_in_db] Done: "
        f"processed={stats['rows_processed']}, updated={stats['rows_updated']}, "
        f"skipped={stats['rows_skipped']}, errors={len(stats['errors'])}"
    )
    return stats
