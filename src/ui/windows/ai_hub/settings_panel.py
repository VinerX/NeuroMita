"""AI Hub — Settings panel.

Lists installed configurable components for the current category in a
sidebar and renders the selected component's settings_schema via the
generic SchemaForm. Save / reset wiring at the bottom.
"""
from __future__ import annotations

from typing import Any

from PyQt6.QtCore import QSize, Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from ui.mvvm import immutable_payload, mutable_payload
from ui.windows.ai_hub.settings_presentation import (
    AIHubSettingsChanged,
    AIHubSettingsState,
    AIHubSettingsWarning,
    ApplyAIHubSettingsRows,
    ResetAIHubSettings,
    SaveAIHubSettings,
    SelectAIHubSettingsComponent,
)
from utils import getTranslationVariant as _

from .schema_renderer import SchemaForm


class SettingsPanel(QWidget):
    """Right side of the AI Hub on the "Settings" tab."""

    request_install_view = pyqtSignal()

    def __init__(self, view_model, parent=None):
        super().__init__(parent)
        self._view_model = view_model
        self._current_id: str | None = None
        self._components_revision = -1
        self._form_revision = -1
        self._errors_revision = -1
        self._rendering = False
        self._build()
        self._view_model.state_changed.connect(self.render)
        self._view_model.effect_emitted.connect(self.handle_effect)
        self.destroyed.connect(lambda *_: self._view_model.close())
        self.render(self._view_model.state)

    # ---------------------------------------------------------- build
    def _build(self) -> None:
        root = QHBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(14)

        # --- left: installed-models list
        left = QFrame()
        left.setObjectName("AIHubSettingsList")
        left.setFixedWidth(280)
        ll = QVBoxLayout(left)
        ll.setContentsMargins(14, 14, 14, 14)
        ll.setSpacing(10)

        self._header = QLabel(_("Установленные модели", "Installed models"))
        self._header.setObjectName("AIHubSettingsListHeader")
        ll.addWidget(self._header)

        self._list = QListWidget()
        self._list.setObjectName("AIHubSettingsModelList")
        self._list.itemSelectionChanged.connect(self._on_selection_changed)
        ll.addWidget(self._list, 1)
        root.addWidget(left, 0)

        # --- right: form host + actions
        right = QFrame()
        right.setObjectName("AIHubSettingsForm")
        rl = QVBoxLayout(right)
        rl.setContentsMargins(20, 18, 20, 14)
        rl.setSpacing(12)

        title_row = QHBoxLayout()
        title_row.setContentsMargins(0, 0, 0, 0)
        title_row.setSpacing(8)
        self._title = QLabel(_("Выберите модель", "Select a model"))
        self._title.setObjectName("AIHubSettingsTitle")
        title_row.addWidget(self._title, 1)
        self._dirty_dot = QLabel("●")
        self._dirty_dot.setObjectName("AIHubSettingsDirtyDot")
        self._dirty_dot.setVisible(False)
        title_row.addWidget(self._dirty_dot, 0)
        rl.addLayout(title_row)

        self._subtitle = QLabel("")
        self._subtitle.setObjectName("AIHubSettingsSubtitle")
        self._subtitle.setWordWrap(True)
        rl.addWidget(self._subtitle)

        # scrollable form host
        scroll = QScrollArea()
        scroll.setObjectName("AIHubSettingsScroll")
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setFrameShape(QFrame.Shape.NoFrame)

        self._form = SchemaForm(on_change=self._on_form_changed)
        scroll.setWidget(self._form)
        rl.addWidget(scroll, 1)

        # placeholder shown when no model is installed in the current category
        self._empty = QLabel(
            _(
                "В этой категории нет установленных моделей.\nПерейдите в раздел «Установка» и установите модель.",
                "No models installed in this category.\nGo to the «Install» section to add one.",
            )
        )
        self._empty.setObjectName("AIHubSettingsEmpty")
        self._empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._empty.setWordWrap(True)
        self._empty.setVisible(False)
        rl.addWidget(self._empty)

        # buttons
        btn_row = QHBoxLayout()
        btn_row.setContentsMargins(0, 0, 0, 0)
        btn_row.setSpacing(10)
        self._status_lbl = QLabel("")
        self._status_lbl.setObjectName("AIHubSettingsStatus")
        btn_row.addWidget(self._status_lbl, 1)

        self._btn_reset = QPushButton(_("Сбросить", "Reset"))
        self._btn_reset.setObjectName("AIHubSecondary")
        self._btn_reset.setCursor(Qt.CursorShape.PointingHandCursor)
        self._btn_reset.clicked.connect(self._on_reset)
        btn_row.addWidget(self._btn_reset, 0)

        self._btn_save = QPushButton(_("Сохранить", "Save"))
        self._btn_save.setObjectName("AIHubPrimary")
        self._btn_save.setCursor(Qt.CursorShape.PointingHandCursor)
        self._btn_save.clicked.connect(self._on_save)
        btn_row.addWidget(self._btn_save, 0)
        rl.addLayout(btn_row)

        root.addWidget(right, 1)

        # initial empty-state
        self._set_form_visible(False)
        self._set_actions_enabled(False)

    # ---------------------------------------------------------- public API
    def apply_data(self, rows: list[dict[str, Any]], category: str | None) -> None:
        self._view_model.dispatch(
            ApplyAIHubSettingsRows(
                rows=immutable_payload(list(rows or [])),
                category=category,
            )
        )

    def select_component(self, component_id: str) -> None:
        """Select an installed model by id. No-op if not installed in the
        current category."""
        cid = str(component_id or "").strip()
        if not cid:
            return
        for i in range(self._list.count()):
            item = self._list.item(i)
            if item is None:
                continue
            if str(item.data(Qt.ItemDataRole.UserRole) or "") == cid:
                self._list.setCurrentItem(item)
                return

    def retranslate(self) -> None:
        """Refresh shell labels without disturbing the edited form values."""
        self._header.setText(_("Установленные модели", "Installed models"))
        self._btn_reset.setText(_("Сбросить", "Reset"))
        self._btn_save.setText(_("Сохранить", "Save"))
        if not self._current_id:
            self._title.setText(_("Нет установленных моделей", "No installed models"))
            self._empty.setText(
                _(
                    "В этой категории нет установленных моделей.\nПерейдите в раздел «Установка» и установите модель.",
                    "No models installed in this category.\nGo to the «Install» section to add one.",
                )
            )

    # ---------------------------------------------------------- list
    def _rebuild_list(self, state: AIHubSettingsState) -> None:
        prev_id = state.selected_component_id or self._current_id
        self._list.blockSignals(True)
        try:
            self._list.clear()
            for cid, title in state.components:
                item = QListWidgetItem(title)
                item.setData(Qt.ItemDataRole.UserRole, cid)
                self._list.addItem(item)

            # restore selection if possible
            if prev_id:
                for i in range(self._list.count()):
                    if str(self._list.item(i).data(Qt.ItemDataRole.UserRole) or "") == prev_id:
                        self._list.setCurrentRow(i)
                        break

            if self._list.currentRow() < 0 and self._list.count() > 0:
                self._list.setCurrentRow(0)
        finally:
            self._list.blockSignals(False)

        if self._list.count() == 0:
            self._set_empty_state()
            return

        self._on_selection_changed()

    def _set_empty_state(self) -> None:
        self._current_id = None
        self._title.setText(_("Нет установленных моделей", "No installed models"))
        self._subtitle.setText("")
        self._dirty_dot.setVisible(False)
        self._set_form_visible(False)
        self._empty.setVisible(True)
        self._set_actions_enabled(False)

    # ---------------------------------------------------------- selection
    def _on_selection_changed(self) -> None:
        item = self._list.currentItem()
        if item is None:
            self._set_empty_state()
            return

        component_id = str(item.data(Qt.ItemDataRole.UserRole) or "").strip()
        if not component_id:
            self._set_empty_state()
            return

        if component_id != self._view_model.state.selected_component_id:
            self._view_model.dispatch(SelectAIHubSettingsComponent(component_id))

    # ---------------------------------------------------------- actions
    def _on_save(self) -> None:
        if not self._view_model.state.selected_component_id:
            return
        values = self._form.values()
        self._view_model.dispatch(SaveAIHubSettings(immutable_payload(values)))

    def _on_reset(self) -> None:
        self._view_model.dispatch(ResetAIHubSettings())

    def _on_form_changed(self) -> None:
        if not self._rendering:
            self._view_model.dispatch(AIHubSettingsChanged())

    def _set_form_visible(self, visible: bool) -> None:
        for w in self.findChildren(QScrollArea, "AIHubSettingsScroll"):
            w.setVisible(visible)

    def _set_actions_enabled(self, enabled: bool) -> None:
        self._btn_save.setEnabled(enabled)
        self._btn_reset.setEnabled(enabled)

    def render(self, state: AIHubSettingsState) -> None:
        self._rendering = True
        try:
            if state.components_revision != self._components_revision:
                self._components_revision = state.components_revision
                self._rebuild_list(state)

            self._current_id = state.selected_component_id or None
            title = next(
                (title for cid, title in state.components if cid == state.selected_component_id),
                _("Выберите модель", "Select a model"),
            )
            self._title.setText(title)

            if state.form_revision != self._form_revision:
                self._form_revision = state.form_revision
                schema = list(mutable_payload(state.schema) or [])
                values = dict(mutable_payload(state.values) or {})
                self._form.clear_field_errors()
                if schema:
                    self._form.set_schema(schema)
                    self._form.set_values(values)
                    self._empty.setVisible(False)
                    self._set_form_visible(True)
                else:
                    self._set_form_visible(False)
                    self._empty.setText(
                        state.status_text
                        or _("У этой модели нет настроек.", "This model has no settings.")
                    )
                    self._empty.setVisible(True)

            if state.errors_revision != self._errors_revision:
                self._errors_revision = state.errors_revision
                self._form.clear_field_errors()
                errors = dict(mutable_payload(state.field_errors) or {})
                for key, message in errors.items():
                    self._form.set_field_error(str(key), str(message))

            self._dirty_dot.setVisible(bool(state.dirty))
            self._status_lbl.setText(str(state.status_text or ""))
            self._list.setEnabled(not state.saving)
            enabled = bool(state.schema) and not state.loading and not state.saving
            self._set_actions_enabled(enabled)
        finally:
            self._rendering = False

    def handle_effect(self, effect) -> None:
        if isinstance(effect, AIHubSettingsWarning):
            QMessageBox.warning(
                self,
                _("Сохранение настроек", "Save settings"),
                effect.message,
            )
