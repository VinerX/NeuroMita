# src/ui/settings/api_settings/dialogs/protocol_pipeline_dialog.py
from __future__ import annotations

from typing import List, Dict, Any, Optional

from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QListWidget, QPushButton,
    QComboBox, QDialogButtonBox
)
from PyQt6.QtCore import Qt

from utils import _


class ProtocolPipelineDialog(QDialog):
    def __init__(
        self,
        parent,
        *,
        available_transform_ids: List[str],
        base_transforms: List[Dict[str, Any]],
        current_transforms: List[Dict[str, Any]],
    ):
        super().__init__(parent)
        self.setWindowTitle(_("Pipeline transforms", "Pipeline transforms"))
        self.setModal(True)

        self._available = [str(x) for x in (available_transform_ids or []) if str(x).strip()]
        self._base = [t for t in (base_transforms or []) if isinstance(t, dict) and t.get("id")]
        self._current = [t for t in (current_transforms or []) if isinstance(t, dict) and t.get("id")]

        lay = QVBoxLayout(self)

        lay.addWidget(QLabel(_("Соберите порядок transforms для протокола (overrides на уровне пресета).",
                               "Build transform order for protocol (preset-level overrides).")))

        top = QHBoxLayout()
        self.combo = QComboBox()
        self.combo.addItems(self._available)
        btn_add = QPushButton(_("Добавить", "Add"))
        top.addWidget(self.combo, 1)
        top.addWidget(btn_add)
        lay.addLayout(top)

        self.list = QListWidget()
        lay.addWidget(self.list, 1)

        btns_row = QHBoxLayout()
        btn_up = QPushButton("↑")
        btn_down = QPushButton("↓")
        btn_remove = QPushButton(_("Удалить", "Remove"))
        btn_reset = QPushButton(_("Сбросить к базовому", "Reset to base"))
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
        box.accepted.connect(self.accept)
        box.rejected.connect(self.reject)

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

    def transforms(self) -> List[Dict[str, Any]]:
        return [dict(t) for t in self._current if isinstance(t, dict) and t.get("id")]