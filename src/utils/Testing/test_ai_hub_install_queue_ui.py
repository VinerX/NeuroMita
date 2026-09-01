from __future__ import annotations

import os
import sys
from pathlib import Path


os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from PyQt6.QtWidgets import QApplication, QDialog, QFrame, QLabel, QPushButton

from ui.windows.ai_hub.dialog import AIHubDialog


_APP: QApplication | None = None


def _app() -> QApplication:
    # Ссылку на QApplication держим в модуле: если вернуть свежий объект и не
    # присвоить его, PyQt соберёт его мусором и следующий виджет уронит процесс.
    global _APP
    if _APP is None:
        _APP = QApplication.instance() or QApplication([])
    return _APP


# PyQt удаляет C++-объект вместе с последней Python-ссылкой: держим диалоги
# живыми до конца процесса, иначе сборка мусора роняет offscreen-Qt.
_ALIVE: list[AIHubDialog] = []


def _bare_dialog() -> AIHubDialog:
    """Диалог без view model: нам нужна только нижняя плашка с очередью."""
    dlg = AIHubDialog.__new__(AIHubDialog)
    QDialog.__init__(dlg)
    dlg._queue_state = {"running": None, "pending": []}
    dlg._queue_popup = None
    dlg._queue_popup_layout = None
    dlg._build_install_bar()
    _ALIVE.append(dlg)
    return dlg


def _job(task_id: str, title: str) -> dict:
    return {"task_id": task_id, "title": title}


def test_queue_chip_hidden_without_pending_jobs() -> None:
    _app()
    dlg = _bare_dialog()

    dlg._queue_state = {"running": _job("voice:install", "Озвучка"), "pending": []}
    dlg._update_install_bar_queue_chip()

    assert not dlg._install_bar_queue.isVisible()


def test_queue_chip_counts_pending_and_opens_popup() -> None:
    app = _app()
    dlg = _bare_dialog()
    dlg._queue_state = {
        "running": _job("voice:install", "Озвучка Миты"),
        "pending": [_job("rag:install", "Модель персонажа"), _job("f5:install", "F5-TTS")],
    }
    dlg._update_install_bar_queue_chip()
    dlg._install_bar.setVisible(True)
    app.processEvents()

    chip = dlg._install_bar_queue
    assert isinstance(chip, QPushButton)
    assert "2" in chip.text()

    dlg._toggle_queue_popup()
    app.processEvents()

    popup = dlg._queue_popup
    assert isinstance(popup, QFrame)
    assert popup.isVisible()

    # Текущая задача + обе ожидающие видны в popup.
    labels = " | ".join(lbl.text() for lbl in popup.findChildren(QLabel))
    assert "Озвучка Миты" in labels
    assert "Модель персонажа" in labels
    assert "F5-TTS" in labels

    # Повторный клик закрывает popup.
    dlg._toggle_queue_popup()
    app.processEvents()
    assert not popup.isVisible()


def test_popup_closes_when_queue_drains() -> None:
    app = _app()
    dlg = _bare_dialog()
    dlg._queue_state = {
        "running": _job("voice:install", "Озвучка"),
        "pending": [_job("rag:install", "Модель персонажа")],
    }
    dlg._update_install_bar_queue_chip()
    dlg._install_bar.setVisible(True)
    dlg._toggle_queue_popup()
    app.processEvents()
    assert dlg._queue_popup.isVisible()

    # Очередь опустела — чип и popup уходят.
    dlg._queue_state = {"running": None, "pending": []}
    dlg._update_install_bar_queue_chip()
    app.processEvents()

    assert not dlg._install_bar_queue.isVisible()
    assert not dlg._queue_popup.isVisible()


def test_popup_refreshes_while_open() -> None:
    app = _app()
    dlg = _bare_dialog()
    dlg._queue_state = {
        "running": _job("voice:install", "Озвучка"),
        "pending": [_job("rag:install", "Модель персонажа")],
    }
    dlg._update_install_bar_queue_chip()
    dlg._install_bar.setVisible(True)
    dlg._toggle_queue_popup()
    app.processEvents()

    dlg._queue_state = {
        "running": _job("voice:install", "Озвучка"),
        "pending": [_job("rag:install", "Модель персонажа"), _job("asr:install", "Распознавание")],
    }
    dlg._update_install_bar_queue_chip()
    app.processEvents()

    labels = " | ".join(lbl.text() for lbl in dlg._queue_popup.findChildren(QLabel))
    assert "Распознавание" in labels
    assert "2" in dlg._install_bar_queue.text()
