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
    QSizePolicy,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from ui.mvvm import immutable_payload, mutable_payload
from ui.windows.ai_hub.settings_presentation import (
    AIHubSettingsChanged,
    AIHubSettingsState,
    AIHubSettingsWarning,
    ApplyAIHubSettingsRows,
    CompileAIHubModel,
    DeleteAIHubModelCompilation,
    DiscardAIHubSettingsChanges,
    OpenAIHubCompilationDocumentation,
    ResetAIHubSettings,
    SaveAIHubSettings,
    SelectAIHubSettingsComponent,
)
from utils import getTranslationVariant as _

from .schema_renderer import SchemaForm
from .status_widgets import SettingsStatusPane, StatusIcon


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
        list_header = QHBoxLayout()
        list_header.addWidget(self._header, 1)
        self._list_spinner = StatusIcon(20)
        self._list_spinner.set_status("fa5s.circle-notch", spinning=True)
        list_header.addWidget(self._list_spinner)
        self._list_count = QLabel()
        self._list_count.setObjectName("AIHubSettingsListCount")
        list_header.addWidget(self._list_count)
        ll.addLayout(list_header)

        self._list = QListWidget()
        self._list.setObjectName("AIHubSettingsModelList")
        self._list.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._list.setTextElideMode(Qt.TextElideMode.ElideRight)
        self._list.itemSelectionChanged.connect(self._on_selection_changed)
        self._list_stack = QStackedWidget()
        self._list_stack.addWidget(self._list)
        self._list_message = QLabel()
        self._list_message.setObjectName("AIHubSettingsEmpty")
        self._list_message.setWordWrap(True)
        self._list_message.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._list_message.setContentsMargins(12, 12, 12, 12)
        self._list_stack.addWidget(self._list_message)
        ll.addWidget(self._list_stack, 1)
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
        self._title.setWordWrap(True)
        self._title.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Maximum)
        title_row.addWidget(self._title, 1)
        self._dirty_dot = QLabel("●")
        self._dirty_dot.setObjectName("AIHubSettingsDirtyDot")
        self._dirty_dot.setVisible(False)
        title_row.addWidget(self._dirty_dot, 0)
        rl.addLayout(title_row)

        self._subtitle = QLabel("")
        self._subtitle.setObjectName("AIHubSettingsSubtitle")
        self._subtitle.setWordWrap(True)
        self._subtitle.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Maximum)
        rl.addWidget(self._subtitle)

        # scrollable form host
        scroll = QScrollArea()
        scroll.setObjectName("AIHubSettingsScroll")
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setFrameShape(QFrame.Shape.NoFrame)

        self._form = SchemaForm(on_change=self._on_form_changed)
        scroll.setWidget(self._form)
        self._scroll = scroll
        self._content = QStackedWidget()
        self._content.setObjectName("AIHubSettingsContent")
        self._content.addWidget(scroll)
        self._state_pane = SettingsStatusPane()
        self._state_pane.action.clicked.connect(self._on_state_action)
        self._content.addWidget(self._state_pane)
        rl.addWidget(self._content, 1)

        self._compile_card = QFrame()
        self._compile_card.setObjectName("AIHubSettingsCompileCard")
        compile_layout = QVBoxLayout(self._compile_card)
        compile_layout.setContentsMargins(16, 14, 16, 14)
        compile_layout.setSpacing(9)
        self._compile_title = QLabel(
            _("GPU-компиляция Fish Speech+", "Fish Speech+ GPU compilation")
        )
        self._compile_title.setObjectName("AIHubSettingsCompileTitle")
        compile_layout.addWidget(self._compile_title)
        self._compile_description = QLabel(
            _(
                "torch.compile и Triton создают оптимизированные CUDA-ядра для выбранной видеокарты. "
                "Для каждой видеокарты хранится отдельный кэш, общий для Fish Speech+ и Fish Speech+ + RVC.",
                "torch.compile and Triton create optimized CUDA kernels for the selected GPU. "
                "Each GPU has a separate cache shared by Fish Speech+ and Fish Speech+ + RVC.",
            )
        )
        self._compile_description.setObjectName("AIHubSettingsCompileDescription")
        self._compile_description.setWordWrap(True)
        compile_layout.addWidget(self._compile_description)

        target_box = QFrame()
        target_box.setObjectName("AIHubSettingsCompileTarget")
        target_layout = QVBoxLayout(target_box)
        target_layout.setContentsMargins(12, 9, 12, 9)
        target_layout.setSpacing(3)
        self._compile_target_caption = QLabel(_("Целевая видеокарта", "Target GPU"))
        self._compile_target_caption.setObjectName("AIHubSettingsCompileCaption")
        target_layout.addWidget(self._compile_target_caption)
        self._compile_target = QLabel("")
        self._compile_target.setObjectName("AIHubSettingsCompileTargetValue")
        self._compile_target.setWordWrap(True)
        target_layout.addWidget(self._compile_target)
        self._compile_status = QLabel("")
        self._compile_status.setObjectName("AIHubSettingsCompileStatus")
        self._compile_status.setWordWrap(True)
        target_layout.addWidget(self._compile_status)
        compile_layout.addWidget(target_box)

        self._compile_cache_summary = QLabel("")
        self._compile_cache_summary.setObjectName("AIHubSettingsCompileDescription")
        self._compile_cache_summary.setWordWrap(True)
        compile_layout.addWidget(self._compile_cache_summary)
        compile_actions = QHBoxLayout()
        self._btn_compile_docs = QPushButton(_("Документация", "Documentation"))
        self._btn_compile_docs.setObjectName("AIHubSecondary")
        self._btn_compile_docs.setCursor(Qt.CursorShape.PointingHandCursor)
        self._btn_compile_docs.clicked.connect(
            lambda: self._view_model.dispatch(OpenAIHubCompilationDocumentation())
        )
        compile_actions.addWidget(self._btn_compile_docs)
        compile_actions.addStretch(1)
        self._btn_delete_compile = QPushButton(_("Удалить весь кэш", "Delete all cache"))
        self._btn_delete_compile.setObjectName("AIHubDanger")
        self._btn_delete_compile.setCursor(Qt.CursorShape.PointingHandCursor)
        self._btn_delete_compile.clicked.connect(self._on_delete_compilation)
        compile_actions.addWidget(self._btn_delete_compile)
        self._btn_compile = QPushButton(_("Скомпилировать", "Compile"))
        self._btn_compile.setObjectName("AIHubPrimary")
        self._btn_compile.setCursor(Qt.CursorShape.PointingHandCursor)
        self._btn_compile.clicked.connect(self._on_compile)
        compile_actions.addWidget(self._btn_compile)
        compile_layout.addLayout(compile_actions)
        self._compile_card.setVisible(False)
        self._form.set_slot_widgets({"fish_speech_compilation": self._compile_card})

        self._footer = QWidget()
        self._footer.setObjectName("AIHubSettingsFooter")
        btn_row = QHBoxLayout(self._footer)
        btn_row.setContentsMargins(0, 0, 0, 0)
        btn_row.setSpacing(10)
        self._activity_icon = StatusIcon(20)
        self._activity_icon.set_status("fa5s.circle-notch", spinning=True)
        btn_row.addWidget(self._activity_icon)
        self._status_lbl = QLabel("")
        self._status_lbl.setObjectName("AIHubSettingsStatus")
        self._status_lbl.setFixedHeight(24)
        self._status_lbl.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed)
        self._footer.setFixedHeight(44)
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
        rl.addWidget(self._footer)

        root.addWidget(right, 1)

        # initial empty-state
        self._set_form_visible(False)
        self._set_actions_enabled(False)

    # ---------------------------------------------------------- public API
    def apply_data(self, rows: list[dict[str, Any]], category: str | None, *, loading: bool = False, error: str = "") -> None:
        self._view_model.dispatch(
            ApplyAIHubSettingsRows(
                rows=immutable_payload(list(rows or [])),
                category=category,
                catalog_loading=loading,
                catalog_error=error,
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

    def selected_component_id(self) -> str:
        return str(self._view_model.state.selected_component_id or "").strip()

    def has_unsaved_changes(self) -> bool:
        """Return true even if the view-model dirty signal has not propagated yet."""
        try:
            form_dirty = bool(self._form.is_dirty())
        except Exception:
            form_dirty = False
        return bool(self._view_model.state.dirty or form_dirty)

    def confirm_discard_unsaved_changes(self) -> bool:
        """Ask before a navigation action would discard edited values."""
        if not self.has_unsaved_changes():
            return True
        answer = QMessageBox.warning(
            self,
            _("Несохранённые изменения", "Unsaved changes"),
            _(
                "Изменения настроек не сохранены. Если продолжить, они будут потеряны.",
                "Settings changes have not been saved. If you continue, they will be lost.",
            ),
            QMessageBox.StandardButton.Discard | QMessageBox.StandardButton.Cancel,
            QMessageBox.StandardButton.Cancel,
        )
        return answer == QMessageBox.StandardButton.Discard

    def discard_unsaved_changes(self) -> None:
        """Restore the last persisted values locally and mark the VM clean."""
        if not self.has_unsaved_changes():
            return
        self._rendering = True
        try:
            self._form.set_values(dict(mutable_payload(self._view_model.state.saved_values) or {}))
            self._form.clear_field_errors()
        finally:
            self._rendering = False
        self._view_model.dispatch(DiscardAIHubSettingsChanges())

    def _restore_selected_list_item(self) -> None:
        selected_id = str(self._view_model.state.selected_component_id or "").strip()
        self._list.blockSignals(True)
        try:
            for i in range(self._list.count()):
                item = self._list.item(i)
                if item is not None and str(item.data(Qt.ItemDataRole.UserRole) or "") == selected_id:
                    self._list.setCurrentItem(item)
                    return
        finally:
            self._list.blockSignals(False)

    def retranslate(self) -> None:
        """Refresh shell labels without disturbing the edited form values."""
        self._header.setText(_("Установленные модели", "Installed models"))
        self._btn_reset.setText(_("Сбросить", "Reset"))
        self._btn_save.setText(_("Сохранить", "Save"))
        self._btn_delete_compile.setText(_("Удалить весь кэш", "Delete all cache"))
        self._btn_compile_docs.setText(_("Документация", "Documentation"))
        self._compile_title.setText(
            _("GPU-компиляция Fish Speech+", "Fish Speech+ GPU compilation")
        )
        self._compile_description.setText(
            _(
                "torch.compile и Triton создают оптимизированные CUDA-ядра для выбранной видеокарты. "
                "Для каждой видеокарты хранится отдельный кэш, общий для Fish Speech+ и Fish Speech+ + RVC.",
                "torch.compile and Triton create optimized CUDA kernels for the selected GPU. "
                "Each GPU has a separate cache shared by Fish Speech+ and Fish Speech+ + RVC.",
            )
        )
        self._compile_target_caption.setText(_("Целевая видеокарта", "Target GPU"))
        self.render(self._view_model.state)

    # ---------------------------------------------------------- list
    def _rebuild_list(self, state: AIHubSettingsState) -> None:
        prev_id = state.selected_component_id or self._current_id
        self._list.blockSignals(True)
        try:
            self._list.clear()
            for cid, title in state.components:
                item = QListWidgetItem(title)
                item.setToolTip(title)
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
            if not self.confirm_discard_unsaved_changes():
                self._restore_selected_list_item()
                return
            self._view_model.dispatch(SelectAIHubSettingsComponent(component_id))

    # ---------------------------------------------------------- actions
    def _on_save(self) -> None:
        if not self._view_model.state.selected_component_id:
            return
        values = self._form.values()
        self._view_model.dispatch(SaveAIHubSettings(immutable_payload(values)))

    def _on_compile(self) -> None:
        self._view_model.dispatch(
            CompileAIHubModel(immutable_payload(self._form.values()))
        )

    def _on_reset(self) -> None:
        self._view_model.dispatch(ResetAIHubSettings())

    def _on_delete_compilation(self) -> None:
        state = self._view_model.state
        selected_device = self._selected_compile_device(state)
        answer = QMessageBox.question(
            self,
            _("Удалить весь кэш компиляции?", "Delete all compilation cache?"),
            _(
                f"Будет удалён общий кэш TorchInductor/Triton для всех видеокарт, включая {selected_device}. "
                "Fish Speech+ создаст его заново при следующей компиляции или запуске.",
                f"The shared TorchInductor/Triton cache for every GPU, including {selected_device}, will be deleted. "
                "Fish Speech+ will rebuild it during the next compilation or launch.",
            ),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if answer == QMessageBox.StandardButton.Yes:
            self._view_model.dispatch(DeleteAIHubModelCompilation())

    def _on_form_changed(self) -> None:
        if not self._rendering:
            self._view_model.dispatch(
                AIHubSettingsChanged(immutable_payload(self._form.values()))
            )

    def _set_form_visible(self, visible: bool) -> None:
        self._content.setCurrentWidget(self._scroll if visible else self._state_pane)

    def _on_state_action(self) -> None:
        if self._view_model.state.load_error and self._current_id:
            self._view_model.dispatch(SelectAIHubSettingsComponent(self._current_id))
        else:
            self.request_install_view.emit()

    def _render_content_state(self, state: AIHubSettingsState) -> None:
        has_form = bool(state.selected_component_id and state.schema and not state.loading and not state.load_error)
        self._set_form_visible(has_form)
        self._footer.setVisible(has_form)
        self._list_spinner.setVisible(state.catalog_loading)
        self._list_count.setText(str(len(state.components)))
        self._list_count.setVisible(bool(state.components) or not state.catalog_loading)
        self._list_stack.setCurrentWidget(self._list if state.components else self._list_message)
        self._list_message.setText(
            _("Проверяем установленные модели…", "Checking installed models…")
            if state.catalog_loading else _("Нет установленных моделей", "No installed models")
        )
        self._subtitle.setText(
            _("Измените параметры и сохраните настройки.", "Adjust the parameters and save your changes.")
            if has_form else _("Настройки установленных AI-компонентов", "Settings for installed AI components")
        )
        if has_form:
            return
        pane = self._state_pane
        if state.loading:
            pane.present(_("Загружаем параметры…", "Loading parameters…"),
                         _("Получаем настройки выбранной модели.", "Fetching settings for the selected model."),
                         icon="fa5s.circle-notch", loading=True)
        elif state.catalog_loading and not state.components:
            pane.present(_("Загружаем модели…", "Loading models…"),
                         _("Проверяем установленные компоненты. Их параметры появятся здесь.",
                           "Checking installed components. Their settings will appear here."),
                         icon="fa5s.circle-notch", loading=True)
        elif state.load_error or (state.catalog_error and not state.components):
            pane.present(_("Не удалось загрузить параметры", "Unable to load settings"),
                         state.load_error or state.catalog_error, icon="fa5s.exclamation-circle",
                         action=_("Повторить", "Retry") if state.load_error else _("К компонентам", "View components"))
        elif not state.components:
            pane.present(_("Пока нет установленных моделей", "No models installed yet"),
                         _("Установите модель в этой категории, чтобы настроить её параметры.",
                           "Install a model in this category to configure its parameters."),
                         icon="fa5s.box-open", action=_("К компонентам", "View components"))
        elif not state.selected_component_id:
            pane.present(_("Выберите модель", "Select a model"),
                         _("Выберите установленную модель в списке слева.", "Select an installed model from the list on the left."),
                         icon="fa5s.mouse-pointer")
        else:
            pane.present(_("Дополнительных параметров нет", "No additional parameters"),
                         _("Эта модель не предоставляет дополнительных настроек.",
                           "This model does not expose additional settings."),
                         icon="fa5s.sliders-h")

    def _set_actions_enabled(self, enabled: bool) -> None:
        self._btn_save.setEnabled(enabled)
        self._btn_reset.setEnabled(enabled)

    def _hardware_snapshot(self) -> dict[str, Any]:
        catalog = getattr(self._view_model, "_catalog", None)
        getter = getattr(catalog, "hardware_snapshot", None)
        if not callable(getter):
            return {}
        try:
            snapshot = getter()
        except Exception:
            return {}
        return dict(snapshot or {}) if isinstance(snapshot, dict) else {}

    def _cuda_display_labels(self) -> dict[str, str]:
        snapshot = self._hardware_snapshot()
        cuda = dict(snapshot.get("cuda") or {})
        devices = [
            dict(item)
            for item in (cuda.get("devices") or [])
            if isinstance(item, dict) and item.get("ordinal") is not None
        ]
        labels: dict[str, str] = {}
        for index, item in enumerate(devices):
            try:
                ordinal = int(item.get("ordinal", index))
            except (TypeError, ValueError):
                continue
            raw = f"cuda:{ordinal}"
            name = str(item.get("name") or "").strip()
            labels[raw] = f"{raw} ({name})" if name else raw
        if len(devices) == 1:
            item = devices[0]
            try:
                ordinal = int(item.get("ordinal", 0))
            except (TypeError, ValueError):
                ordinal = 0
            raw = f"cuda:{ordinal}"
            labels["cuda"] = labels.get(raw, raw)
        return labels

    def _decorate_schema_for_display(self, schema: list[dict[str, Any]]) -> list[dict[str, Any]]:
        cuda_labels = self._cuda_display_labels()
        if not cuda_labels:
            return list(schema or [])

        decorated: list[dict[str, Any]] = []
        for entry in list(schema or []):
            if not isinstance(entry, dict):
                decorated.append(entry)
                continue
            type_ = self._form._normalize_type(entry.get("type"))
            if type_ != "combobox":
                decorated.append(entry)
                continue
            options = self._form._normalize_options(entry)
            values = [str(v) for v in (options.get("values") or []) if str(v).strip()]
            if not any(value == "cuda" or value.startswith("cuda:") for value in values):
                decorated.append(entry)
                continue
            labels = dict(options.get("display_labels") or {})
            changed = False
            for value in values:
                mapped = cuda_labels.get(value)
                if mapped and labels.get(value) != mapped:
                    labels[value] = mapped
                    changed = True
            if not changed:
                decorated.append(entry)
                continue
            cloned = dict(entry)
            cloned_options = dict(options)
            cloned_options["display_labels"] = labels
            cloned["options"] = cloned_options
            decorated.append(cloned)
        return decorated

    @staticmethod
    def _selected_compile_device(state: AIHubSettingsState) -> str:
        values = dict(mutable_payload(state.values) or {})
        key = "fsprvc_fsp_device" if state.selected_component_id == "tts:medium+low" else "device"
        device = str(values.get(key) or "cuda:0").strip().lower()
        return "cuda:0" if device == "cuda" else device

    @staticmethod
    def _compile_target_label(target: dict[str, Any]) -> str:
        device = str(target.get("device") or "").strip()
        name = str(target.get("gpu_name") or "").strip()
        capability = str(target.get("compute_capability") or "").strip()
        label = device
        if name:
            label += f" — {name}"
        if capability:
            label += f" (SM {capability})"
        return label

    def _selected_compile_target(
        self,
        device: str,
        compiled_target: dict[str, Any] | None,
    ) -> dict[str, Any]:
        if compiled_target:
            return dict(compiled_target)
        try:
            ordinal = int(device.partition(":")[2])
        except (TypeError, ValueError):
            return {"device": device}
        cuda = dict(self._hardware_snapshot().get("cuda") or {})
        for item in cuda.get("devices") or []:
            if not isinstance(item, dict):
                continue
            try:
                item_ordinal = int(item.get("ordinal"))
            except (TypeError, ValueError):
                continue
            if item_ordinal != ordinal:
                continue
            capability = str(item.get("compute_capability") or "").strip().lower()
            if capability.startswith("sm_") and capability[3:].isdigit():
                digits = capability[3:]
                capability = f"{digits[:-1]}.{digits[-1]}" if len(digits) > 1 else digits
            return {
                "device": device,
                "gpu_name": str(item.get("name") or ""),
                "compute_capability": capability,
            }
        return {"device": device}

    def render(self, state: AIHubSettingsState) -> None:
        self._rendering = True
        try:
            if state.components_revision != self._components_revision:
                self._components_revision = state.components_revision
                self._rebuild_list(state)

            self._current_id = state.selected_component_id or None
            title = next(
                (title for cid, title in state.components if cid == state.selected_component_id),
                _("Параметры моделей", "Model parameters"),
            )
            self._title.setText(title)

            if state.form_revision != self._form_revision:
                self._form_revision = state.form_revision
                schema = self._decorate_schema_for_display(list(mutable_payload(state.schema) or []))
                values = dict(mutable_payload(state.values) or {})
                self._form.clear_field_errors()
                if schema != getattr(self, "_rendered_schema", None):
                    self._form.set_schema(schema)
                    self._rendered_schema = schema
                self._form.set_values(values)

            self._render_content_state(state)

            if state.errors_revision != self._errors_revision:
                self._errors_revision = state.errors_revision
                self._form.clear_field_errors()
                errors = dict(mutable_payload(state.field_errors) or {})
                for key, message in errors.items():
                    self._form.set_field_error(str(key), str(message))

            self._dirty_dot.setVisible(bool(state.dirty))
            self._status_lbl.setText(str(state.status_text or "") if state.dirty or state.save_status != "idle" or state.compile_busy else "")
            self._status_lbl.setToolTip(str(state.status_text or ""))
            color = "#a3e635" if state.save_status in {"saving", "saved"} else "#bca9bb"
            if state.save_status == "error":
                color = "#ffb4b4"
            self._activity_icon.set_status(
                "fa5s.circle-notch" if state.saving or state.compile_busy else "fa5s.check-circle" if state.save_status == "saved" else "fa5s.exclamation-circle" if state.save_status == "error" else "fa5s.circle",
                spinning=bool(state.saving or state.compile_busy), color=color,
            )
            self._list.setEnabled(not state.saving)
            self._form.setEnabled(not state.saving and not state.compile_busy)
            enabled = bool(state.schema) and not state.loading and not state.saving and not state.load_error and not state.compile_busy
            self._set_actions_enabled(enabled and state.dirty)
            self._compile_card.setVisible(bool(state.compile_available and not state.loading and not state.load_error))
            if state.compile_available:
                cache_exists = bool(state.compile_cache_exists)
                size_mb = int(state.compile_cache_size_bytes or 0) / (1024 * 1024)
                selected_device = self._selected_compile_device(state)
                targets = [
                    dict(item)
                    for item in (mutable_payload(state.compile_targets) or [])
                    if isinstance(item, dict) and str(item.get("device") or "").strip()
                ]
                target_by_device = {
                    ("cuda:0" if str(item.get("device")).strip().lower() == "cuda" else str(item.get("device")).strip().lower()): item
                    for item in targets
                }
                selected_target = target_by_device.get(selected_device)
                selected_compiled = selected_target is not None
                selected_label = self._compile_target_label(
                    self._selected_compile_target(selected_device, selected_target)
                )
                self._compile_target.setText(selected_label)
                if selected_compiled:
                    self._compile_status.setText(
                        _(
                            "● Используется старый общий кэш. Перекомпиляция создаст отдельный кэш этой видеокарты.",
                            "● Using the legacy shared cache. Recompilation will create a separate cache for this GPU.",
                        )
                        if selected_target.get("cache_layout") == "shared"
                        else _("● Кэш для этой видеокарты готов", "● Cache for this GPU is ready")
                    )
                else:
                    self._compile_status.setText(
                        _("○ Для этой видеокарты компиляция ещё не выполнена", "○ This GPU has not been compiled yet")
                    )

                if targets:
                    compiled = "; ".join(self._compile_target_label(item) for item in targets)
                    details_ru = f"Готовые GPU-кэши: {compiled}. Общий размер: {size_mb:.0f} МБ."
                    details_en = f"Ready GPU caches: {compiled}. Total size: {size_mb:.0f} MB."
                elif cache_exists:
                    details_ru = (
                        f"Общий кеш: {size_mb:.0f} МБ. Он создан старой версией, поэтому устройство неизвестно. "
                        "Перекомпилируйте для выбранной видеокарты."
                    )
                    details_en = (
                        f"Shared cache: {size_mb:.0f} MB. It was created by an older version, so its device is unknown. "
                        "Compile it again for the selected GPU."
                    )
                else:
                    details_ru = "Кэши ещё не созданы. Для каждой видеокарты будет свой кэш, общий для обеих моделей Fish Speech+."
                    details_en = "No caches have been created yet. Each GPU will have its own cache shared by both Fish Speech+ models."
                self._compile_cache_summary.setText(_(details_ru, details_en))
                self._btn_compile.setText(
                    _(
                        f"Перекомпилировать для {selected_device}",
                        f"Recompile for {selected_device}",
                    )
                    if selected_compiled
                    else _(
                        f"Скомпилировать для {selected_device}",
                        f"Compile for {selected_device}",
                    )
                )
                self._btn_delete_compile.setVisible(cache_exists)
                self._btn_compile.setEnabled(not state.compile_busy)
                self._btn_delete_compile.setEnabled(not state.compile_busy)
        finally:
            self._rendering = False

    def handle_effect(self, effect) -> None:
        if isinstance(effect, AIHubSettingsWarning):
            QMessageBox.warning(
                self,
                _("Сохранение настроек", "Save settings"),
                effect.message,
            )
