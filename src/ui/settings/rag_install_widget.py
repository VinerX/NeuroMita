from __future__ import annotations

from PyQt6.QtWidgets import QLabel, QPushButton, QVBoxLayout, QWidget

from ui.settings.rag_install_presentation import ActivateRagInstall, OpenRagAiHub
from utils import getTranslationVariant as _


class RagInstallStatusWidget(QWidget):
    def __init__(self, view_model, target: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._view_model = view_model
        self._target = str(target)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)

        self._backend = self._label()
        self._secondary = self._label()
        self._tertiary = self._label()
        self._button = QPushButton("", self)
        self._button.setVisible(False)
        self._button.clicked.connect(
            lambda: self._view_model.dispatch(OpenRagAiHub(self._target))
        )

        layout.addWidget(self._backend)
        layout.addWidget(self._secondary)
        layout.addWidget(self._tertiary)
        layout.addWidget(self._button)

        self._view_model.state_changed.connect(self.render)
        self.destroyed.connect(lambda *_args: self._disconnect_view_model())
        self.render(self._view_model.state)
        self._view_model.dispatch(ActivateRagInstall())

    def _label(self) -> QLabel:
        label = QLabel("", self)
        label.setStyleSheet("color: #aaa; font-size: 11px;")
        return label

    def render(self, state) -> None:
        is_embeddings = self._target == "embeddings"
        target = state.embeddings if is_embeddings else state.reranker
        self._backend.setText(self._line("Backend:", "Backend:", target.backend, target.loading))
        if is_embeddings:
            self._secondary.setText(self._line("Индекс:", "Index:", target.index, target.loading))
            self._tertiary.setVisible(False)
        else:
            self._secondary.setText(self._line("Модель:", "Model:", target.model, target.loading))
            self._tertiary.setVisible(True)
            self._tertiary.setText(self._line("Статус:", "Status:", target.loaded, target.loading))
        self._button.setVisible(bool(target.button_visible))
        self._button.setEnabled(not target.button_busy)
        self._button.setText(
            _("Открытие AI Hub...", "Opening AI Hub...")
            if target.button_busy
            else _("Открыть AI Hub", "Open AI Hub")
        )

    @staticmethod
    def _line(prefix_ru: str, prefix_en: str, value: str, loading: bool) -> str:
        shown = _("Загрузка...", "Loading...") if loading else str(value)
        return _(prefix_ru, prefix_en) + " " + shown

    def _disconnect_view_model(self) -> None:
        try:
            self._view_model.state_changed.disconnect(self.render)
        except (RuntimeError, TypeError):
            pass


def create_rag_install_status_widget(view_model, target: str) -> RagInstallStatusWidget:
    return RagInstallStatusWidget(view_model, target)