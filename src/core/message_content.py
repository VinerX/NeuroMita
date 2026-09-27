"""Единый кодек содержимого сообщения.

Мультимодальный `content` (список частей) раньше разбирался в четырёх местах
по-своему: запись в SQLite, промпт сжатия, текст для эмбеддинга и рендер для UI.
Каждый знал ровно про два типа частей (`text`, `image_url`) и молча выбрасывал
всё остальное — часть, доехавшая до БД, после round-trip исчезала.

Здесь одно место, которое знает про части, и одно правило для незнакомых типов:
их не теряем — в БД они едут как есть, в текстовых представлениях становятся
явным плейсхолдером `[<type>]`, а сам факт встречи пишется в лог один раз.
"""
from __future__ import annotations

import json
import threading
from typing import Any, Callable, Dict, Iterable, List, Optional, Tuple

from main_logger import logger

TEXT_PART = "text"
IMAGE_PART = "image_url"

_known_types = frozenset({TEXT_PART, IMAGE_PART})
_reported_unknown: set[str] = set()
_report_lock = threading.Lock()


def _report_unknown_part(part_type: str) -> None:
    """Незнакомый тип части — не ошибка, но и не то, что можно терять молча."""
    with _report_lock:
        if part_type in _reported_unknown:
            return
        _reported_unknown.add(part_type)
    logger.warning(
        f"[MessageContentCodec] Неизвестный тип части сообщения '{part_type}': "
        f"сохраняется как есть, в текстовых представлениях — плейсхолдером."
    )


