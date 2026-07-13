from __future__ import annotations

import os
import sys
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from PyQt6 import sip
from PyQt6.QtWidgets import QApplication, QPushButton

from ui.windows.ai_hub.helpers import is_backend_compatible
from ui.windows.ai_hub.widgets import ModelCard


_APP: QApplication | None = None


def _app() -> QApplication:
    global _APP
    _APP = QApplication.instance() or QApplication([])
    return _APP


def teardown_module() -> None:
    global _APP
    if _APP is None:
        return
    _APP.closeAllWindows()
    _APP.quit()
    sip.delete(_APP)
    _APP = None


def _row(*, backend: str = "onnx", ready: bool = False) -> dict:
    return {
        "metadata": {
            "id": "asr:test",
            "item_id": "test",
            "category": "asr",
            "title": "Test model",
            "description": "Test model description",
            "backend": backend,
        },
        "status": {
            "code": "ready" if ready else "not_installed",
            "ready": ready,
            "installed": ready,
        },
    }


def test_nvidia_accepts_onnx_but_amd_rejects_cuda() -> None:
    assert is_backend_compatible("onnx", "NVIDIA")
    assert is_backend_compatible("cuda", "NVIDIA")
    assert not is_backend_compatible("cuda", "AMD")
    assert is_backend_compatible("onnx", "AMD")


def test_file_check_and_other_install_keep_card_button_neutral() -> None:
    app = _app()
    card = ModelCard(
        _row(),
        on_install=lambda _component_id: None,
        on_uninstall=lambda _component_id: None,
        on_open_settings=lambda _component_id: None,
        gpu_vendor="NVIDIA",
    )
    button = card.findChild(QPushButton, "AIHubCardPrimary")
    assert button is not None
    idle_text = button.text()

    card.set_state("checking")
    app.processEvents()
    assert not button.isEnabled()
    assert button.text() == idle_text

    card.set_state("global_busy")
    app.processEvents()
    assert not button.isEnabled()
    assert button.text() == idle_text

    card.set_state("idle")
    app.processEvents()
    assert button.isEnabled()
    assert button.text() == idle_text


def test_hardware_incompatible_backend_cannot_be_installed() -> None:
    _app()
    card = ModelCard(
        _row(backend="cuda"),
        on_install=lambda _component_id: None,
        on_uninstall=lambda _component_id: None,
        on_open_settings=lambda _component_id: None,
        gpu_vendor="AMD",
    )
    button = card.findChild(QPushButton, "AIHubCardUnavailable")
    assert button is not None
    assert not button.isEnabled()


def test_installed_component_menu_is_locked_during_install() -> None:
    app = _app()
    card = ModelCard(
        _row(ready=True),
        on_install=lambda _component_id: None,
        on_uninstall=lambda _component_id: None,
        on_open_settings=lambda _component_id: None,
        gpu_vendor="NVIDIA",
    )
    menu = card.findChild(QPushButton, "AIHubCardMenuBtn")
    assert menu is not None

    card.set_state("global_busy")
    app.processEvents()
    assert not menu.isEnabled()

    card.set_state("idle")
    app.processEvents()
    assert menu.isEnabled()
