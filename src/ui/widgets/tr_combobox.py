"""TRQComboBox — QComboBox с живым переводом пунктов и без boilerplate.

Решает две повторяющиеся в коде проблемы:

1. **Дублирование** ``blockSignals(True) → clear() → addItems() → setCurrentText()
   → blockSignals(False)`` при пере-наполнении — заменяется одним
   ``set_items(...)`` / ``set_data_items(...)``.

2. **Живая смена языка** пунктов. Главное правило: ЗНАЧЕНИЕ пункта (``itemData``)
   стабильно и НЕ зависит от языка. Смена языка меняет только отображаемый ТЕКСТ
   переводимых пунктов, поэтому текущий выбор и сохранённая настройка не ломаются
   (в отличие от обычного ``addItems([_(...)])``, где значение = переведённый
   текст). Работать с выбором надо через ``current_value()`` / ``set_current_value()``.

Виды пунктов:
  * переводимый — ``add_tr_item(ru, en, value=...)``: текст = ``translate(ru, en)``,
    ``value`` по умолчанию = ``ru`` (канонический стабильный ключ);
  * данные      — ``add_data_item(text, value=...)``: текст = value, НЕ переводится
    (имена персонажей/моделей/пресетов и т.п.).

Каждый экземпляр сам подписывается на ``language_changed`` и переустанавливает
тексты переводимых пунктов вживую (Qt снимает подписку при удалении виджета).
"""

from __future__ import annotations

from typing import Iterable

from PyQt6.QtWidgets import QComboBox

from localization import translate as _tr
from localization.live import language_changed_signal

_UNSET = object()


class TRQComboBox(QComboBox):
    def __init__(self, parent=None):
        super().__init__(parent)
        # Параллельно пунктам: (ru, en) для переводимых, None — для данных.
        self._tr_pairs: list[tuple[str, str] | None] = []
        try:
            language_changed_signal().connect(self._retranslate)
        except Exception:
            pass

    # ── наполнение ───────────────────────────────────────────────────────────
    def add_tr_item(self, ru: str, en: str = "", *, value=_UNSET) -> None:
        """Переводимый пункт. ``value`` по умолчанию = ``ru`` (стабильный ключ)."""
        val = ru if value is _UNSET else value
        self._tr_pairs.append((ru, en))
        self.addItem(_tr(ru, en), val)

    def add_data_item(self, text, *, value=_UNSET) -> None:
        """Непереводимый пункт-данные. ``value`` по умолчанию = сам текст."""
        val = text if value is _UNSET else value
        self._tr_pairs.append(None)
        self.addItem(str(text), val)

    def set_items(self, items: Iterable, *, current=_UNSET, emit: bool = False) -> None:
        """Пере-наполнить с блокировкой сигналов, сохранив/задав выбор по значению.

        Каждый элемент ``items``:
          * ``str``                 → data-пункт (text == value);
          * ``(ru, en)``            → переводимый, value = ru;
          * ``(ru, en, value)``     → переводимый с явным value.
        ``current`` — какое значение выбрать после (по умолчанию — сохранить
        прежнее). ``emit`` — эмитить ли currentIndexChanged по завершении.
        """
        keep = self.current_value() if current is _UNSET else current
        blocked = self.blockSignals(True)
        try:
            self.clear()
            self._tr_pairs.clear()
            for it in items:
                if isinstance(it, (tuple, list)):
                    if len(it) >= 3:
                        self.add_tr_item(it[0], it[1], value=it[2])
                    elif len(it) == 2:
                        self.add_tr_item(it[0], it[1])
                    elif len(it) == 1:
                        self.add_data_item(it[0])
                else:
                    self.add_data_item(it)
            self._select_value(keep)
        finally:
            self.blockSignals(blocked)
        if emit:
            self.currentIndexChanged.emit(self.currentIndex())

    def set_data_items(self, texts: Iterable, *, current=_UNSET, emit: bool = False) -> None:
        """Чисто-данные список (замена ручного blockSignals/clear/addItems)."""
        self.set_items([str(t) for t in texts], current=current, emit=emit)

    # ── выбор по значению (язык-независимо) ──────────────────────────────────
    def current_value(self):
        data = self.currentData()
        return data if data is not None else self.currentText()

    def set_current_value(self, value, *, emit: bool = False) -> bool:
        blocked = self.blockSignals(not emit)
        try:
            ok = self._select_value(value)
        finally:
            self.blockSignals(blocked)
        return ok

    def _select_value(self, value) -> bool:
        if value is _UNSET or value is None:
            return False
        idx = self.findData(value)
        if idx < 0:
            idx = self.findText(str(value))
        if idx >= 0:
            self.setCurrentIndex(idx)
            return True
        return False

    # ── live ─────────────────────────────────────────────────────────────────
    def _retranslate(self, *_):
        blocked = self.blockSignals(True)
        try:
            for i, pair in enumerate(self._tr_pairs):
                if pair is not None and i < self.count():
                    self.setItemText(i, _tr(pair[0], pair[1]))
        finally:
            self.blockSignals(blocked)


__all__ = ["TRQComboBox"]
