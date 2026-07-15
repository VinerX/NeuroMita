from __future__ import annotations

import os
import sys
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

PROJECT_SRC = Path(__file__).resolve().parents[2]
if str(PROJECT_SRC) not in sys.path:
    sys.path.insert(0, str(PROJECT_SRC))

from PyQt6.QtWidgets import QApplication

from ui.chat.chat_widget import ChatWidget
from ui.widgets.mita_status_widget import MitaStatusWidget


def _app() -> QApplication:
    return QApplication.instance() or QApplication([])


def test_terminal_error_stays_visible_until_close_button_is_clicked():
    app = _app()
    chat = ChatWidget()
    status = MitaStatusWidget(chat)

    status.show_error("Network error: write operation timed out")
    status.hide_animated()
    status.show_thinking("Crazy Mita")
    status.show_success()
    app.processEvents()

    assert status.current_state == "error"
    assert not chat._typing_bar.isHidden()
    assert not chat._status_close_button.isHidden()

    chat._status_close_button.click()
    app.processEvents()

    assert status.current_state == "idle"
    assert chat._typing_bar.isHidden()
