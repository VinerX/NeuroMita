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
Фолбэк-цепочка для прочих языков: ``catalog[lang] -> catalog[EN] -> inline en -> ru``.
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
COMPACT_UI_LANGUAGES: tuple[str, ...] = ("RU", "EN")
LANGUAGE_DISPLAY_NAMES: dict[str, str] = {
    "RU": "Русский",
    "EN": "English",
    "FR": "Français",
    "DE": "Deutsch",
    "ZH": "简体中文",
    "UK": "Українська",
    "EL": "Ελληνικά",
    "JA": "日本語",
    "KO": "한국어",
    "ES": "Español",
    "PL": "Polski",
    "RO": "Română",
    "NL": "Nederlands",
    "TR": "Türkçe",
    "PT": "Português",
    "IT": "Italiano",
}


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


def external_localization_dir() -> str | None:
    """Публичный путь к внешней папке кастомных локалей (может не существовать)."""
    return _external_dir()


def ensure_external_localization_dir() -> str | None:
    """Создаёт внешнюю папку локалей и кладёт в неё шаблон + README, если их нет.

    Возвращает путь к папке (или None, если NEUROMITA_BASE_DIR не задан).
    Нужна для кнопки «Открыть папку с языками»: пользователь кидает туда
    ``<код>.json`` (например ``pl.json``) — и язык появляется в списке выбора.
    """
    ext = _external_dir()
    if not ext:
        return None
    try:
        os.makedirs(ext, exist_ok=True)
        # Шаблон со всеми ключами (для удобного старта нового перевода).
        tpl_dst = os.path.join(ext, "_template.json")
        if not os.path.isfile(tpl_dst):
            tpl = {}
            try:
                if _res_files is not None:
                    res = _res_files(__package__).joinpath("locales", "_template.json")
                    if res.is_file():
                        tpl = json.loads(res.read_text(encoding="utf-8")) or {}
            except Exception:
                tpl = {}
            with open(tpl_dst, "w", encoding="utf-8") as f:
                json.dump(tpl, f, ensure_ascii=False, indent=2)
        readme = os.path.join(ext, "README.txt")
        if not os.path.isfile(readme):
            with open(readme, "w", encoding="utf-8") as f:
                f.write(
                    "Кастомные переводы интерфейса NeuroMita.\n\n"
                    "Как добавить язык:\n"
                    "1. Скопируйте _template.json в <код>.json (например pl.json для польского,\n"
                    "   ISO 639-1 код языка).\n"
                    "2. Переведите значения (ключи — русские строки, НЕ трогайте их).\n"
                    "3. По желанию добавьте ключ \"_name\": \"Polski\" — это имя языка в списке выбора.\n"
                    "4. Перезапустите приложение — язык появится в выборе.\n\n"
                    "Custom UI translations for NeuroMita.\n"
                    "Copy _template.json to <code>.json, translate the values (keys are the\n"
                    "Russian source strings — keep them as-is), optionally add \"_name\", restart.\n"
                )
    except Exception:
        return ext
    return ext


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


def _scan_available_languages() -> list[str]:
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


def available_languages(mode: str = "full") -> list[str]:
    """Список доступных языков для конкретного UI-контекста.

    mode='full' -> все найденные локали.
    mode='compact' -> компактный список для узких панелей (RU/EN).
    """
    langs = _scan_available_languages()
    if mode == "compact":
        return [code for code in COMPACT_UI_LANGUAGES if code in langs]
    return langs


def language_display_name(code: str) -> str:
    code = str(code or "").upper()
    if code in LANGUAGE_DISPLAY_NAMES:
        return LANGUAGE_DISPLAY_NAMES[code]
    # Кастомные/новые языки: имя можно задать ключом "_name" в JSON-каталоге.
    try:
        self_name = _catalog(code).get("_name")
        if self_name:
            return str(self_name)
    except Exception:
        pass
    return code


def translate_for_language(lang: str, ru_str: str, en_str: str = "") -> str:
    """Переводит строку в конкретный язык без чтения текущей настройки UI."""
    lang = str(lang or BASE_LANGUAGE).upper()
    if lang == BASE_LANGUAGE:
        return ru_str
    value = _catalog(lang).get(ru_str)
    if value:
        return value
    if lang != "EN":
        english_value = _catalog("EN").get(ru_str)
        if english_value:
            return english_value
    if lang == "EN" and en_str:
        return en_str
    return en_str or ru_str


class TrStr(str):
    """Строка перевода, несущая исходную пару ``(ru, en)``.

    Ведёт себя как обычный ``str`` (isinstance/сравнение/конкатенация/json),
    но дополнительно хранит исходники — чтобы фабрика виджетов могла
    зарегистрировать виджет для живой перетрансляции при смене языка.
    Конкатенация/format/`.upper()` и т.п. дают обычный ``str`` (исходники
    теряются) — это нормально: такие строки динамические и в реестр не идут.
    """

    __slots__ = ("tr_ru", "tr_en")

    def __new__(cls, value: str, ru: str, en: str = ""):
        obj = super().__new__(cls, value)
        obj.tr_ru = ru
        obj.tr_en = en
        return obj

    def __copy__(self):
        return self

    def __deepcopy__(self, memo):
        memo[id(self)] = self
        return self


def translate(ru_str: str, en_str: str = "") -> str:
    """Возвращает перевод ``ru_str`` на текущий язык.

    RU → исходная строка; иначе catalog[lang] → инлайн en → ru. Результат —
    ``TrStr``, несущий исходную пару ``(ru, en)`` для живой перетрансляции.
    """
    value = translate_for_language(_current_language(), ru_str, en_str)
    return TrStr(value, ru_str, en_str)


# Совместимые алиасы со старым API
getTranslationVariant = translate
_ = translate
