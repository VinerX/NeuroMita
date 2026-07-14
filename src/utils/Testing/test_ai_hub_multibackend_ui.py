from __future__ import annotations

import os
import sys
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from PyQt6 import sip
from PyQt6.QtWidgets import QApplication, QLabel, QPushButton

from core.installables.compatibility import evaluate_installable_compatibility
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


def _row(*, backend: str = "onnx", ready: bool = False, vendor: str = "NVIDIA") -> dict:
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
        "compatibility": evaluate_installable_compatibility(
            component_id="asr:test",
            backend=backend,
            gpu_vendor=vendor,
        ),
    }


def test_nvidia_accepts_onnx_but_amd_rejects_cuda() -> None:
    verdict = lambda backend, vendor: evaluate_installable_compatibility(
        component_id="asr:test",
        backend=backend,
        gpu_vendor=vendor,
    )
    assert verdict("onnx", "NVIDIA")["supported"]
    assert verdict("cuda", "NVIDIA")["supported"]
    assert not verdict("cuda", "AMD")["supported"]
    assert verdict("onnx", "AMD")["supported"]
    assert verdict("onnx", "INTEL")["supported"]
    assert verdict("onnx", "CPU")["supported"]
    assert not verdict("onnx", "NVIDIA")["recommended"]
    assert verdict("onnx", "AMD")["recommended"]


def test_nvidia_onnx_card_is_allowed_but_marked_not_recommended() -> None:
    _app()
    card = ModelCard(
        _row(),
        on_install=lambda _component_id: None,
        on_uninstall=lambda _component_id: None,
        on_open_settings=lambda _component_id: None,
    )

    button = card.findChild(QPushButton, "AIHubCardPrimary")
    warning = card.findChild(QLabel, "AIHubChipNotRecommended")
    assert button is not None and button.isEnabled()
    assert warning is not None


def test_file_check_and_other_install_keep_card_button_neutral() -> None:
    app = _app()
    card = ModelCard(
        _row(),
        on_install=lambda _component_id: None,
        on_uninstall=lambda _component_id: None,
        on_open_settings=lambda _component_id: None,
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
        _row(backend="cuda", vendor="AMD"),
        on_install=lambda _component_id: None,
        on_uninstall=lambda _component_id: None,
        on_open_settings=lambda _component_id: None,
    )
    button = card.findChild(QPushButton, "AIHubCardUnavailable")
    assert button is not None
    assert not button.isEnabled()


def test_missing_canonical_compatibility_is_fail_closed() -> None:
    _app()
    row = _row()
    row.pop("compatibility")
    card = ModelCard(
        row,
        on_install=lambda _component_id: None,
        on_uninstall=lambda _component_id: None,
        on_open_settings=lambda _component_id: None,
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
    )
    menu = card.findChild(QPushButton, "AIHubCardMenuBtn")
    assert menu is not None

    card.set_state("global_busy")
    app.processEvents()
    assert not menu.isEnabled()

    card.set_state("idle")
    app.processEvents()
    assert menu.isEnabled()
