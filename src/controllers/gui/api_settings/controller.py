from __future__ import annotations

from typing import Any, Optional

from PyQt6.QtCore import QObject, QTimer, pyqtSignal, pyqtSlot, Qt
from PyQt6.QtWidgets import QMessageBox

from core.events import get_event_bus, Events
from core.services import use
from services.contracts import ProtocolBuilderService
from main_logger import logger
from utils import getTranslationVariant as _
from ui.settings.api_settings.widgets import CustomPresetListItem
from .bus_async import bus_call_async
from .protocols_mixin import ProtocolsMixin
from .editor_mixin import EditorMixin
from .presets_mixin import PresetsMixin
from .test_mixin import TestMixin
from controllers.gui.settings_data_prefetch import API_PROVIDER_NAMES


class ApiSettingsController(QObject, ProtocolsMixin, EditorMixin, PresetsMixin, TestMixin):
    test_result_received = pyqtSignal(dict)
    test_result_failed = pyqtSignal(dict)

    dispatch_to_gui = pyqtSignal(object)

    def __init__(self, view: Any, *, settings_data: Any):
        super().__init__(view)
        self.view = view
        self._settings_data = settings_data
        self.event_bus = get_event_bus()

        self.current_preset_id: Optional[int] = None
        self.current_preset_data: dict = {}
        self.custom_presets_list_items: dict[int, CustomPresetListItem] = {}

        self._is_loading_ui = False
        self._snapshot = None
        self._pending_select_id: Optional[int] = None

        self._protocols = self._load_protocol_catalog()
        self._protocol_default_id = self._pick_default_protocol_id()

        # cache for pipeline dialog
        self._transform_catalog: list[dict] = []
        self._protocol_overrides: dict = {}

        self._state_save_timer = QTimer(self)
        self._state_save_timer.setSingleShot(True)
        self._state_save_timer.timeout.connect(self._emit_save_state)

        logger.info("[API UI] ApiSettingsController init")

        self.dispatch_to_gui.connect(self._run_on_gui, type=Qt.ConnectionType.QueuedConnection)

        self._wire_ui()
        self._subscribe_bus()
        view.destroyed.connect(lambda *_args: self.close())

        # load transforms catalog (once)
        QTimer.singleShot(0, self._safe(self._load_transform_catalog_async, "load_transform_catalog_async"))

        self._populate_protocol_combo()

        QTimer.singleShot(0, lambda: logger.info("[API UI] QTimer(0) fired (Qt loop is running)"))
        QTimer.singleShot(250, self._safe(self.reload_presets_async, "reload_presets_async@startup"))
        logger.info("[API UI] ApiSettingsController ready, scheduling reload_presets_async")

    @pyqtSlot(object)
    def _run_on_gui(self, fn_obj: object):
        try:
            if callable(fn_obj):
                fn_obj()
            else:
                logger.error("[API UI] dispatch_to_gui received non-callable")
        except Exception as e:
            logger.error(f"[API UI] dispatched callable crashed: {e}", exc_info=True)
            try:
                if hasattr(self.view, "provider_label"):
                    self.view.provider_label.setText("API UI: dispatched callable crashed (see logs)")
            except Exception:
                pass

    def _bus_call_async(self, fn, on_ok, on_fail=None, *, name="bus_call"):
        return bus_call_async(
            fn,
            on_ok,
            on_fail,
            name=name,
            dispatch=lambda cb: self.dispatch_to_gui.emit(cb),
        )

    def _safe(self, fn, name: str):
        """
        Qt-сигналы часто передают лишние аргументы (clicked(bool), currentIndexChanged(int)).
        Здесь:
        1) пробуем вызвать fn(*args, **kwargs)
        2) если это TypeError из-за аргументов — пробуем fn()
        """
        def wrapper(*args, **kwargs):
            try:
                return fn(*args, **kwargs)
            except TypeError as e:
                # retry without args ONLY if args were provided
                if args or kwargs:
                    try:
                        return fn()
                    except Exception as e2:
                        logger.error(f"[API UI] handler crashed: {name}: {e2}", exc_info=True)
                        try:
                            if hasattr(self.view, "provider_label"):
                                self.view.provider_label.setText(f"API UI error: {name} (see logs)")
                        except Exception:
                            pass
                        return None

                logger.error(f"[API UI] handler crashed: {name}: {e}", exc_info=True)
                try:
                    if hasattr(self.view, "provider_label"):
                        self.view.provider_label.setText(f"API UI error: {name} (see logs)")
                except Exception:
                    pass
                return None
            except Exception as e:
                logger.error(f"[API UI] handler crashed: {name}: {e}", exc_info=True)
                try:
                    if hasattr(self.view, "provider_label"):
                        self.view.provider_label.setText(f"API UI error: {name} (see logs)")
                except Exception:
                    pass
                return None

        return wrapper

    def _wire_ui(self) -> None:
        v = self.view

        v.custom_presets_list.itemSelectionChanged.connect(self._safe(self._on_selection_changed, "selection_changed"))
        if hasattr(v.custom_presets_list, "create_requested"):
            v.custom_presets_list.create_requested.connect(self._safe(self._add_custom_preset_async, "add_preset_from_placeholder"))

        v.add_preset_btn.clicked.connect(self._safe(self._add_custom_preset_async, "add_preset"))
        v.remove_preset_btn.clicked.connect(self._safe(self._remove_custom_preset_async, "remove_preset"))
        v.rename_preset_btn.clicked.connect(self._safe(self._rename_custom_preset_async, "rename_preset"))
        v.copy_preset_btn.clicked.connect(self._safe(self._copy_custom_preset_async, "copy_preset"))
        v.move_up_btn.clicked.connect(self._safe(self._move_preset_up, "move_up"))
        v.move_down_btn.clicked.connect(self._safe(self._move_preset_down, "move_down"))

        v.save_preset_button.clicked.connect(self._safe(self._save_preset_async, "save_preset"))
        v.cancel_button.clicked.connect(self._safe(self._cancel_changes, "cancel_changes"))

        v.test_button.clicked.connect(self._safe(self._test_connection, "test_connection"))

        v.key_visibility_button.clicked.connect(self._safe(self._toggle_key_visibility, "toggle_key_visibility"))
        v.template_combo.currentIndexChanged.connect(self._safe(self._on_template_changed_async, "template_changed"))

        v.protocol_row.combo.currentIndexChanged.connect(self._safe(self._on_protocol_changed, "protocol_changed"))

        v.api_url_row.edit.textChanged.connect(self._safe(self._on_field_changed, "url_changed"))
        v.api_model_row.edit.textChanged.connect(self._safe(self._on_field_changed, "model_changed"))
        v.api_key_row.edit.textChanged.connect(self._safe(self._on_field_changed, "key_changed"))
        v.reserve_keys_row.changed.connect(self._safe(self._on_field_changed, "reserve_keys_changed"))

        if hasattr(v, "fallback_editor"):
            v.fallback_editor.changed.connect(self._safe(self._on_field_changed, "fallbacks_changed"))

        if hasattr(v, "openrouter_routing_widgets"):
            for key, widget in (v.openrouter_routing_widgets or {}).items():
                if hasattr(widget, "textChanged"):
                    widget.textChanged.connect(self._safe(self._on_field_changed, f"openrouter_routing_{key}"))
                elif hasattr(widget, "toggled"):
                    widget.toggled.connect(self._safe(self._on_field_changed, f"openrouter_routing_{key}"))
                elif hasattr(widget, "currentIndexChanged"):
                    widget.currentIndexChanged.connect(self._safe(self._on_field_changed, f"openrouter_routing_{key}"))

        # Wire generation override widgets
        for key, (chk, val_widget) in getattr(v, 'gen_override_widgets', {}).items():
            chk.toggled.connect(self._safe(self._on_field_changed, f"gen_override_enable_{key}"))
            from PyQt6.QtWidgets import QCheckBox, QLineEdit
            if isinstance(val_widget, QCheckBox):
                val_widget.toggled.connect(self._safe(self._on_field_changed, f"gen_override_value_{key}"))
            elif isinstance(val_widget, QLineEdit):
                val_widget.textChanged.connect(self._safe(self._on_field_changed, f"gen_override_value_{key}"))

        # IMPORTANT: pipeline button
        if hasattr(v, "configure_pipeline_btn"):
            v.configure_pipeline_btn.clicked.connect(self._safe(self._on_configure_pipeline_clicked, "configure_pipeline_clicked"))

        self.test_result_received.connect(self._safe(self._process_test_result, "process_test_result"))
        self.test_result_failed.connect(self._safe(self._process_test_failed, "process_test_failed"))

    def _subscribe_bus(self) -> None:
        self.event_bus.subscribe(Events.ApiPresets.TEST_RESULT, self._on_test_result, weak=False)
        self.event_bus.subscribe(Events.ApiPresets.TEST_FAILED, self._on_test_failed, weak=False)

        self.event_bus.subscribe(Events.ApiPresets.PRESET_SAVED, self._on_preset_catalog_changed, weak=False)
        self.event_bus.subscribe(Events.ApiPresets.PRESET_DELETED, self._on_preset_catalog_changed, weak=False)

    def _on_preset_catalog_changed(self, _event) -> None:
        self._settings_data.clear(API_PROVIDER_NAMES)
        self.reload_presets_async()

    def close(self) -> None:
        try:
            self.event_bus.unsubscribe_owner(self)
        except Exception:
            pass

    def _load_transform_catalog_async(self) -> None:
        def _call():
            return use(ProtocolBuilderService).list_transforms()

        def _apply(lst):
            if isinstance(lst, list):
                self._transform_catalog = [x for x in lst if isinstance(x, dict) and x.get("id")]
                logger.info(f"[API UI] Transform catalog loaded: {len(self._transform_catalog)} items")

        self._bus_call_async(_call, _apply, name="load_transform_catalog")

    def _on_configure_pipeline_clicked(self) -> None:
        """
        Открываем окно через WindowManager (GUI controller).
        """
        v = self.view
        base = self._parse_base(v.template_combo.currentData())

        # 3) если выбран шаблон — НЕ показывать конфигурацию
        if base is not None:
            QMessageBox.information(
                v,
                _("Недоступно", "Not available"),
                _("Pipeline можно настраивать только для пресетов без шаблона.",
                  "Pipeline can be configured only for presets without a template."),
            )
            return

        pid = self._current_protocol_id_ui() or self._protocol_default_id
        proto = self._protocols.get(pid) or {}
        base_transforms = proto.get("transforms") or []
        if not isinstance(base_transforms, list):
            base_transforms = []

        current_transforms = self._effective_transforms_for_current()

        available_ids = [str(t.get("id")) for t in (self._transform_catalog or []) if t.get("id")]

        def on_apply(new_transforms: list[dict]):
            self._protocol_overrides = dict(self._protocol_overrides or {})
            self._protocol_overrides["transforms"] = [t for t in (new_transforms or []) if isinstance(t, dict) and t.get("id")]

            # refresh view
            lines = []
            for t in self._protocol_overrides["transforms"]:
                tid = str(t.get("id") or "")
                params = t.get("params")
                lines.append(f"- {tid}" + (f"  params={params}" if params else ""))

            v.protocol_transforms_view.setPlainText("\n".join(lines))
            self._on_field_changed()

        # show via window manager
        self.event_bus.emit(Events.GUI.SHOW_WINDOW, {
            "window_id": "protocol_pipeline",
            "payload": {
                "available_ids": available_ids,
                "base_transforms": base_transforms,
                "current_transforms": current_transforms,
                "on_apply": on_apply,
                "modal": True,
            }
        })

    def _effective_transforms_for_current(self) -> list[dict]:
        pid = self._current_protocol_id_ui() or self._protocol_default_id
        base = (self._protocols.get(pid) or {}).get("transforms") or []
        if isinstance(self._protocol_overrides, dict):
            ot = self._protocol_overrides.get("transforms")
            if isinstance(ot, list):
                return [t for t in ot if isinstance(t, dict) and t.get("id")]
        return [t for t in base if isinstance(t, dict) and t.get("id")]
