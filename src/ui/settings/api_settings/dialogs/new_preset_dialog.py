from __future__ import annotations

from typing import Any

from PyQt6.QtWidgets import QComboBox, QDialog, QDialogButtonBox, QFormLayout, QLineEdit, QSizePolicy, QVBoxLayout

from ui.settings.api_settings.widgets import ProviderDelegate
from utils import _


class NewPresetDialog(QDialog):
    def __init__(
        self,
        parent,
        *,
        template_options: list[tuple[str, Any]],
        initial_template_data: Any = None,
        template_presets_meta: list[Any] | None = None,
    ):
        super().__init__(parent)
        self.setModal(True)
        self.setWindowTitle(_("Новый пресет", "New preset"))

        self._last_autofill_value = ""
        self._autofill_active = False

        layout = QVBoxLayout(self)
        form = QFormLayout()
        form.setContentsMargins(0, 0, 0, 0)

        self.template_combo = QComboBox()
        self.template_combo.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.template_combo.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
        self.template_combo.setMinimumContentsLength(18)
        for label, data in template_options or []:
            self.template_combo.addItem(str(label), data)
        self.provider_delegate = ProviderDelegate(self.template_combo)
        self.provider_delegate.set_presets_meta(template_presets_meta or [])
        self.template_combo.view().setItemDelegate(self.provider_delegate)
        form.addRow(_("Шаблон", "Template"), self.template_combo)

        self.name_edit = QLineEdit()
        self.name_edit.setPlaceholderText(_("Имя по шаблону", "Name from template"))
        form.addRow(_("Имя", "Name"), self.name_edit)
        layout.addLayout(form)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self._accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

        self.template_combo.currentIndexChanged.connect(self._on_template_changed)
        self.name_edit.textEdited.connect(self._on_name_edited)

        initial_index = 0
        for idx in range(self.template_combo.count()):
            if self.template_combo.itemData(idx) == initial_template_data:
                initial_index = idx
                break
        self.template_combo.setCurrentIndex(initial_index)
        self._on_template_changed(initial_index)
        self.resize(620, self.sizeHint().height())

    def _template_name(self) -> str:
        text = str(self.template_combo.currentText() or "").strip()
        if text == _("Без шаблона", "No template"):
            return ""
        return text

    def _on_name_edited(self, text: str) -> None:
        current = str(text or "").strip()
        self._autofill_active = bool(current and current == self._last_autofill_value)

    def _on_template_changed(self, _index: int) -> None:
        current = str(self.name_edit.text() or "").strip()
        if current and not self._autofill_active and current != self._last_autofill_value:
            return

        new_name = self._template_name()
        self._last_autofill_value = new_name
        self._autofill_active = bool(new_name)
        self.name_edit.setText(new_name)

    def _accept(self) -> None:
        if not self.preset_name():
            template_name = self._template_name()
            if template_name:
                self.name_edit.setText(template_name)
            else:
                self.name_edit.setFocus()
                return
        self.accept()

    def preset_name(self) -> str:
        return str(self.name_edit.text() or "").strip()

    def selected_template_data(self) -> Any:
        return self.template_combo.currentData()
