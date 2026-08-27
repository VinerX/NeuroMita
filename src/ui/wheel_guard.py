from __future__ import annotations

from PyQt6.QtCore import QEvent, QObject
from PyQt6.QtWidgets import QAbstractScrollArea, QApplication, QComboBox


class ComboBoxWheelGuard(QObject):
    """Application-wide filter that stops the mouse wheel from changing the
    value of a *closed* combobox.

    Scrolling the page and accidentally landing on a combobox used to silently
    switch its selection. With this guard the wheel over a closed combobox is
    consumed and re-sent to the nearest scroll area, so the surrounding page
    keeps scrolling while the combobox value stays put. When the dropdown is
    open the wheel target is the popup's list view (not the QComboBox), so
    scrolling inside the open list still works normally.
    """

    def eventFilter(self, obj: QObject, event: QEvent) -> bool:  # noqa: N802
        if event.type() == QEvent.Type.Wheel and isinstance(obj, QComboBox):
            area = obj.parentWidget()
            while area is not None and not isinstance(area, QAbstractScrollArea):
                area = area.parentWidget()
            if isinstance(area, QAbstractScrollArea):
                QApplication.sendEvent(area.viewport(), event)
            return True
        return False


_GUARD: ComboBoxWheelGuard | None = None


def install_combobox_wheel_guard(app: QApplication) -> None:
    """Install the wheel guard on `app` (idempotent)."""
    global _GUARD
    if _GUARD is not None:
        return
    _GUARD = ComboBoxWheelGuard(app)
    app.installEventFilter(_GUARD)
