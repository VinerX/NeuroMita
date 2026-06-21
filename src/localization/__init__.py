"""Лёгкая многоязычная локализация UI на JSON-каталогах.

Ключ перевода — РУССКАЯ строка (как в коде), поэтому существующие вызовы
``_(ru, en)`` / ``getTranslationVariant(ru, en)`` продолжают работать без правок,
а дополнительные языки подключаются JSON-файлами ``locales/<lang>.json`` вида::

    { "Русская строка": "Перевод", ... }

Источники каталогов (объединяются, внешний переопределяет встроенный):
  1. встроенные в пакет ``localization/locales/*.json`` (читаются zip-безопасно,
     т.к. ``src`` пакуется в ``.pyz``);
  2. внешняя папка ``NEUROMITA_BASE_DIR/Localization/*.json`` — чтобы добавить язык
     дропом файла без пересборки.

Базовый язык — RU: для него перевод не нужен, возвращается исходная строка.
Фолбэк-цепочка для прочих языков: ``catalog[lang] -> inline en -> ru`` (без исключений).
"""

from __future__ import annotations

import json
import os
import threading

try:  # пакетное чтение работает и из распакованного src, и из .pyz
    from importlib.resources import files as _res_files
except Exception:  # очень старый питон — деградируем до файловой системы
    _res_files = None

# Кэш загруженных каталогов: LANG(upper) -> { ru: translation }
_catalogs: dict[str, dict] = {}
_loaded: set[str] = set()
_lock = threading.RLock()

BASE_LANGUAGE = "RU"


def _current_language() -> str:
    """Текущий язык интерфейса из настроек (default RU)."""
    try:
        from managers.settings_manager import SettingsManager
        return str(SettingsManager.get("LANGUAGE", "RU") or "RU").upper()
    except Exception:
        return "RU"


def _external_dir() -> str | None:
    base = os.environ.get("NEUROMITA_BASE_DIR")
    if not base:
        return None
    return os.path.join(base, "Localization")


def _read_bundled(lang: str) -> dict:
    """Читает встроенный в пакет locales/<lang>.json (zip-безопасно)."""
    name = f"{lang.lower()}.json"
    try:
        if _res_files is not None:
            res = _res_files(__package__).joinpath("locales", name)
            if res.is_file():
                return json.loads(res.read_text(encoding="utf-8")) or {}
        else:  # фолбэк на файловую систему
            path = os.path.join(os.path.dirname(__file__), "locales", name)
            if os.path.isfile(path):
                with open(path, encoding="utf-8") as f:
                    return json.load(f) or {}
    except Exception:
        pass
    return {}


def _read_external(lang: str) -> dict:
    ext = _external_dir()
    if not ext:
        return {}
    path = os.path.join(ext, f"{lang.lower()}.json")
    try:
        if os.path.isfile(path):
            with open(path, encoding="utf-8") as f:
                return json.load(f) or {}
    except Exception:
        pass
    return {}


def _catalog(lang: str) -> dict:
    """Объединённый каталог языка (встроенный + внешний оверлей), с кэшем."""
    lang = lang.upper()
    if lang in _loaded:
        return _catalogs.get(lang, {})
    with _lock:
        if lang in _loaded:
            return _catalogs.get(lang, {})
        merged = dict(_read_bundled(lang))
        merged.update(_read_external(lang))  # внешний переопределяет встроенный
        _catalogs[lang] = merged
        _loaded.add(lang)
        return merged


def reload() -> None:
    """Сбрасывает кэш каталогов (например, после смены языка/правки файлов)."""
    with _lock:
        _catalogs.clear()
        _loaded.clear()


def available_languages() -> list[str]:
    """RU + все языки, для которых есть JSON (встроенный или внешний)."""
    langs = {BASE_LANGUAGE}
    # встроенные
    try:
        if _res_files is not None:
            loc = _res_files(__package__).joinpath("locales")
            if loc.is_dir():
                for entry in loc.iterdir():
                    if entry.name.endswith(".json") and not entry.name.startswith("_"):
                        langs.add(entry.name[:-5].upper())
        else:
            d = os.path.join(os.path.dirname(__file__), "locales")
            for fn in os.listdir(d):
                if fn.endswith(".json") and not fn.startswith("_"):
                    langs.add(fn[:-5].upper())
    except Exception:
        pass
    # внешние
    ext = _external_dir()
    if ext and os.path.isdir(ext):
        try:
            for fn in os.listdir(ext):
                if fn.endswith(".json") and not fn.startswith("_"):
                    langs.add(fn[:-5].upper())
        except Exception:
            pass
    return sorted(langs)


def translate(ru_str: str, en_str: str = "") -> str:
    """Возвращает перевод ``ru_str`` на текущий язык.

    RU → исходная строка; иначе catalog[lang] → инлайн en → ru.
    """
    lang = _current_language()
    if lang == BASE_LANGUAGE:
        return ru_str
    value = _catalog(lang).get(ru_str)
    if value:
        return value
    if lang == "EN" and en_str:
        return en_str
    return en_str or ru_str


# Совместимые алиасы со старым API
getTranslationVariant = translate
_ = translate
