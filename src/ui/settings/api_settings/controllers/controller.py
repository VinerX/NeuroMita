from __future__ import annotations

from typing import Any, Optional

from PyQt6.QtCore import QObject, QTimer, pyqtSignal, pyqtSlot, Qt

from core.events import get_event_bus, Events
from main_logger import logger
from ui.settings.api_settings.widgets import CustomPresetListItem
from .bus_async import bus_call_async
from .protocols_mixin import ProtocolsMixin
from .editor_mixin import EditorMixin
from .presets_mixin import PresetsMixin
from .test_mixin import TestMixin


class ApiSettingsController(QObject, ProtocolsMixin, EditorMixin, PresetsMixin, TestMixin):
    test_result_received = pyqtSignal(dict)
    test_result_failed = pyqtSignal(dict)

    # Thread-safe dispatcher: emit(callable) from any thread => executed in GUI thread
    dispatch_to_gui = pyqtSignal(object)

    def __init__(self, view: Any):
        super().__init__(view)
        self.view = view
        self.event_bus = get_event_bus()

        self.current_preset_id: Optional[int] = None
        self.current_preset_data: dict = {}
        self.custom_presets_list_items: dict[int, CustomPresetListItem] = {}

        self._is_loading_ui = False
        self._snapshot = None
        self._pending_select_id: Optional[int] = None

        self._protocols = self._load_protocol_catalog()
        self._protocol_default_id = self._pick_default_protocol_id()

        self._state_save_timer = QTimer(self)
        self._state_save_timer.setSingleShot(True)
        self._state_save_timer.timeout.connect(self._emit_save_state)

        logger.info("[API UI] ApiSettingsController init")

        # connect dispatcher
        self.dispatch_to_gui.connect(self._run_on_gui, type=Qt.ConnectionType.QueuedConnection)

        self._wire_ui()
        self._subscribe_bus()

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
        def wrapper(*args, **kwargs):
            try:
                return fn(*args, **kwargs)
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

        v.add_preset_btn.clicked.connect(self._safe(self._add_custom_preset_async, "add_preset"))
        v.remove_preset_btn.clicked.connect(self._safe(self._remove_custom_preset_async, "remove_preset"))
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
        v.reserve_keys_row.edit.textChanged.connect(self._safe(self._on_field_changed, "reserve_keys_changed"))

        self.test_result_received.connect(self._safe(self._process_test_result, "process_test_result"))
        self.test_result_failed.connect(self._safe(self._process_test_failed, "process_test_failed"))

    def _subscribe_bus(self) -> None:
        self.event_bus.subscribe(Events.ApiPresets.TEST_RESULT, self._on_test_result, weak=False)
        self.event_bus.subscribe(Events.ApiPresets.TEST_FAILED, self._on_test_failed, weak=False)

        self.event_bus.subscribe(Events.ApiPresets.PRESET_SAVED, lambda _e: self.reload_presets_async(), weak=False)
        self.event_bus.subscribe(Events.ApiPresets.PRESET_DELETED, lambda _e: self.reload_presets_async(), weak=False)