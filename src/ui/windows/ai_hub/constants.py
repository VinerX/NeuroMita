from __future__ import annotations

from utils import getTranslationVariant as _


CATEGORY_ORDER = ("tts", "voices", "asr", "rag", "backend", "deps")

CATEGORY_LABELS = {
    "tts": _("Синтез речи (TTS)", "TTS"),
    "voices": _("Голоса Мит", "Mita Voices"),
    "asr": _("Распознавание (ASR)", "ASR"),
    "rag": _("Поиск и память (RAG)", "RAG"),
    "backend": _("Системное ядро", "Backend"),
    "deps": _("Зависимости", "Dependencies"),
}

CATEGORY_ICONS = {
    "tts": "fa5s.wave-square",
    "voices": "fa5s.compact-disc",
    "asr": "fa5s.microphone",
    "rag": "fa5s.cube",
    "backend": "fa5s.microchip",
    "deps": "fa5s.plug",
}

# Map registry row categories into the sidebar buckets.
# Beat-синхронизация — это backend-движок («Neural beat synchronization backend»),
# а не зависимость, поэтому кладём её в «Системное ядро», а не в «Зависимости».
ROW_CATEGORY_MAP = {
    "tts": "tts",
    "voices": "voices",
    "asr": "asr",
    "rag": "rag",
    "backend": "backend",
    "beats": "backend",
    "deps": "deps",
    "dependency": "deps",
}

STATUS_LABELS = {
    "ready": _("Установлена", "Installed"),
    "installed": _("Установлена", "Installed"),
    "not_installed": _("Не установлена", "Not installed"),
    "backend_missing": _("Нет ядра", "Backend missing"),
    "failed": _("Ошибка", "Failed"),
    "unknown": _("Неизвестно", "Unknown"),
}

# (icon, color)
STATUS_ICONS = {
    "ready": ("fa5s.check-circle", "#7fe38c"),
    "installed": ("fa5s.check-circle", "#7fe38c"),
    "not_installed": ("fa5s.clock", "#bca9bb"),
    "backend_missing": ("fa5s.exclamation-circle", "#e6c850"),
    "failed": ("fa5s.times-circle", "#ff7b7b"),
    "unknown": ("fa5s.question-circle", "#9ca3af"),
}
