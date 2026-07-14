from __future__ import annotations

from utils import getTranslationVariant as _


CATEGORY_ORDER = ("tts", "voices", "asr", "rag", "extras", "backend", "deps")

# Keep translation sources immutable: evaluating ``_`` during module import
# freezes the active language in a long-lived AI Hub dialog.
CATEGORY_LABEL_SOURCES = {
    "tts": ("Синтез речи (TTS)", "TTS"),
    "voices": ("Голоса Мит", "Mita Voices"),
    "asr": ("Распознавание (ASR)", "ASR"),
    "rag": ("Поиск и память (RAG)", "RAG"),
    "extras": ("Дополнительно", "Extras"),
    "backend": ("Системное ядро", "Backend"),
    "deps": ("Зависимости", "Dependencies"),
}


def category_label(key: str) -> str:
    """Return a category label in the language active at render time."""
    ru, en = CATEGORY_LABEL_SOURCES.get(str(key or ""), (str(key or ""), str(key or "")))
    return _(ru, en)

CATEGORY_ICONS = {
    "tts": "fa5s.wave-square",
    "voices": "fa5s.compact-disc",
    "asr": "fa5s.microphone",
    "rag": "fa5s.cube",
    "extras": "fa5s.puzzle-piece",
    "backend": "fa5s.microchip",
    "deps": "fa5s.plug",
}

# Map registry row categories into the sidebar buckets.
# Beat-синхронизация — это дополнительный функционал («Neural beat synchronization
# backend»), а не зависимость и не системное ядро. Кладём её в «Дополнительно».
ROW_CATEGORY_MAP = {
    "tts": "tts",
    "voices": "voices",
    "asr": "asr",
    "rag": "rag",
    "extras": "extras",
    "beats": "extras",
    "backend": "backend",
    "deps": "deps",
    "dependency": "deps",
}

STATUS_LABEL_SOURCES = {
    "ready": ("Установлена", "Installed"),
    "installed": ("Установлена", "Installed"),
    "not_installed": ("Не установлена", "Not installed"),
    "backend_missing": ("Нет ядра", "Backend missing"),
    "failed": ("Ошибка", "Failed"),
    "unknown": ("Неизвестно", "Unknown"),
}


def status_label(code: str) -> str:
    """Return a status label in the language active at render time."""
    ru, en = STATUS_LABEL_SOURCES.get(str(code or ""), (str(code or ""), str(code or "")))
    return _(ru, en)

# (icon, color)
STATUS_ICONS = {
    "ready": ("fa5s.check-circle", "#7fe38c"),
    "installed": ("fa5s.check-circle", "#7fe38c"),
    "not_installed": ("fa5s.clock", "#bca9bb"),
    "backend_missing": ("fa5s.exclamation-circle", "#e6c850"),
    "failed": ("fa5s.times-circle", "#ff7b7b"),
    "unknown": ("fa5s.question-circle", "#9ca3af"),
}
