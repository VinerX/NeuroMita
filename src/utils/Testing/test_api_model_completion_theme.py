from types import SimpleNamespace

import pytest

pytest.importorskip("PyQt6")
from PyQt6.QtCore import QCoreApplication, QEvent, Qt
from PyQt6.QtGui import QColor, QPalette
from PyQt6.QtTest import QTest
from PyQt6.QtWidgets import QApplication, QLineEdit, QVBoxLayout, QWidget

from styles.compose import get_main_window_stylesheet
from styles.theme import get_theme
from ui.settings.api_settings.ui import _build_completer

_APP = None


def test_model_popup_keeps_theme_when_only_main_window_is_styled():
    global _APP
    _APP = QApplication.instance() or QApplication([])
    previous_style = _APP.styleSheet()
    _APP.setStyleSheet("")
    root = QWidget()
    root.setStyleSheet(get_main_window_stylesheet())
    edit = QLineEdit()
    QVBoxLayout(root).addWidget(edit)
    host = SimpleNamespace(api_model_row=SimpleNamespace(edit=edit))
    _build_completer(host)
    host.api_model_list_model.setStringList(["gemini-3.6-flash", "gemini-3.5-flash"])
    popup = host.api_model_completer.popup()
    try:
        root.resize(450, 120)
        root.show()
        _APP.processEvents()
        host.api_model_completer.complete()
        _APP.processEvents()
        assert popup.parentWidget() is None
        theme = get_theme()
        for group in (QPalette.ColorGroup.Active, QPalette.ColorGroup.Inactive):
            for role, key in (
                (QPalette.ColorRole.Base, "control_bg"),
                (QPalette.ColorRole.Text, "text"),
                (QPalette.ColorRole.Highlight, "accent"),
            ):
                assert popup.palette().color(group, role) == QColor(theme[key])
        row = popup.visualRect(popup.model().index(0, 0))
        QTest.mouseClick(popup.viewport(), Qt.MouseButton.LeftButton, pos=row.center())
        assert edit.text() == "gemini-3.6-flash"
    finally:
        popup.hide()
        root.deleteLater()
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        _APP.setStyleSheet(previous_style)
