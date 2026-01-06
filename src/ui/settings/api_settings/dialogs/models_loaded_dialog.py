from __future__ import annotations

from typing import List

from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit, QListWidget,
    QPushButton, QApplication
)

from utils import _


class ModelsLoadedDialog(QDialog):
    def __init__(self, parent, *, models: List[str], message: str = ""):
        super().__init__(parent)
        self.setModal(True)
        self.setWindowTitle(_("Загруженные модели", "Loaded models"))

        self._selected: str = ""
        self._models = [str(m).strip() for m in (models or []) if str(m).strip()]

        lay = QVBoxLayout(self)

        if message:
            lab = QLabel(str(message))
            lab.setWordWrap(True)
            lay.addWidget(lab)

        self.search = QLineEdit()
        self.search.setPlaceholderText(_("Поиск...", "Search..."))
        lay.addWidget(self.search)

        self.list = QListWidget()
        self.list.addItems(self._models)
        lay.addWidget(self.list, 1)

        btn_row = QHBoxLayout()
        self.btn_use = QPushButton(_("Выбрать", "Use selected"))
        self.btn_copy = QPushButton(_("Копировать всё", "Copy all"))
        self.btn_close = QPushButton(_("Закрыть", "Close"))
        btn_row.addWidget(self.btn_use)
        btn_row.addWidget(self.btn_copy)
        btn_row.addStretch(1)
        btn_row.addWidget(self.btn_close)
        lay.addLayout(btn_row)

        self.search.textChanged.connect(self._apply_filter)
        self.btn_use.clicked.connect(self._accept_selected)
        self.list.itemDoubleClicked.connect(lambda _it: self._accept_selected())
        self.btn_copy.clicked.connect(self._copy_all)
        self.btn_close.clicked.connect(self.reject)

        self.resize(520, 520)

    def _apply_filter(self, text: str) -> None:
        needle = str(text or "").strip().lower()
        for i in range(self.list.count()):
            it = self.list.item(i)
            it.setHidden(bool(needle) and needle not in it.text().lower())

    def _accept_selected(self) -> None:
        it = self.list.currentItem()
        if not it:
            return
        self._selected = it.text().strip()
        self.accept()

    def _copy_all(self) -> None:
        QApplication.clipboard().setText("\n".join(self._models))

    def selected_model(self) -> str:
        return self._selected