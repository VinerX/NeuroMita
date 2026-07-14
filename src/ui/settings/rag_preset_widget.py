from __future__ import annotations

from PyQt6.QtCore import QSignalBlocker
from PyQt6.QtWidgets import (
    QComboBox,
    QHBoxLayout,
    QInputDialog,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from ui.settings.rag_preset_presentation import (
    ActivateRagPresets,
    ApplyRagPreset,
    ConfirmApplyRagPreset,
    ConfirmDeleteRagPreset,
    DeleteRagPreset,
    InstallMissingRagModels,
    OfferMissingRagModels,
    PromptSaveRagPreset,
    RagPresetShowError,
    RagPresetState,
    RequestApplyRagPreset,
    RequestDeleteRagPreset,
    RequestSaveRagPreset,
    SaveRagPreset,
    SelectRagPreset,
)
from utils import getTranslationVariant as _


class RagPresetWidget(QWidget):
    def __init__(self, view_model, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._view_model = view_model

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(6)

        self.combo = QComboBox(self)
        root.addWidget(self.combo)

        buttons = QHBoxLayout()
        self.apply_button = QPushButton(_("Применить", "Apply"), self)
        self.save_button = QPushButton(_("Сохранить как...", "Save as..."), self)
        self.delete_button = QPushButton(_("Удалить", "Delete"), self)
        buttons.addWidget(self.apply_button)
        buttons.addWidget(self.save_button)
        buttons.addWidget(self.delete_button)
        root.addLayout(buttons)

        self.combo.currentTextChanged.connect(
            lambda value: self._view_model.dispatch(SelectRagPreset(str(value)))
        )
        self.apply_button.clicked.connect(
            lambda: self._view_model.dispatch(RequestApplyRagPreset())
        )
        self.save_button.clicked.connect(
            lambda: self._view_model.dispatch(RequestSaveRagPreset())
        )
        self.delete_button.clicked.connect(
            lambda: self._view_model.dispatch(RequestDeleteRagPreset())
        )
        self._view_model.state_changed.connect(self.render)
        self._view_model.effect_emitted.connect(self.handle_effect)
        self.destroyed.connect(lambda *_args: self._disconnect_view_model())

        self.render(self._view_model.state)
        self._view_model.dispatch(ActivateRagPresets())

    def render(self, state: RagPresetState) -> None:
        blocker = QSignalBlocker(self.combo)
        try:
            existing = tuple(self.combo.itemText(index) for index in range(self.combo.count()))
            if existing != state.names:
                self.combo.clear()
                self.combo.addItems(list(state.names))
            if self.combo.currentText() != state.selected:
                self.combo.setCurrentText(state.selected)
        finally:
            del blocker
        self.combo.setEnabled(not state.busy)
        self.apply_button.setEnabled(state.can_apply and not state.busy)
        self.save_button.setEnabled(not state.busy)
        self.delete_button.setEnabled(state.can_delete and not state.busy)

    def handle_effect(self, effect) -> None:
        if isinstance(effect, ConfirmApplyRagPreset):
            self._confirm_apply(effect.name)
        elif isinstance(effect, PromptSaveRagPreset):
            name = self._prompt_name()
            if name:
                self._view_model.dispatch(SaveRagPreset(name))
        elif isinstance(effect, ConfirmDeleteRagPreset):
            answer = QMessageBox.question(
                self,
                _("Удалить пресет", "Delete preset"),
                _("Удалить пресет «{name}»?", "Delete preset «{name}»?").format(
                    name=effect.name
                ),
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            )
            if answer == QMessageBox.StandardButton.Yes:
                self._view_model.dispatch(DeleteRagPreset(effect.name))
        elif isinstance(effect, OfferMissingRagModels):
            models = "\n".join(
                f"• {model}"
                for _target, target_models in effect.missing
                for model in target_models
            )
            answer = QMessageBox.question(
                self,
                _("Необходима загрузка моделей", "Model download required"),
                _(
                    "Для выбранного пресета RAG отсутствуют модели:\n{models}\n\n"
                    "Добавить их в очередь загрузки?",
                    "The selected RAG preset needs these models:\n{models}\n\n"
                    "Add them to the download queue?",
                ).format(models=models),
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.Yes,
            )
            if answer == QMessageBox.StandardButton.Yes:
                self._view_model.dispatch(
                    InstallMissingRagModels(tuple(target for target, _models in effect.missing))
                )
        elif isinstance(effect, RagPresetShowError):
            QMessageBox.critical(self, effect.title, effect.message)

    def _confirm_apply(self, name: str) -> None:
        message = QMessageBox(self)
        message.setWindowTitle(_("Применить пресет", "Apply preset"))
        message.setText(
            _(
                "Применить пресет «{name}»?\nТекущие настройки RAG будут заменены.",
                "Apply preset «{name}»?\nCurrent RAG settings will be replaced.",
            ).format(name=name)
        )
        save_button = message.addButton(
            _("Сохранить текущие и применить", "Save current & Apply"),
            QMessageBox.ButtonRole.AcceptRole,
        )
        apply_button = message.addButton(
            _("Применить", "Apply"),
            QMessageBox.ButtonRole.DestructiveRole,
        )
        cancel_button = message.addButton(
            _("Отмена", "Cancel"),
            QMessageBox.ButtonRole.RejectRole,
        )
        message.setDefaultButton(cancel_button)
        message.exec()
        clicked = message.clickedButton()
        if clicked is apply_button:
            self._view_model.dispatch(ApplyRagPreset(name))
        elif clicked is save_button:
            saved_name = self._prompt_name()
            if saved_name:
                self._view_model.dispatch(ApplyRagPreset(name, saved_name))

    def _prompt_name(self) -> str | None:
        value, accepted = QInputDialog.getText(
            self,
            _("Сохранить пресет", "Save preset"),
            _("Название пресета:", "Preset name:"),
        )
        normalized = str(value or "").strip()
        return normalized if accepted and normalized else None

    def _disconnect_view_model(self) -> None:
        try:
            self._view_model.state_changed.disconnect(self.render)
        except (RuntimeError, TypeError):
            pass
        try:
            self._view_model.effect_emitted.disconnect(self.handle_effect)
        except (RuntimeError, TypeError):
            pass


def create_rag_preset_widget(view_model) -> RagPresetWidget:
    return RagPresetWidget(view_model)