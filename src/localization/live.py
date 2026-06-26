"""Live-смена языка интерфейса без перезапуска приложения.

Идея: текст, который «живёт» в виджете (надписи, заголовки, тултипы, вкладки),
регистрируется вместе со СПОСОБОМ его переустановки. При смене языка
``refresh_all()`` заново вычисляет перевод и применяет его — окна/контроллеры
НЕ пересоздаются, поэтому подписки на EventBus не плодятся (главная грабля
прошлой попытки PR #59).

Два механизма:
  * ``tr_set(widget, ru, en, setter)`` — ставит перевод и регистрирует виджет.
    Подходит для прямых ``setText``/``setToolTip``/``setWindowTitle`` и т.п.
  * ``language_changed_signal()`` — Qt-сигнал ``(code: str)`` для компонентов, чей
    текст нельзя выразить простым setter (динамика, кастомная отрисовка): они
    подписываются и сами перерисовывают нужное.

Реестр держит на виджеты СЛАБЫЕ ссылки (``weakref``) — замыкание переустановки
получает виджет аргументом и не захватывает его сильно, поэтому мёртвые виджеты
корректно вычищаются и не текут.
"""

from __future__ import annotations

import weakref
from typing import Callable

from . import reload as _reload_catalogs
from . import translate

try:  # для надёжного определения «C++ объект уже удалён»
    from PyQt6 import sip as _sip
except Exception:  # pragma: no cover - окружение без PyQt
    _sip = None

# Реестр: (weakref(owner), apply_fn). apply_fn(owner) переустанавливает перевод.
_registry: list[tuple["weakref.ref", Callable]] = []
_notifier = None


def _alive(widget) -> bool:
    """True, пока за Python-обёрткой жив C++ объект виджета."""
    if widget is None:
        return False
    if _sip is not None:
        try:
            return not _sip.isdeleted(widget)
        except Exception:
            return True
    return True


def _get_notifier():
    """Ленивая инициализация QObject-нотификатора (PyQt нужен только тут)."""
    global _notifier
    if _notifier is None:
        from PyQt6.QtCore import QObject, pyqtSignal

        class _Notifier(QObject):
            language_changed = pyqtSignal(str)

        _notifier = _Notifier()
    return _notifier


def language_changed_signal():
    """Qt-сигнал ``language_changed(code: str)`` — для ручной перерисовки."""
    return _get_notifier().language_changed


def register(owner, apply_fn: Callable) -> None:
    """Зарегистрировать произвольную переустановку перевода.

    ``apply_fn(owner)`` будет вызвана на каждой смене языка, пока ``owner`` жив.
    Сам ``apply_fn`` НЕ должен сильно захватывать ``owner`` — он приходит
    аргументом, иначе weakref-очистка не сработает.
    """
    try:
        ref = weakref.ref(owner)
    except TypeError:
        # Объект не поддерживает weakref — держим сильно (без авто-очистки).
        ref = lambda _o=owner: _o  # noqa: E731
    _registry.append((ref, apply_fn))


def tr_set(widget, ru: str, en: str = "", setter: str = "setText", transform=None):
    """Поставить перевод ``ru/en`` через ``widget.<setter>(...)`` и зарегистрировать.

    ``transform`` — необязательная обёртка над переведённым значением (например
    ``str.upper`` для капс-заголовков или форматтер тултипа). Возвращает
    ``widget`` — удобно оборачивать прямо в месте создания::

        title = tr_set(QLabel(), "Настройки", "Settings")
    """
    def _apply(w, ru=ru, en=en, s=setter, tf=transform):
        value = translate(ru, en)
        if tf is not None:
            value = tf(value)
        getattr(w, s)(value)

    _apply(widget)
    register(widget, _apply)
    return widget


def register_if_tr(widget, text, setter: str = "setText", transform=None):
    """Зарегистрировать виджет для live-перевода, ЕСЛИ ``text`` — это ``TrStr``.

    Текст уже выставлен (фабрикой виджета), поэтому повторно не ставим — только
    запоминаем способ переустановки. ``transform`` — необязательная обёртка над
    переведённым значением (например, форматтер тултипа). Если ``text`` —
    обычная строка (динамика/без исходников), молча ничего не делаем.
    """
    ru = getattr(text, "tr_ru", None)
    if ru is None:
        return widget
    en = getattr(text, "tr_en", "")

    def _apply(w, ru=ru, en=en, s=setter, tf=transform):
        value = translate(ru, en)
        if tf is not None:
            value = tf(value)
        getattr(w, s)(value)

    register(widget, _apply)
    return widget


def tr_tab_text(tab_widget, index: int, ru: str, en: str = ""):
    """Перевести и зарегистрировать текст вкладки ``index`` у ``QTabWidget``."""
    tab_widget.setTabText(index, translate(ru, en))
    register(
        tab_widget,
        lambda w, i=index, ru=ru, en=en: w.setTabText(i, translate(ru, en)),
    )
    return tab_widget


def refresh_all() -> None:
    """Переустановить перевод у всех живых зарегистрированных виджетов."""
    alive: list[tuple["weakref.ref", Callable]] = []
    for ref, fn in _registry:
        owner = ref()
        if not _alive(owner):
            continue
        try:
            fn(owner)
        except RuntimeError:
            # C++ объект удалён между проверкой и вызовом — выкидываем запись.
            continue
        except Exception:
            pass
        alive.append((ref, fn))
    _registry[:] = alive


def set_language(code: str) -> None:
    """Сменить язык интерфейса вживую: записать настройку и обновить UI.

    1) сохраняем ``LANGUAGE``; 2) сбрасываем кэш каталогов; 3) переустанавливаем
    переводы у зарегистрированных виджетов; 4) эмитим ``language_changed`` для
    компонентов с ручной перерисовкой.
    """
    code = str(code or "RU").upper()
    try:
        from managers.settings_manager import SettingsManager

        SettingsManager.set("LANGUAGE", code)
    except Exception:
        pass
    _reload_catalogs()
    refresh_all()
    try:
        _get_notifier().language_changed.emit(code)
    except Exception:
        pass


__all__ = [
    "register",
    "register_if_tr",
    "tr_set",
    "tr_tab_text",
    "refresh_all",
    "set_language",
    "language_changed_signal",
]
