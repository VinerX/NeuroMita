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

from main_logger import logger
from utils import getTranslationVariant as _

from .helpers import meta_from_row, status_from_row
from .schema_renderer import SchemaForm


class SettingsPanel(QWidget):
    """Right side of the AI Hub on the "Settings" tab."""

    request_install_view = pyqtSignal()

    def __init__(self, installables_controller, parent=None):
        super().__init__(parent)
        self.catalog = installables_controller
        self._rows: list[dict[str, Any]] = []
        self._category: str | None = None
        self._current_id: str | None = None
        self._build()

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

        header = QLabel(_("Установленные модели", "Installed models"))
        header.setObjectName("AIHubSettingsListHeader")
        ll.addWidget(header)

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
        """Refresh the installed-models list for the given category."""
        self._rows = list(rows or [])
        self._category = category
        self._rebuild_list()

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

    # ---------------------------------------------------------- list
    def _installed_rows(self) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        category = self._category
        for row in self._rows:
            meta = meta_from_row(row)
            if category and str(meta.get("category") or "") != category:
                continue
            status = status_from_row(row)
            if not (status.get("installed") or status.get("ready") or str(status.get("code") or "") in ("installed", "ready")):
                continue
            # Only show configurable rows. We don't have a flag in metadata,
            # but the GET_SETTINGS_SCHEMA call returns [] for non-configurable
            # components, so we use that filter lazily in selection.
            rows.append(row)
        return rows

    def _rebuild_list(self) -> None:
        prev_id = self._current_id
        self._list.blockSignals(True)
        try:
            self._list.clear()
            rows = self._installed_rows()
            for row in rows:
                meta = meta_from_row(row)
                cid = str(meta.get("id") or "")
                title = str(meta.get("title") or cid or "-")
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

        self._current_id = component_id
        self._title.setText(item.text())
        self._subtitle.setText("")
        self._dirty_dot.setVisible(False)
        self._status_lbl.setText("")
        self._form.clear_field_errors()

        schema = self._fetch_schema(component_id)
        if not schema:
            self._set_form_visible(False)
            self._empty.setText(
                _(
                    "У этой модели нет настроек.",
                    "This model has no settings.",
                )
            )
            self._empty.setVisible(True)
            self._set_actions_enabled(False)
            return

        self._empty.setVisible(False)
        self._set_form_visible(True)

        values = self._fetch_values(component_id)
        self._form.set_schema(schema)
        self._form.set_values(values)
        self._set_actions_enabled(True)
        self._update_dirty()

    # ---------------------------------------------------------- catalog calls
    def _fetch_schema(self, component_id: str) -> list[dict[str, Any]]:
        return self.catalog.settings_schema(component_id)

    def _fetch_values(self, component_id: str) -> dict[str, Any]:
        return self.catalog.load_settings(component_id)

    def _save_values(self, component_id: str, values: dict[str, Any]) -> dict[str, Any]:
        return self.catalog.save_settings(component_id, values)

    # ---------------------------------------------------------- actions
    def _on_save(self) -> None:
        if not self._current_id:
            return
        values = self._form.values()
        self._form.clear_field_errors()
        result = self._save_values(self._current_id, values)
        if result.get("ok"):
            self._status_lbl.setText(_("Сохранено", "Saved"))
            self._dirty_dot.setVisible(False)
            self._form.set_values(values)  # rebase "original" snapshot
            return

        errors = result.get("errors") if isinstance(result.get("errors"), dict) else {}
        for key, message in errors.items():
            if key == "_":
                continue
            self._form.set_field_error(str(key), str(message))
        if errors.get("_"):
            QMessageBox.warning(
                self,
                _("Сохранение настроек", "Save settings"),
                str(errors.get("_") or _("Не удалось сохранить настройки.", "Failed to save settings.")),
            )
        else:
            self._status_lbl.setText(_("Проверьте ошибки", "Check errors"))

    def _on_reset(self) -> None:
        if not self._current_id:
            return
        values = self._fetch_values(self._current_id)
        self._form.set_values(values)
        self._form.clear_field_errors()
        self._dirty_dot.setVisible(False)
        self._status_lbl.setText(_("Сброшено", "Reset"))

    def _on_form_changed(self) -> None:
        self._update_dirty()

    def _update_dirty(self) -> None:
        dirty = self._form.is_dirty()
        self._dirty_dot.setVisible(dirty)
        if dirty:
            self._status_lbl.setText(_("Есть несохранённые изменения", "Unsaved changes"))

    def _set_form_visible(self, visible: bool) -> None:
        for w in self.findChildren(QScrollArea, "AIHubSettingsScroll"):
            w.setVisible(visible)

    def _set_actions_enabled(self, enabled: bool) -> None:
        self._btn_save.setEnabled(enabled)
        self._btn_reset.setEnabled(enabled)
