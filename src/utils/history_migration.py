# src/utils/history_migration.py
"""
Миграция старого тег-формата истории в structured (список сегментов).

Старый формат (строка в поле "content"):
    <p>0,-1,0</p><love>1</love><e>smileteeth</e><a>Щелчек</a> О, ты так говоришь!
    <e>smile</e><a>wave_hip_hop_dance</a> Тогда давайте устроим настоящий танец!
    <music>Music happy intensive</music>
    <hint>Продолжай танцевать</hint>

Новый формат (список в поле "content"):
    [{"text": "...", "emotions": [...], "animations": [...], "music": [...], ...}]
"""
from __future__ import annotations

import json
import os
import re
import shutil
from datetime import datetime
from typing import Any

from main_logger import logger


# Теги, которые пропускаем при парсинге (уже неактуальны в истории)
_SKIP_TAGS = {"p", "love", "memory"}

# Теги → поля сегмента (single-value → список)
_TAG_TO_LIST_FIELD: dict[str, str] = {
    "e":      "emotions",
    "a":      "animations",
    "ia":     "idle_animations",
    "music":  "music",
    "v":      "visual_effects",
    "c":      "commands",
    "move":   "movement_modes",
    "cloth":  "clothes",
    "inter":  "interactions",
    "fp":     "face_params",
    "f":      "face_params",
}

# Теги → scalar-поля сегмента
_TAG_TO_SCALAR_FIELD: dict[str, str] = {
    "hint":       "hint",
    "start_game": "start_game",
    "end_game":   "end_game",
    "target":     "target",
}

# Обычные теги: <tag>value</tag>
_TAG_RE = re.compile(r"<([\w]+)>(.*?)</\1>", re.DOTALL)

# Память: <+memory>...</memory> или <-memory>...</memory> (закрывается без +/-)
_MEMORY_RE = re.compile(r"<[+\-#]memory>.*?</memory>", re.DOTALL)


def _make_empty_segment() -> dict[str, Any]:
    return {
        "text":       "",
        "emotions":   [],
        "animations": [],
    }


def migrate_content(content: str) -> tuple[str, dict[str, Any]]:
    """
    Конвертирует строку старого формата в (clean_text, structured_data).

    Returns:
        clean_text    — строка без тегов (идёт в msg["content"])
        structured_data — dict с полем "segments" (идёт в msg["structured_data"])
    """
    seg = _make_empty_segment()

    # Сначала вырезаем теги памяти (у них несимметричный open/close: <+memory>...</memory>)
    remainder = _MEMORY_RE.sub(" ", content)

    for m in _TAG_RE.finditer(remainder):
        tag_name = m.group(1).lower()
        tag_value = m.group(2).strip()

        if tag_name in _SKIP_TAGS:
            pass
        elif tag_name in _TAG_TO_LIST_FIELD:
            field = _TAG_TO_LIST_FIELD[tag_name]
            if tag_value:
                seg.setdefault(field, []).append(tag_value)
        elif tag_name in _TAG_TO_SCALAR_FIELD:
            field = _TAG_TO_SCALAR_FIELD[tag_name]
            if tag_value:
                seg[field] = tag_value

    # Убираем все теги из текста
    text_clean = _TAG_RE.sub(" ", remainder)
    clean_text = " ".join(text_clean.split()).strip()
    seg["text"] = clean_text

    structured_data = {"segments": [seg]}
    return clean_text, structured_data


def _is_old_format(msg: dict) -> bool:
    """True если сообщение в старом формате — строка без structured_data."""
    return isinstance(msg.get("content"), str) and "structured_data" not in msg


def migrate_history_file(history_path: str) -> tuple[bool, int]:
    """
    Мигрирует один файл истории на месте.
    Перед изменением создаёт резервную копию рядом с файлом.

    Returns:
        (success, migrated_count) — успех и кол-во смигрированных сообщений.
    """
    if not os.path.exists(history_path):
        logger.warning(f"[migration] File not found: {history_path}")
        return False, 0

    try:
        with open(history_path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except Exception as e:
        logger.error(f"[migration] Cannot read {history_path}: {e}")
        return False, 0

    messages: list[dict] = data.get("messages", [])
    migrated = 0

    for msg in messages:
        if msg.get("role") != "assistant":
            continue
        if not _is_old_format(msg):
            continue
        content = msg["content"]

        clean_text, structured_data = migrate_content(content)
        msg["content"] = clean_text
        msg["structured_data"] = structured_data
        migrated += 1

    if migrated == 0:
        logger.info(f"[migration] Nothing to migrate in {history_path}")
        return True, 0

    # Создаём бекап
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_path = history_path.replace(".json", f"_bak_{ts}.json")
    try:
        shutil.copy2(history_path, backup_path)
        logger.info(f"[migration] Backup saved: {backup_path}")
    except Exception as e:
        logger.warning(f"[migration] Could not create backup: {e}")

    try:
        with open(history_path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        logger.info(f"[migration] Migrated {migrated} messages in {history_path}")
        return True, migrated
    except Exception as e:
        logger.error(f"[migration] Cannot write {history_path}: {e}")
        return False, 0


def migrate_character_history(character_id: str) -> tuple[bool, int]:
    """
    Мигрирует основной файл истории персонажа.
    """
    history_path = os.path.join("Histories", character_id, f"{character_id}_history.json")
    return migrate_history_file(history_path)