class MessageContentCodec:
    """Все преобразования `content` сообщения в одном месте."""

    # ── разбор ────────────────────────────────────────────────────────────

    @staticmethod
    def parts(content: Any) -> List[Dict[str, Any]]:
        """Список частей мультимодального content. Для строки — пустой список."""
        if not isinstance(content, list):
            return []
        return [item for item in content if isinstance(item, dict)]

    @staticmethod
    def part_type(part: Dict[str, Any]) -> str:
        return str(part.get("type") or "").strip()

    @staticmethod
    def part_text(part: Dict[str, Any]) -> str:
        """Текст части. Исторически он лежит то в `text`, то в `content`."""
        value = part.get("text")
        if value is None:
            value = part.get("content", "")
        return str(value or "").strip()

    @classmethod
    def placeholder(cls, part: Dict[str, Any]) -> str:
        part_type = cls.part_type(part)
        if part_type == IMAGE_PART:
            return "[image]"
        if not part_type:
            return ""
        if part_type not in _known_types:
            _report_unknown_part(part_type)
        return f"[{part_type}]"

    # ── текстовые представления ───────────────────────────────────────────

    @classmethod
    def to_prompt_text(cls, content: Any, *, separator: str = " ") -> str:
        """Текст для промпта: картинки и прочие части — плейсхолдерами.

        Именно здесь base64 не должен доехать до модели: без разбора частей
        сжатие истории раздувалось до сотен тысяч токенов на одну картинку.
        """
        if isinstance(content, str):
            return content.strip()
        if isinstance(content, list):
            chunks: List[str] = []
            for part in cls.parts(content):
                if cls.part_type(part) == TEXT_PART:
                    text = cls.part_text(part)
                    if text:
                        chunks.append(text)
                    continue
                placeholder = cls.placeholder(part)
                if placeholder:
                    chunks.append(placeholder)
            return separator.join(chunk for chunk in chunks if chunk).strip()
        return str(content or "").strip()

    @classmethod
    def to_embedding_text(cls, content: Any) -> str:
        """Текст для эмбеддинга: только человеческий текст, без плейсхолдеров."""
        if content is None:
            return ""
        if isinstance(content, str):
            return content.strip()
        if isinstance(content, list):
            chunks = [
                cls.part_text(part)
                for part in cls.parts(content)
                if cls.part_type(part) == TEXT_PART
            ]
            return "\n".join(chunk for chunk in chunks if chunk).strip()
        try:
            return json.dumps(content, ensure_ascii=False).strip()
        except Exception:
            return str(content).strip()

    @classmethod
    def has_visible_content(cls, content: Any) -> bool:
        """Есть ли в сообщении хоть что-то, кроме пустоты."""
        if isinstance(content, str):
            return bool(content.strip())
        if isinstance(content, list):
            for part in cls.parts(content):
                if cls.part_type(part) == TEXT_PART:
                    if cls.part_text(part):
                        return True
                    continue
                if cls.part_type(part):
                    return True
        return False

    # ── БД ────────────────────────────────────────────────────────────────

    @classmethod
    def split_for_db(
        cls,
        content: Any,
        *,
        map_image_url: Optional[Callable[[str], str]] = None,
    ) -> Tuple[str, List[Dict[str, Any]]]:
        """Делит мультимодальный content на текст и «прочие части».

        Текст едет в колонку `content`, остальное — в meta. Незнакомые части
        сохраняются без изменений: восстановление вернёт их байт в байт.
        """
        text_chunks: List[str] = []
        other_parts: List[Dict[str, Any]] = []

        for part in cls.parts(content):
            part_type = cls.part_type(part)
            if part_type == TEXT_PART:
                text_chunks.append(str(part.get("text", "") or ""))
                continue
            if part_type == IMAGE_PART and map_image_url is not None:
                image_url = dict(part.get(IMAGE_PART) or {})
                url = image_url.get("url", "")
                if isinstance(url, str) and url.startswith("data:image"):
                    stored = dict(part)
                    image_url["url"] = map_image_url(url)
                    stored[IMAGE_PART] = image_url
                    other_parts.append(stored)
                    continue
            if part_type and part_type not in _known_types:
                _report_unknown_part(part_type)
            other_parts.append(part)

        return "\n".join(text_chunks), other_parts

    @classmethod
    def merge_from_db(
        cls,
        text: Any,
        parts: Iterable[Any],
        *,
        map_image_url: Optional[Callable[[str], str]] = None,
        on_image: Optional[Callable[[Dict[str, Any], Dict[str, Any]], None]] = None,
    ) -> List[Dict[str, Any]]:
        """Собирает мультимодальный content обратно из БД.

        `on_image(clean_part, stored_part)` — побочный канал для UI (описания
        картинок). Части незнакомых типов возвращаются как есть, а не теряются.
        """
        content: List[Dict[str, Any]] = []
        if text:
            content.append({"type": TEXT_PART, "text": str(text)})

        for part in parts or ():
            if not isinstance(part, dict):
                continue
            part_type = cls.part_type(part)

            if part_type == IMAGE_PART:
                stored_image = dict(part.get(IMAGE_PART) or {})
                url = stored_image.get("url", "")
                final_url = url
                if map_image_url is not None:
                    is_local = bool(part.get("is_local_file", False))
                    if is_local or (
                        url
                        and not str(url).startswith("http")
                        and not str(url).startswith("data:")
                    ):
                        final_url = map_image_url(str(url))

                clean_part: Dict[str, Any] = {
                    "type": IMAGE_PART,
                    IMAGE_PART: {"url": final_url},
                }
                if "detail" in stored_image:
                    clean_part[IMAGE_PART]["detail"] = stored_image["detail"]
                if part.get("display_role"):
                    clean_part["display_role"] = part.get("display_role")

                content.append(clean_part)
                if on_image is not None:
                    on_image(clean_part, part)
                continue

            if part_type and part_type not in _known_types:
                _report_unknown_part(part_type)
            content.append(part)

        return content

    # ── прочее ────────────────────────────────────────────────────────────

    @classmethod
    def prepend_text(cls, content: Any, prefix: str) -> Any:
        """Клеит префикс к тексту сообщения, не теряя остальные части."""
        if not prefix:
            return content
        if isinstance(content, str):
            return prefix + content
        if isinstance(content, list):
            merged: List[Any] = []
            inserted = False
            for item in content:
                if (
                    not inserted
                    and isinstance(item, dict)
                    and cls.part_type(item) == TEXT_PART
                ):
                    updated = dict(item)
                    key = "text" if "text" in updated else "content"
                    updated[key] = prefix + str(updated.get(key, "") or "")
                    merged.append(updated)
                    inserted = True
                else:
                    merged.append(item)
            if not inserted:
                merged.insert(0, {"type": TEXT_PART, "text": prefix})
            return merged
        return prefix + str(content)

    @classmethod
    def append_text(cls, content: Any, suffix: str) -> Any:
        """Добавляет текст после content, сохраняя порядок мультимодальных частей."""
        if not suffix:
            return content
        if isinstance(content, str):
            return content + suffix
        if isinstance(content, list):
            # A dedicated final text part preserves the order: an action block
            # belongs after every original text/image part of the reply.
            return [*content, {"type": TEXT_PART, "text": suffix}]
        return str(content or "") + suffix


__all__ = ["MessageContentCodec", "TEXT_PART", "IMAGE_PART"]
