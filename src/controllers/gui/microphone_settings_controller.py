from __future__ import annotations

import re
from typing import Any

from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtGui import QFontMetrics

from core.events import Events, Event
from main_logger import logger
from utils import getTranslationVariant as _
from .base_controller import BaseController


class MicrophoneSettingsController(BaseController):
    def __init__(self, main_controller, view):
        self._bound_sig: tuple[int, int, int, int, int, int] | None = None
        super().__init__(main_controller, view)

    def subscribe_to_events(self):
        eb = self.event_bus
        eb.subscribe(Events.Install.TASK_FINISHED, self._on_install_finished, weak=False)
        eb.subscribe(Events.Install.TASK_FAILED, self._on_install_failed, weak=False)

        self._ui(self._bind_if_ready)

    def _widgets_signature(self) -> tuple[int, int, int, int, int, int] | None:
        v = self.view
        if not v:
            return None
        need = (
            "mic_combobox",
            "mic_refresh_button",
            "recognizer_combobox",
            "asr_refresh_button",
            "mic_active_checkbox",
            "mic_instant_checkbox",
        )
        for n in need:
            if not hasattr(v, n):
                return None
        return (
            id(getattr(v, "mic_combobox")),
            id(getattr(v, "mic_refresh_button")),
            id(getattr(v, "recognizer_combobox")),
            id(getattr(v, "asr_refresh_button")),
            id(getattr(v, "mic_active_checkbox")),
            id(getattr(v, "mic_instant_checkbox")),
        )

    def _bind_if_ready(self):
        sig = self._widgets_signature()
        if sig is None:
            QTimer.singleShot(350, lambda: self._ui(self._bind_if_ready))
            return

        if self._bound_sig == sig:
            QTimer.singleShot(1200, lambda: self._ui(self._bind_if_ready))
            return

        self._bound_sig = sig
        v = self.view

        def safe_disconnect(qt_signal, slot):
            try:
                qt_signal.disconnect(slot)
            except Exception:
                pass

        safe_disconnect(v.mic_refresh_button.clicked, self.refresh_microphones)
        v.mic_refresh_button.clicked.connect(self.refresh_microphones)

        safe_disconnect(v.asr_refresh_button.clicked, self.refresh_engines)
        v.asr_refresh_button.clicked.connect(self.refresh_engines)

        safe_disconnect(v.mic_combobox.currentIndexChanged, self._on_mic_changed)
        v.mic_combobox.currentIndexChanged.connect(self._on_mic_changed)

        safe_disconnect(v.recognizer_combobox.currentTextChanged, self._on_engine_changed)
        v.recognizer_combobox.currentTextChanged.connect(self._on_engine_changed)

        safe_disconnect(v.mic_active_checkbox.stateChanged, self._on_active_toggled)
        v.mic_active_checkbox.stateChanged.connect(self._on_active_toggled)

        safe_disconnect(v.mic_instant_checkbox.stateChanged, self._on_instant_toggled)
        v.mic_instant_checkbox.stateChanged.connect(self._on_instant_toggled)

        if hasattr(v, "asr_manage_button") and v.asr_manage_button:
            safe_disconnect(v.asr_manage_button.clicked, self._open_asr_glossary)
            v.asr_manage_button.clicked.connect(self._open_asr_glossary)

        self.refresh_microphones()
        self.refresh_engines()
        QTimer.singleShot(400, lambda: self._ui(self.refresh_engines))

        QTimer.singleShot(1200, lambda: self._ui(self._bind_if_ready))

    def _open_asr_glossary(self):
        try:
            self.event_bus.emit(Events.GUI.SHOW_WINDOW, {"window_id": "asr_glossary"})
        except Exception:
            pass

    def _save_setting(self, key: str, value: Any):
        v = self.view
        if v and hasattr(v, "_save_setting"):
            try:
                v._save_setting(key, value)
                return
            except Exception:
                pass

        try:
            self.event_bus.emit(Events.Core.SETTING_CHANGED, {"key": key, "value": value})
        except Exception:
            pass
        try:
            self.event_bus.emit("setting_changed", {"key": key, "value": value})
        except Exception:
            pass

    def _reset_init_status(self):
        v = self.view
        if not v:
            return
        if hasattr(v, "asr_set_pill") and hasattr(v, "asr_init_status") and v.asr_init_status is not None:
            try:
                v.asr_set_pill.emit({"label": v.asr_init_status, "text": "—", "kind": "info"})
            except Exception:
                pass

    def _truncate_text_for_width(self, text: str, widget, max_width: int) -> str:
        metrics = QFontMetrics(widget.font())
        ellipsis = "..."
        ellipsis_width = metrics.horizontalAdvance(ellipsis)
        available = max(int(max_width) - int(ellipsis_width) - 20, 20)

        if metrics.horizontalAdvance(text) <= available:
            return text

        left, right = 0, len(text)
        result = ""
        while left <= right:
            mid = (left + right) // 2
            s = text[:mid]
            if metrics.horizontalAdvance(s) <= available:
                result = s
                left = mid + 1
            else:
                right = mid - 1

        return (result + ellipsis) if result else ellipsis

    def refresh_microphones(self):
        v = self.view
        if not v or not hasattr(v, "mic_combobox"):
            return

        req_id = int(getattr(v, "_mic_list_req_id", 0)) + 1
        v._mic_list_req_id = req_id

        def show_loading():
            v.mic_combobox.blockSignals(True)
            try:
                v.mic_combobox.clear()
                v.mic_combobox.addItem(_("Загрузка...", "Loading..."))
                v.mic_combobox.setEnabled(False)
            finally:
                v.mic_combobox.blockSignals(False)

        self._ui(show_loading)

        def cb(result, error=None):
            def apply():
                if int(getattr(v, "_mic_list_req_id", 0)) != req_id:
                    return

                mic_list = result if isinstance(result, list) and result else [_("Микрофоны не найдены", "No microphones found")]

                v.mic_combobox.blockSignals(True)
                try:
                    v.mic_combobox.clear()

                    max_text_width = v.mic_combobox.maximumWidth()
                    if not max_text_width or max_text_width > 10000:
                        max_text_width = 200

                    for mic_name in mic_list:
                        full = str(mic_name)
                        display = self._truncate_text_for_width(full, v.mic_combobox, int(max_text_width))
                        if len(display) > 30:
                            display = full[:27] + "..."
                        v.mic_combobox.addItem(display)
                        idx = v.mic_combobox.count() - 1
                        v.mic_combobox.setItemData(idx, full, Qt.ItemDataRole.UserRole)
                        v.mic_combobox.setItemData(idx, full, Qt.ItemDataRole.ToolTipRole)

                    current_full = ""
                    try:
                        current_full = v.settings.get("MIC_DEVICE", mic_list[0] if mic_list else "")
                    except Exception:
                        current_full = mic_list[0] if mic_list else ""

                    for i in range(v.mic_combobox.count()):
                        if v.mic_combobox.itemData(i, Qt.ItemDataRole.UserRole) == current_full:
                            v.mic_combobox.setCurrentIndex(i)
                            break

                    v.mic_combobox.setToolTip(str(current_full or ""))
                    v.mic_combobox.setEnabled(True)
                finally:
                    v.mic_combobox.blockSignals(False)

            self._ui(apply)

        try:
            self.event_bus.emit(Events.Speech.GET_MICROPHONE_LIST, {"callback": cb})
        except Exception as e:
            logger.error(f"GET_MICROPHONE_LIST emit error: {e}")

    def refresh_engines(self, select_engine: str | None = None):
        v = self.view
        if not v or not hasattr(v, "recognizer_combobox"):
            return

        req_id = int(getattr(v, "_asr_glossary_req_id", 0)) + 1
        v._asr_glossary_req_id = req_id

        try:
            prev_engine = v.recognizer_combobox.currentText() if v.recognizer_combobox.isEnabled() else ""
        except Exception:
            prev_engine = ""

        def show_loading():
            v.recognizer_combobox.blockSignals(True)
            try:
                v.recognizer_combobox.clear()
                v.recognizer_combobox.setEnabled(False)
                v.recognizer_combobox.addItem(_("Загрузка...", "Loading..."))
            finally:
                v.recognizer_combobox.blockSignals(False)

        self._ui(show_loading)

        desired = ""
        try:
            desired = (select_engine or v.settings.get("RECOGNIZER_TYPE") or "").strip()
        except Exception:
            desired = (select_engine or "").strip()

        def cb(result, error=None):
            def apply():
                if int(getattr(v, "_asr_glossary_req_id", 0)) != req_id:
                    return

                glossary = result if isinstance(result, list) else []
                engines: list[str] = []
                for item in glossary:
                    try:
                        if item.get("installed", False) and item.get("id"):
                            engines.append(str(item["id"]))
                    except Exception:
                        pass

                v.recognizer_combobox.blockSignals(True)
                try:
                    v.recognizer_combobox.clear()
                    if engines:
                        v.recognizer_combobox.setEnabled(True)
                        v.recognizer_combobox.addItems(engines)

                        idx = v.recognizer_combobox.findText(desired)
                        if idx >= 0:
                            v.recognizer_combobox.setCurrentIndex(idx)
                        else:
                            v.recognizer_combobox.setCurrentIndex(0)
                            self._save_setting("RECOGNIZER_TYPE", v.recognizer_combobox.currentText())
                    else:
                        v.recognizer_combobox.setEnabled(False)
                        v.recognizer_combobox.addItem(_("Нет установленных моделей", "No installed models"))
                finally:
                    v.recognizer_combobox.blockSignals(False)

                try:
                    new_engine = v.recognizer_combobox.currentText() if v.recognizer_combobox.isEnabled() else ""
                except Exception:
                    new_engine = ""

                if new_engine != prev_engine:
                    self._reset_init_status()

                self._apply_asr_install_status(new_engine if engines else "")

            self._ui(apply)

        try:
            self.event_bus.emit(Events.Speech.GET_ASR_MODELS_GLOSSARY, {"callback": cb})
        except Exception as e:
            logger.error(f"GET_ASR_MODELS_GLOSSARY emit error: {e}")

    def _apply_asr_install_status(self, engine: str):
        v = self.view
        if not v or not hasattr(v, "mic_active_checkbox"):
            return

        if not engine or not getattr(v, "recognizer_combobox", None) or not v.recognizer_combobox.isEnabled():
            def off():
                try:
                    v.mic_active_checkbox.setChecked(False)
                    v.mic_active_checkbox.setEnabled(False)
                except Exception:
                    pass

            self._ui(off)
            return

        req_id = int(getattr(v, "_asr_installed_req_id", 0)) + 1
        v._asr_installed_req_id = req_id

        def lock():
            try:
                v.mic_active_checkbox.setEnabled(False)
            except Exception:
                pass

        self._ui(lock)

        def cb(result, error=None):
            def apply():
                if int(getattr(v, "_asr_installed_req_id", 0)) != req_id:
                    return

                installed = bool(result) if error is None else False
                try:
                    v.mic_active_checkbox.setEnabled(bool(installed))
                    if not installed:
                        v.mic_active_checkbox.setChecked(False)
                except Exception:
                    pass

            self._ui(apply)

        try:
            self.event_bus.emit(Events.Speech.CHECK_ASR_MODEL_INSTALLED, {"model": engine, "callback": cb})
        except Exception:
            self._ui(lambda: v.mic_active_checkbox.setEnabled(False))

    def _on_mic_changed(self, index: int):
        v = self.view
        if not v or not hasattr(v, "mic_combobox") or index < 0:
            return

        try:
            full = v.mic_combobox.itemData(index, Qt.ItemDataRole.UserRole) or ""
        except Exception:
            full = ""

        try:
            v.mic_combobox.setToolTip(str(full))
        except Exception:
            pass

        self._save_setting("MIC_DEVICE", str(full))

        selection = str(full or "")
        if not selection or "(" not in selection:
            return

        try:
            microphone_name = selection.rsplit(" (", 1)[0]
            m = re.search(r"\((\d+)\)\s*$", selection)
            if not m:
                return
            device_id = int(m.group(1))

            self.event_bus.emit(Events.Speech.SET_MICROPHONE, {"name": microphone_name, "device_id": device_id})

            active = False
            try:
                active = bool(v.settings.get("MIC_ACTIVE", False))
            except Exception:
                active = False

            if active:
                self.event_bus.emit(Events.Speech.RESTART_SPEECH_RECOGNITION, {"device_id": device_id})
        except Exception as e:
            logger.error(f"Mic change error: {e}")

    def _on_engine_changed(self, engine: str):
        v = self.view
        if not v or not getattr(v, "recognizer_combobox", None) or not v.recognizer_combobox.isEnabled():
            return
        eng = str(engine or "").strip()
        if not eng:
            return
        self._reset_init_status()
        self._save_setting("RECOGNIZER_TYPE", eng)
        self._apply_asr_install_status(eng)

    def _on_active_toggled(self, state: int):
        self._save_setting("MIC_ACTIVE", bool(state))

    def _on_instant_toggled(self, state: int):
        self._save_setting("MIC_INSTANT_SENT", bool(state))

    def _is_asr_task(self, data: dict) -> bool:
        if not isinstance(data, dict):
            return False
        if data.get("kind") == "asr":
            return True
        meta = data.get("meta") if isinstance(data.get("meta"), dict) else {}
        return meta.get("kind") == "asr"

    def _on_install_finished(self, event: Event):
        data = event.data or {}
        if not self._is_asr_task(data):
            return
        self._ui(self.refresh_engines)

    def _on_install_failed(self, event: Event):
        data = event.data or {}
        if not self._is_asr_task(data):
            return
        self._ui(self.refresh_engines)