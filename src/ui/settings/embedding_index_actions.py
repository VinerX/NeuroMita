from __future__ import annotations

from PyQt6.QtCore import QTimer
from PyQt6.QtWidgets import QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget

from utils import getTranslationVariant as _


class EmbeddingIndexActionsWidget(QWidget):
    """RAG index controls with a persistent entry point to a hidden task dialog."""

    def __init__(
        self,
        gui,
        refresh_status,
        start_reindex,
        active_dialog,
    ) -> None:
        super().__init__(gui)
        self._refresh_status_callback = refresh_status
        self._start_reindex_callback = start_reindex
        self._active_dialog_callback = active_dialog

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(4)

        actions = QHBoxLayout()
        actions.setSpacing(4)
        self._index_button = QPushButton(_("Индекс нового", "Index new"))
        self._index_button.clicked.connect(self._start_or_show)
        actions.addWidget(self._index_button)
        self._refresh_button = QPushButton(_("Обновить статус", "Refresh status"))
        self._refresh_button.clicked.connect(self._refresh_status_callback)
        actions.addWidget(self._refresh_button)
        actions.addStretch()
        root.addLayout(actions)

        self._active_widget = QWidget()
        active = QHBoxLayout(self._active_widget)
        active.setContentsMargins(0, 0, 0, 0)
        active.setSpacing(6)
        self._active_label = QLabel()
        self._active_label.setWordWrap(True)
        active.addWidget(self._active_label, 1)
        self._show_button = QPushButton(_("Показать", "Show"))
        self._show_button.clicked.connect(self._show_progress)
        active.addWidget(self._show_button)
        root.addWidget(self._active_widget)

        self._timer = QTimer(self)
        self._timer.setInterval(400)
        self._timer.timeout.connect(self._refresh_task_state)
        self._timer.start()
        self._refresh_task_state()

    def _running_dialog(self):
        try:
            return self._active_dialog_callback()
        except Exception:
            return None

    def _refresh_task_state(self) -> None:
        dialog = self._running_dialog()
        active = dialog is not None
        self._active_widget.setVisible(active)
        if not active:
            self._index_button.setText(_("Индекс нового", "Index new"))
            return

        status = str(dialog.status_text() or "").strip()
        detail = str(dialog.detail_text() or "").strip()
        text = detail or status or _("Подготовка...", "Preparing...")
        self._active_label.setText(_("Индексация: {text}", "Indexing: {text}").format(text=text))
        self._index_button.setText(_("Индексация идёт", "Indexing in progress"))

    def _show_progress(self) -> None:
        dialog = self._running_dialog()
        if dialog is None:
            return
        dialog.show()
        dialog.raise_()
        dialog.activateWindow()

    def _start_or_show(self) -> None:
        dialog = self._running_dialog()
        if dialog is not None:
            self._show_progress()
            return

        self._start_reindex_callback()
        QTimer.singleShot(0, self._refresh_task_state)
