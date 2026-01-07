import os
import time
import threading
from typing import Any

from PyQt6.QtWidgets import QMessageBox

from main_logger import logger
from core.events import Events, Event
from .base_controller import BaseController

from ui.dialogs.model_loading_dialog import create_model_loading_dialog
from utils import getTranslationVariant as _


class VoiceoverGuiController(BaseController):
    def __init__(self, main_controller, view):
        self._loading_dialog = None
        self._loading_status_label = None
        self._loading_model_id: str | None = None

        self._last_selected_model_id: str | None = None
        self._model_id_to_name: dict[str, str] = {}

        self._autoload_done = False

        self._tg_connected: bool | None = None
        self._tg_connecting: bool = False
        self._tg_last_attempt_ts: float = 0.0
        self._tg_attempt_cooldown_sec: float = 20.0

        self._tg_poll_stop = threading.Event()
        self._tg_poll_thread: threading.Thread | None = None
        self._tg_poll_active: bool = False

        super().__init__(main_controller, view)

    def subscribe_to_events(self):
        eb = self.event_bus

        eb.subscribe(Events.GUI.VOICEOVER_REFRESH, self._on_refresh, weak=False)
        eb.subscribe(Events.GUI.VOICEOVER_MODEL_SELECTED, self._on_model_selected, weak=False)

        eb.subscribe(Events.Core.SETTING_CHANGED, self._on_setting_changed, weak=False)

        eb.subscribe(Events.Audio.UPDATE_MODEL_LOADING_STATUS, self._on_loading_status, weak=False)
        eb.subscribe(Events.Audio.FINISH_MODEL_LOADING, self._on_finish_loading, weak=False)
        eb.subscribe(Events.Audio.CANCEL_MODEL_LOADING, self._on_cancel_loading, weak=False)

        eb.subscribe(Events.VoiceModel.MODEL_INSTALL_FINISHED, self._on_models_changed, weak=False)
        eb.subscribe(Events.VoiceModel.MODEL_UNINSTALL_FINISHED, self._on_models_changed, weak=False)
        eb.subscribe(Events.VoiceModel.REFRESH_MODEL_PANELS, self._on_models_changed, weak=False)

        eb.subscribe(Events.Telegram.SET_SILERO_CONNECTED, self._on_tg_connected_event, weak=False)
        eb.subscribe(Events.Telegram.START_SILERO, self._on_tg_start_requested, weak=False)
        eb.subscribe(Events.Telegram.STOP_SILERO, self._on_tg_stop_requested, weak=False)

    def autoload_last_model_on_startup(self):
        if self._autoload_done:
            return
        self._autoload_done = True
        self._ui(lambda: self._sync_everything(allow_autoload=True))

    def _on_refresh(self, _event: Event):
        self._ui(lambda: self._sync_everything(allow_autoload=False))

    def _on_models_changed(self, _event: Event):
        self._ui(lambda: self._sync_everything(allow_autoload=False))

    def _on_setting_changed(self, event: Event):
        data = event.data or {}
        key = str(data.get("key") or "").strip()
        value = data.get("value", None)

        relevant = {
            "USE_VOICEOVER",
            "VOICEOVER_METHOD",
            "NM_CURRENT_VOICEOVER",
            "LOCAL_VOICE_LOAD_LAST",
            "VOICE_LANGUAGE",
            "TG_AUTOCONNECT",
        }
        if key not in relevant:
            return

        def apply():
            if key == "VOICE_LANGUAGE":
                lang = str(value or self._get_setting("VOICE_LANGUAGE", "ru") or "ru")
                self.event_bus.emit_and_wait(Events.Audio.CHANGE_VOICE_LANGUAGE, {"language": lang}, timeout=1.0)
            self._sync_everything(allow_autoload=False)

        self._ui(apply)

    # ---------- Telegram ----------
    def _on_tg_connected_event(self, event: Event):
        data = event.data or {}
        val = data.get("connected", None)
        if isinstance(val, bool):
            self._tg_connected = val
            if val:
                self._tg_connecting = False
        self._ui(lambda: self._sync_everything(allow_autoload=False))

    def _on_tg_start_requested(self, _event: Event):
        self._tg_connecting = True
        self._tg_last_attempt_ts = time.time()
        self._ui(lambda: self._sync_everything(allow_autoload=False))

    def _on_tg_stop_requested(self, _event: Event):
        self._tg_connecting = False
        self._tg_connected = False
        self._ui(lambda: self._sync_everything(allow_autoload=False))

    def _ensure_tg_polling(self, active: bool):
        self._tg_poll_active = bool(active)

        if not self._tg_poll_active:
            self._tg_poll_stop.set()
            self._tg_poll_thread = None
            return

        if self._tg_poll_thread is not None and self._tg_poll_thread.is_alive():
            return

        self._tg_poll_stop.clear()

        def worker():
            while not self._tg_poll_stop.is_set():
                if not self._tg_poll_active:
                    break

                connected = None
                try:
                    res = self.event_bus.emit_and_wait(Events.Telegram.GET_SILERO_STATUS, timeout=0.7)
                    connected = bool(res and res[0])
                except Exception:
                    connected = None

                if connected is not None:
                    self._tg_connected = connected
                    if connected:
                        self._tg_connecting = False

                    self._ui(lambda: self._sync_tg_button_and_icon_only())

                interval = 1.0 if self._tg_connecting else 5.0
                time.sleep(interval)

        self._tg_poll_thread = threading.Thread(target=worker, daemon=True)
        self._tg_poll_thread.start()

    def _sync_tg_button_and_icon_only(self):
        self._update_tg_connect_button()
        self._emit_voice_icon_state()

    def _update_tg_connect_button(self):
        btn = getattr(self.view, "tg_connect_button", None)
        if btn is None:
            return

        use_voice = self._effective_use_voice()
        method = self._effective_method()

        active = bool(use_voice and method == "TG")

        if not active:
            btn.setEnabled(False)
            btn.setText(_("Подключиться к Telegram", "Connect Telegram"))
            return

        if self._tg_connecting:
            btn.setEnabled(False)
            btn.setText(_("Подключение...", "Connecting..."))
            return

        if self._tg_connected is True:
            btn.setEnabled(False)
            btn.setText(_("Подключено", "Connected"))
            return

        btn.setEnabled(True)
        btn.setText(_("Подключиться к Telegram", "Connect Telegram"))

    def _maybe_autoconnect_tg(self):
        use_voice = self._effective_use_voice()
        method = self._effective_method()
        if not use_voice or method != "TG":
            return

        autoconnect = bool(self._get_setting("TG_AUTOCONNECT", True))
        if not autoconnect:
            return

        if self._tg_connected is True or self._tg_connecting:
            return

        now = time.time()
        if (now - float(self._tg_last_attempt_ts or 0.0)) < float(self._tg_attempt_cooldown_sec or 20.0):
            return

        self._tg_connecting = True
        self._tg_last_attempt_ts = now

        self.event_bus.emit(Events.Telegram.START_SILERO, {"source": "autoconnect", "force": False})

    # ---------- Local models ----------
    def _on_model_selected(self, event: Event):
        model_id = str((event.data or {}).get("model_id") or "").strip()
        if not model_id:
            self._ui(lambda: self._sync_everything(allow_autoload=False))
            return

        def apply():
            self._ensure_voice_model_name_map()

            cur = self._current_model_id_from_settings()
            if cur:
                self._last_selected_model_id = cur

            self._save_setting("NM_CURRENT_VOICEOVER", model_id)

            if not self._check_installed(model_id):
                self._sync_local_warning_icon()
                self._emit_voice_icon_state()
                QMessageBox.information(self.view, _("Информация", "Info"), _("Модель не установлена.", "Model is not installed."))
                return

            if self._check_initialized(model_id):
                if not self._select_model(model_id):
                    QMessageBox.critical(self.view, _("Ошибка", "Error"), _("Не удалось активировать модель", "Failed to activate model"))
                self._set_combobox_by_model_id(model_id)
                self._sync_local_warning_icon()
                self._emit_voice_icon_state()
                return

            self._show_loading_dialog(model_id)
            self._emit_voice_icon_state()

            def progress_callback(status_type: str, message: str):
                if status_type == "status":
                    self._ui(lambda: self._set_loading_status(message))

            self.event_bus.emit(Events.Audio.INIT_VOICE_MODEL, {
                "model_id": model_id,
                "progress_callback": progress_callback,
            })

        self._ui(apply)

    def _on_loading_status(self, event: Event):
        status = str((event.data or {}).get("status", "") or "")
        self._ui(lambda: self._set_loading_status(status))

    def _on_finish_loading(self, event: Event):
        model_id = str((event.data or {}).get("model_id", "") or "").strip()

        def apply():
            had_dialog = (self._loading_dialog is not None)

            self._close_loading_dialog()
            self._loading_model_id = None

            ok = True
            if model_id:
                self._save_setting("NM_CURRENT_VOICEOVER", model_id)
                ok = bool(self._select_model(model_id))

            self._sync_everything(allow_autoload=False)

            if had_dialog and model_id:
                if ok:
                    self.event_bus.emit(Events.GUI.SHOW_INFO_MESSAGE, {
                        "title": _("Успешно", "Success"),
                        "message": _("Модель {} успешно инициализирована!", "Model {} initialized successfully!").format(model_id)
                    })
                else:
                    self.event_bus.emit(Events.GUI.SHOW_ERROR_MESSAGE, {
                        "title": _("Ошибка", "Error"),
                        "message": _("Модель инициализировалась, но не удалось активировать её.", "Model initialized, but failed to activate it.")
                    })

        self._ui(apply)

    def _on_cancel_loading(self, _event: Event):
        def apply():
            self._close_loading_dialog()
            self._loading_model_id = None
            self._restore_last_model_after_cancel()
            self._sync_everything(allow_autoload=False)

        self._ui(apply)

    # ---------- sync ----------
    def _sync_everything(self, *, allow_autoload: bool):
        if not self.view:
            return

        self._ensure_voice_model_name_map()

        self._apply_voiceover_visibility_from_widgets()
        self._update_local_models_combobox()

        if allow_autoload:
            self._maybe_autoload_local_model()

        self._sync_local_warning_icon()

        self._update_tg_connect_button()
        self._maybe_autoconnect_tg()

        tg_active = bool(self._effective_use_voice() and self._effective_method() == "TG")
        self._ensure_tg_polling(tg_active)

        self._emit_voice_icon_state()

    def _effective_use_voice(self) -> bool:
        w = getattr(self.view, "use_voice_checkbox", None)
        if w is not None and hasattr(w, "isChecked"):
            return bool(w.isChecked())
        return bool(self._get_setting("USE_VOICEOVER", False))

    def _effective_method(self) -> str:
        w = getattr(self.view, "method_combobox", None)
        if w is not None and hasattr(w, "currentText"):
            t = str(w.currentText() or "").strip()
            return t or "TG"
        return str(self._get_setting("VOICEOVER_METHOD", "TG") or "TG")

    def _apply_voiceover_visibility_from_widgets(self):
        use_voice = self._effective_use_voice()
        method = self._effective_method()

        method_cb = getattr(self.view, "method_combobox", None)
        tg_frame = getattr(self.view, "tg_settings_frame", None)
        local_frame = getattr(self.view, "local_settings_frame", None)

        if method_cb is not None:
            method_cb.setEnabled(use_voice)

        if tg_frame is not None:
            tg_frame.setVisible(method == "TG")
        if local_frame is not None:
            local_frame.setVisible(method == "Local")

    # ---------- sidebar indicator ----------
    def _emit_voice_icon_state(self):
        use_voice = self._effective_use_voice()
        method = self._effective_method()

        if not use_voice:
            self.event_bus.emit(Events.GUI.SET_SETTINGS_ICON_INDICATOR, {"category": "voice", "state": None, "tooltip": None})
            return

        if method == "TG":
            if self._tg_connecting:
                self.event_bus.emit(Events.GUI.SET_SETTINGS_ICON_INDICATOR, {
                    "category": "voice",
                    "state": "loading",
                    "tooltip": _("Подключение к Telegram...", "Connecting to Telegram..."),
                })
                return

            if self._tg_connected is True:
                self.event_bus.emit(Events.GUI.SET_SETTINGS_ICON_INDICATOR, {
                    "category": "voice",
                    "state": "green",
                    "tooltip": _("Telegram подключен", "Telegram connected"),
                })
                return

            self.event_bus.emit(Events.GUI.SET_SETTINGS_ICON_INDICATOR, {
                "category": "voice",
                "state": "red",
                "tooltip": _("Telegram не подключен", "Telegram not connected"),
            })
            return

        if method != "Local":
            self.event_bus.emit(Events.GUI.SET_SETTINGS_ICON_INDICATOR, {"category": "voice", "state": None, "tooltip": None})
            return

        model_id = self._current_model_id_from_settings()
        if not model_id:
            self.event_bus.emit(Events.GUI.SET_SETTINGS_ICON_INDICATOR, {
                "category": "voice",
                "state": "red",
                "tooltip": _("Локальная озвучка: модель не выбрана", "Local voiceover: model not selected"),
            })
            return

        if self._loading_model_id == model_id:
            self.event_bus.emit(Events.GUI.SET_SETTINGS_ICON_INDICATOR, {
                "category": "voice",
                "state": "loading",
                "tooltip": _("Инициализация модели...", "Initializing model..."),
            })
            return

        if not self._check_installed(model_id):
            self.event_bus.emit(Events.GUI.SET_SETTINGS_ICON_INDICATOR, {
                "category": "voice",
                "state": "red",
                "tooltip": _("Модель не установлена", "Model not installed"),
            })
            return

        initialized = self._check_initialized(model_id)
        self.event_bus.emit(Events.GUI.SET_SETTINGS_ICON_INDICATOR, {
            "category": "voice",
            "state": "green" if initialized else "red",
            "tooltip": _("Модель готова", "Model ready") if initialized else _("Требуется инициализация", "Initialization required"),
        })

    # ---------- local warning icon ----------
    def _sync_local_warning_icon(self):
        lbl = getattr(self.view, "local_model_status_label", None)
        if lbl is None:
            return

        use_voice = self._effective_use_voice()
        method = self._effective_method()

        if not use_voice or method != "Local":
            lbl.setVisible(False)
            return

        model_id = self._current_model_id_from_settings()
        if not model_id:
            lbl.setVisible(True)
            return

        installed = self._check_installed(model_id)
        initialized = self._check_initialized(model_id) if installed else False
        lbl.setVisible(not (installed and initialized))

    # ---------- local combobox ----------
    def _ensure_voice_model_name_map(self):
        now = time.time()
        ts = float(getattr(self, "_model_id_to_name_ts", 0.0) or 0.0)

        if self._model_id_to_name and (now - ts) < 30.0:
            return

        try:
            res = self.event_bus.emit_and_wait(Events.Audio.GET_ALL_LOCAL_MODEL_CONFIGS, timeout=1.5)
            cfgs = res[0] if res and isinstance(res[0], list) else []
        except Exception:
            cfgs = []

        mp: dict[str, str] = {}
        for c in cfgs or []:
            if not isinstance(c, dict):
                continue
            mid = str(c.get("id") or "").strip()
            name = str(c.get("name") or mid).strip()
            if mid:
                mp[mid] = name

        if not mp:
            try:
                from ui.settings.voiceover_settings import LOCAL_VOICE_MODELS
                for m in LOCAL_VOICE_MODELS:
                    mid = str(m.get("id") or "").strip()
                    name = str(m.get("name") or mid).strip()
                    if mid:
                        mp[mid] = name
            except Exception:
                pass

        self._model_id_to_name = mp
        self._model_id_to_name_ts = now

    def _update_local_models_combobox(self):
        cb = getattr(self.view, "local_voice_combobox", None)
        if cb is None:
            return

        installed_ids = set()
        try:
            res = self.event_bus.emit_and_wait(Events.VoiceModel.GET_INSTALLED_MODELS, timeout=0.7)
            got = res[0] if res else None
            if isinstance(got, (set, list, tuple)):
                installed_ids = set(str(x) for x in got)
        except Exception:
            installed_ids = set()

        ordered_ids = list(self._model_id_to_name.keys())
        ids = [mid for mid in ordered_ids if mid in installed_ids]
        items = [(self._model_id_to_name.get(mid, mid), mid) for mid in ids]

        cb.blockSignals(True)
        try:
            cb.clear()
            for name, mid in items:
                cb.addItem(name, mid)
        finally:
            cb.blockSignals(False)

        current = self._current_model_id_from_settings()

        if current and current in installed_ids:
            self._set_combobox_by_model_id(current)
            return

        if items:
            first_id = items[0][1]
            self._save_setting("NM_CURRENT_VOICEOVER", first_id)
            self._set_combobox_by_model_id(first_id)
            return

        self._save_setting("NM_CURRENT_VOICEOVER", None)

    def _set_combobox_by_model_id(self, model_id: str):
        cb = getattr(self.view, "local_voice_combobox", None)
        if cb is None:
            return
        for i in range(cb.count()):
            if str(cb.itemData(i) or "") == model_id:
                if cb.currentIndex() != i:
                    cb.setCurrentIndex(i)
                return

    # ---------- local autoload ----------
    def _maybe_autoload_local_model(self):
        if not bool(self._get_setting("LOCAL_VOICE_LOAD_LAST", False)):
            return

        model_id = self._current_model_id_from_settings()
        if not model_id:
            return

        if not self._check_installed(model_id):
            return

        if self._check_initialized(model_id):
            self._select_model(model_id)
            return

        self._show_loading_dialog(model_id)
        self._emit_voice_icon_state()

        def progress_callback(status_type: str, message: str):
            if status_type == "status":
                self._ui(lambda: self._set_loading_status(message))

        self.event_bus.emit(Events.Audio.INIT_VOICE_MODEL, {
            "model_id": model_id,
            "progress_callback": progress_callback,
        })

    # ---------- local loading dialog ----------
    def _show_loading_dialog(self, model_id: str):
        if not self.view:
            return

        if not os.path.exists("models"):
            QMessageBox.critical(self.view, _("Ошибка", "Error"),
                                 _("Не найдена папка models. Инициализация отменена.",
                                   "Failed to find models folder. Initialization cancelled."))
            return

        self._loading_model_id = model_id
        model_name = self._model_id_to_name.get(model_id, model_id)

        self._loading_dialog, _progress, self._loading_status_label = create_model_loading_dialog(
            self.view,
            model_name,
            lambda: self._user_cancel_loading()
        )
        self._loading_dialog.show()
        self._set_loading_status(_("Инициализация модели...", "Initializing model..."))

    def _user_cancel_loading(self):
        self._close_loading_dialog()
        self._loading_model_id = None
        self._restore_last_model_after_cancel()
        self._sync_everything(allow_autoload=False)

    def _restore_last_model_after_cancel(self):
        if not self._last_selected_model_id:
            return
        self._save_setting("NM_CURRENT_VOICEOVER", self._last_selected_model_id)
        self._set_combobox_by_model_id(self._last_selected_model_id)

    def _set_loading_status(self, text: str):
        if self._loading_status_label is not None:
            self._loading_status_label.setText(str(text or ""))

    def _close_loading_dialog(self):
        if self._loading_dialog is not None:
            try:
                self._loading_dialog.close()
            except Exception:
                pass
        self._loading_dialog = None
        self._loading_status_label = None

    # ---------- backend checks ----------
    def _check_installed(self, model_id: str) -> bool:
        try:
            res = self.event_bus.emit_and_wait(Events.Audio.CHECK_MODEL_INSTALLED, {"model_id": model_id}, timeout=0.7)
            return bool(res and res[0])
        except Exception:
            return False

    def _check_initialized(self, model_id: str) -> bool:
        try:
            res = self.event_bus.emit_and_wait(Events.Audio.CHECK_MODEL_INITIALIZED, {"model_id": model_id}, timeout=0.7)
            return bool(res and res[0])
        except Exception:
            return False

    def _select_model(self, model_id: str) -> bool:
        try:
            res = self.event_bus.emit_and_wait(Events.Audio.SELECT_VOICE_MODEL, {"model_id": model_id}, timeout=1.0)
            return bool(res and res[0])
        except Exception as e:
            logger.error(f"SELECT_VOICE_MODEL failed: {e}", exc_info=True)
            return False

    # ---------- settings ----------
    def _save_setting(self, key: str, value: Any):
        try:
            cur = self._get_setting(key, None)
            if cur is None and (value is None or value == ""):
                return
            if value is None and (cur is None or cur == ""):
                return
            if str(cur) == str(value):
                return
        except Exception:
            pass

        self.event_bus.emit(Events.Settings.SAVE_SETTING, {"key": key, "value": value})

    def _get_setting(self, key: str, default=None):
        try:
            return self.main_controller.settings.get(key, default)
        except Exception:
            return default

    def _current_model_id_from_settings(self) -> str:
        v = self._get_setting("NM_CURRENT_VOICEOVER", None)
        return str(v or "").strip() if v else ""