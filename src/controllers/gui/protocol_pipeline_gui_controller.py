from __future__ import annotations

from typing import Any

from PyQt6.QtWidgets import QDialog, QVBoxLayout, QHBoxLayout, QLabel, QListWidget, QPushButton, QComboBox, QDialogButtonBox
from PyQt6.QtCore import Qt

from main_logger import logger
from core.events import Events, Event
from .base_controller import BaseController


class ProtocolPipelineGuiController(BaseController):
    """
    Registers 'protocol_pipeline' dialog in WindowManager and provides showing it via Events.GUI.SHOW_WINDOW.
    """

    def subscribe_to_events(self):
        # nothing to subscribe; dialog is opened via SHOW_WINDOW
        self._ensure_registered()

    def _ensure_registered(self):
        if not self.view or not hasattr(self.view, "window_manager") or self.view.window_manager is None:
            return

        if getattr(self.view, "_protocol_pipeline_registered", False):
            return

        def factory(parent, payload: dict):
            dlg = _ProtocolPipelineDialog(parent)
            dlg.apply_payload(payload or {})
            return dlg

        def on_ready(dialog: QDialog, payload: dict):
            if hasattr(dialog, "apply_payload"):
                dialog.apply_payload(payload or {})

        self.view.window_manager.register_dialog(
            "protocol_pipeline",
            factory=factory,
            singleton=True,
            hide_on_close=True,
            modal=True,
            on_ready=on_ready,
        )
        self.view._protocol_pipeline_registered = True
        logger.info("ProtocolPipeline dialog registered in WindowManager")


class _ProtocolPipelineDialog(QDialog):
    def __init__(self, parent):
        super().__init__(parent)
        self.setWindowTitle("Pipeline transforms")
        self.setModal(True)
        self.resize(520, 520)

        self._payload: dict = {}
        self._available: list[str] = []
        self._base: list[dict] = []
        self._current: list[dict] = []

        lay = QVBoxLayout(self)
        self.lbl = QLabel("Configure transforms order (preset override).")
        self.lbl.setWordWrap(True)
        lay.addWidget(self.lbl)

        top = QHBoxLayout()
        self.combo = QComboBox()
        self.combo.setSizePolicy(self.combo.sizePolicy().horizontalPolicy(), self.combo.sizePolicy().verticalPolicy())
        btn_add = QPushButton("Add")
        top.addWidget(self.combo, 1)
        top.addWidget(btn_add)
        lay.addLayout(top)

        self.list = QListWidget()
        lay.addWidget(self.list, 1)

        btns_row = QHBoxLayout()
        btn_up = QPushButton("↑")
        btn_down = QPushButton("↓")
        btn_remove = QPushButton("Remove")
        btn_reset = QPushButton("Reset to base")
        btns_row.addWidget(btn_up)
        btns_row.addWidget(btn_down)
        btns_row.addWidget(btn_remove)
        btns_row.addStretch(1)
        btns_row.addWidget(btn_reset)
        lay.addLayout(btns_row)

        box = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        lay.addWidget(box)

        btn_add.clicked.connect(self._on_add)
        btn_remove.clicked.connect(self._on_remove)
        btn_up.clicked.connect(lambda: self._move(-1))
        btn_down.clicked.connect(lambda: self._move(1))
        btn_reset.clicked.connect(self._on_reset)
        box.accepted.connect(self._on_accept)
        box.rejected.connect(self.reject)

    def apply_payload(self, payload: dict):
        self._payload = dict(payload or {})
        self._available = [str(x) for x in (payload.get("available_ids") or []) if str(x).strip()]

        self._base = [t for t in (payload.get("base_transforms") or []) if isinstance(t, dict) and t.get("id")]
        cur = payload.get("current_transforms")
        if isinstance(cur, list) and cur:
            self._current = [t for t in cur if isinstance(t, dict) and t.get("id")]
        else:
            self._current = list(self._base)

        self.combo.blockSignals(True)
        self.combo.clear()
        self.combo.addItems(self._available)
        self.combo.blockSignals(False)

        self._reload()

    def _reload(self):
        self.list.clear()
        for t in self._current:
            self.list.addItem(str(t.get("id")))

    def _on_add(self):
        tid = str(self.combo.currentText() or "").strip()
        if not tid:
            return
        self._current.append({"id": tid})
        self._reload()

    def _on_remove(self):
        row = self.list.currentRow()
        if row < 0 or row >= len(self._current):
            return
        self._current.pop(row)
        self._reload()

    def _move(self, delta: int):
        row = self.list.currentRow()
        if row < 0 or row >= len(self._current):
            return
        new_row = row + int(delta)
        if new_row < 0 or new_row >= len(self._current):
            return
        self._current[row], self._current[new_row] = self._current[new_row], self._current[row]
        self._reload()
        self.list.setCurrentRow(new_row)

    def _on_reset(self):
        self._current = list(self._base)
        self._reload()

    def _on_accept(self):
        cb = self._payload.get("on_apply")
        if callable(cb):
            try:
                cb([dict(t) for t in self._current if isinstance(t, dict) and t.get("id")])
            except Exception as e:
                logger.error(f"pipeline on_apply failed: {e}", exc_info=True)
        self.accept()