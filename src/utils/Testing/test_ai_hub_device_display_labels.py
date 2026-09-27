from __future__ import annotations

import os
import sys
from dataclasses import replace
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

pytest.importorskip("PyQt6")

from PyQt6.QtCore import QObject, pyqtSignal
from PyQt6.QtWidgets import QApplication

from ui.mvvm import immutable_payload
from ui.windows.ai_hub.settings_panel import SettingsPanel
from ui.windows.ai_hub.settings_presentation import AIHubSettingsState


_APP: QApplication | None = None


def _app() -> QApplication:
    global _APP
    _APP = QApplication.instance() or QApplication([])
    return _APP


class _CatalogStub:
    def hardware_snapshot(self) -> dict:
        return {
            "cuda": {
                "available": True,
                "devices": [
                    {
                        "ordinal": 0,
                        "name": "NVIDIA GeForce RTX 4060",
                        "compute_capability": "SM_89",
                    }
                ],
            }
        }


class _ViewModelStub(QObject):
    state_changed = pyqtSignal(object)
    effect_emitted = pyqtSignal(object)

    def __init__(self) -> None:
        super().__init__()
        self._catalog = _CatalogStub()
        self.state = AIHubSettingsState(
            components=(("tts:fish", "Fish Speech+"),),
            selected_component_id="tts:fish",
            schema=immutable_payload(
                [
                    {
                        "key": "device",
                        "label": "Device",
                        "type": "combobox",
                        "options": {
                            "values": ["cuda", "cpu"],
                            "default": "cuda",
                        },
                    }
                ]
            ),
            values=immutable_payload({"device": "cuda"}),
            components_revision=1,
            form_revision=1,
        )

    def dispatch(self, _intent) -> None:
        return None

    def close(self) -> None:
        return None


def test_single_cuda_device_gets_human_friendly_display_label() -> None:
    _app()
    vm = _ViewModelStub()
    panel = SettingsPanel(vm)
    combo = panel._form._widgets["device"]

    assert combo.currentText() == "cuda:0 (NVIDIA GeForce RTX 4060)"
    assert panel._form.values()["device"] == "cuda"
