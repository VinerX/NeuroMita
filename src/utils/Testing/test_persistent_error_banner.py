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


def test_terminal_error_survives_background_events():
    """Ошибка держится сквозь фоновые события (сжатие/hide) и не гасится сама —
    её должен снять только новый запрос или крестик."""
    app = _app()
    chat = ChatWidget()
    status = MitaStatusWidget(chat)

    status.show_error("Network error: write operation timed out")
    status.hide_animated()  # авто-гашение не трогает ошибку
    status.show_thinking({"state": "compression", "text": "Сжатие истории..."})  # фон
    status.show_success()  # фоновый успех сжатия тоже не трёт ошибку
    app.processEvents()

    assert status.current_state == "error"
    assert not chat._typing_bar.isHidden()
    assert not chat._status_close_button.isHidden()

    chat._status_close_button.click()
    app.processEvents()

    assert status.current_state == "idle"
    assert chat._typing_bar.isHidden()


def test_new_request_clears_terminal_error():
    """Новый запрос пользователя (show_thinking с именем персонажа) снимает
    залипшую терминальную ошибку — иначе она висит поверх удачного ответа."""
    app = _app()
    chat = ChatWidget()
    status = MitaStatusWidget(chat)

    status.show_error("Provider rejected request (regional restriction)")
    app.processEvents()
    assert status.current_state == "error"

    # Игрок починил сеть и отправил новое сообщение → пошёл новый «думает».
    status.show_thinking("Crazy Mita")
    app.processEvents()
    assert status.current_state == "thinking"
    assert chat._status_close_button.isHidden()  # крестик ошибки убран

    # Ответ пришёл — статус гаснет штатно.
    status.show_success()
    app.processEvents()
    assert status.current_state == "success"
