import os
import time
import threading
from typing import Any

from PyQt6.QtWidgets import QMessageBox

from main_logger import logger
from core.events import Events, Event
from core.services import services
from core.task_supervisor import task_supervisor
from services.contracts import (
    InstallableCatalogService,
    LocalVoiceService,
    TelegramService,
    VoiceModelService,
)
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

        self._installed_models_cache: set[str] | None = None
        self._installed_models_cache_ts: float = 0.0
        # Модели, про которые точно известно, что они инициализированы (загружены
        # в память). Ведётся из snapshot-пути индикатора; старый путь его читает,
        # чтобы отдавать честный «green/warn» без блокирующего CHECK_MODEL_INITIALIZED.
        self._initialized_models_cache: set[str] = set()

        super().__init__(main_controller, view)

    def subscribe_to_events(self):
        eb = self.event_bus

        eb.subscribe(Events.GUI.VOICEOVER_REFRESH, self._on_refresh, weak=False)
        eb.subscribe(Events.GUI.VOICEOVER_MODEL_SELECTED, self._on_model_selected, weak=False)

        self._subscribe_settings(
            self._on_setting_changed,
            keys=(
                "USE_VOICEOVER", "VOICEOVER_METHOD", "NM_CURRENT_VOICEOVER",
                "LOCAL_VOICE_LOAD_LAST", "VOICE_LANGUAGE", "TG_AUTOCONNECT",
            ),
        )

        eb.subscribe(Events.Audio.UPDATE_MODEL_LOADING_STATUS, self._on_loading_status, weak=False)
        eb.subscribe(Events.Audio.FINISH_MODEL_LOADING, self._on_finish_loading, weak=False)
        eb.subscribe(Events.Audio.CANCEL_MODEL_LOADING, self._on_cancel_loading, weak=False)

        eb.subscribe(Events.VoiceModel.MODEL_INSTALL_FINISHED, self._on_models_changed, weak=False)
        eb.subscribe(Events.VoiceModel.MODEL_UNINSTALL_FINISHED, self._on_models_changed, weak=False)
        eb.subscribe(Events.VoiceModel.REFRESH_MODEL_PANELS, self._on_models_changed, weak=False)
        eb.subscribe(Events.Install.CATALOG_CHANGED, self._on_models_changed, weak=False)

        eb.subscribe(Events.Telegram.SET_SILERO_CONNECTED, self._on_tg_connected_event, weak=False)
        eb.subscribe(Events.Telegram.START_SILERO, self._on_tg_start_requested, weak=False)
        eb.subscribe(Events.Telegram.STOP_SILERO, self._on_tg_stop_requested, weak=False)
        eb.subscribe(Events.AI.SERVICE_RESTARTED, self._on_ai_service_restarted, weak=False)

    def _get_installed_models_set(self) -> set[str]:
        now = time.time()
        if self._installed_models_cache is not None and (now - self._installed_models_cache_ts) < 1.0:
            return set(self._installed_models_cache)

        installed = self._canonical_installed_model_ids()

        self._installed_models_cache = installed
        self._installed_models_cache_ts = now
        return set(installed)

    @staticmethod
    def _canonical_installed_model_ids() -> set[str]:
        catalog = services().get_optional(InstallableCatalogService)
        if catalog is None:
            return set()
        return set(catalog.ready_item_ids("tts"))

    def _initialize_local_model(self, model_id: str) -> None:
        local_voice = services().get_optional(LocalVoiceService)
        if local_voice is None:
            self.event_bus.emit(
                Events.GUI.SHOW_ERROR_MESSAGE,
                {
                    "title": _("Ошибка", "Error"),
                    "message": _(
                        "Сервис локальной озвучки недоступен.",
                        "Local voice service is unavailable.",
                    ),
                },
            )
            self.event_bus.emit(Events.Audio.CANCEL_MODEL_LOADING)
            return
        try:
            local_voice.initialize_model(model_id)
        except Exception as exc:
            logger.error(
                f"Failed to schedule local voice initialization for '{model_id}': {exc}",
                exc_info=True,
            )
            self.event_bus.emit(
                Events.GUI.SHOW_ERROR_MESSAGE,
                {"title": _("Ошибка", "Error"), "message": str(exc)},
            )
            self.event_bus.emit(Events.Audio.CANCEL_MODEL_LOADING)

    def autoload_last_model_on_startup(self):
        if self._autoload_done:
            return
        self._autoload_done = True
        self._ui(lambda: self._sync_everything(allow_autoload=True))

    def _on_refresh(self, _event: Event):
        self._ui(lambda: self._sync_everything(allow_autoload=False))

    def _on_models_changed(self, event: Event):
        payload = event.data if isinstance(event.data, dict) else {}
        if "success" in payload and not bool(payload.get("success")):
            return
        self._installed_models_cache = None
        self._installed_models_cache_ts = 0.0
        self._model_id_to_name_ts = 0.0
        self._ui(lambda: self._sync_everything(allow_autoload=False))

    def _on_setting_changed(self, change):
        key = str(change.key or "").strip()
        value = change.value

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
                self.event_bus.emit(Events.Audio.CHANGE_VOICE_LANGUAGE, {"language": lang})
            self._sync_everything(allow_autoload=False)
            self.event_bus.emit(Events.GUI.UPDATE_STATUS_COLORS)

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

    def _on_ai_service_restarted(self, event: Event):
        data = event.data if isinstance(event.data, dict) else {}
        service = str(data.get("service") or "").strip().lower()
        if service != "tts":
            return

        ok = bool(data.get("ok", False))
        err = str(data.get("error") or "").strip()

        def apply():
            self._sync_everything(allow_autoload=False)

            if ok:
                self.event_bus.emit(Events.GUI.SHOW_INFO_MESSAGE, {
                    "title": _("Готово", "Done"),
                    "message": _("Нейро-ядро озвучки перезапущено.", "Voice AI engine restarted."),
                })
            else:
                self.event_bus.emit(Events.GUI.SHOW_ERROR_MESSAGE, {
                    "title": _("Ошибка", "Error"),
                    "message": _("Не удалось перезапустить нейро-ядро озвучки.", "Failed to restart voice AI engine.")
                            + (f"\n\n{err}" if err else "")
                })

        self._ui(apply)

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

                telegram = services().get_optional(TelegramService)
                connected = telegram.is_silero_connected() if telegram is not None else None

                if connected is not None:
                    self._tg_connected = connected
                    if connected:
                        self._tg_connecting = False

                    self._ui(lambda: self._sync_tg_button_and_icon_only())

                interval = 1.0 if self._tg_connecting else 5.0
                if self._tg_poll_stop.wait(interval):
                    break

        self._tg_poll_thread = task_supervisor().start_thread(
            self,
            "telegram-status-poll",
            worker,
            replace=True,
        )

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
        if not self._backend_enabled():
            return

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
            if not self._backend_enabled():
                self._sync_everything(allow_autoload=False)
                self.event_bus.emit(Events.GUI.SHOW_INFO_MESSAGE, {
                    "title": _("GUI-only режим", "GUI-only mode"),
                    "message": _(
                        "Озвучка недоступна: backend-контроллеры не запущены.",
                        "Voiceover is unavailable because backend controllers are disabled.",
                    ),
                })
                return

            cur = self._current_model_id_from_settings()
            if cur:
                self._last_selected_model_id = cur

            self._save_setting("NM_CURRENT_VOICEOVER", model_id)
            self._set_combobox_by_model_id(model_id)
            self._select_or_init_model_async(model_id)
            return

            if not self._check_installed(model_id):
                self._sync_local_model_status()
                self._emit_voice_icon_state()
                QMessageBox.information(self.view, _("Информация", "Info"), _("Модель не установлена.", "Model is not installed."))
                return

            if self._check_initialized(model_id):
                if not self._select_model(model_id):
                    QMessageBox.critical(self.view, _("Ошибка", "Error"), _("Не удалось активировать модель", "Failed to activate model"))
                self._set_combobox_by_model_id(model_id)
                self._sync_local_model_status()
                self._emit_voice_icon_state()
                return

            if not self._show_loading_dialog(model_id):
                # Нет папки models и т.п. — инициализацию НЕ запускаем
                # (раньше эмитили INIT_VOICE_MODEL несмотря на ошибку).
                self._emit_voice_icon_state()
                return
            self._emit_voice_icon_state()

            self._initialize_local_model(model_id)

        self._ui(apply)

    def _select_or_init_model_async(self, model_id: str):
        if not model_id:
            return

        if not self._model_id_to_name:
            self._model_id_to_name = self._build_model_name_map([])

        ticket = int(getattr(self, "_model_selection_ticket", 0) or 0) + 1
        self._model_selection_ticket = ticket

        chip = getattr(self.view, "local_model_status_chip", None)
        btn = getattr(self.view, "local_model_action_btn", None)
        if chip is not None or btn is not None:
            self._apply_model_status(chip, btn, "loading", _("Checking...", "Checking..."), None, "")

        def worker():
            local_voice = services().get_optional(LocalVoiceService)
            installed_ids = self._canonical_installed_model_ids()

            installed = model_id in installed_ids
            initialized = bool(installed and local_voice and local_voice.check_initialized(model_id))
            selected = bool(local_voice.select_model(model_id)) if initialized and local_voice else None

            return {
                "model_id": model_id,
                "installed_ids": installed_ids,
                "installed": installed,
                "initialized": initialized,
                "selected": selected,
            }

        def apply(snapshot: dict):
            if ticket != int(getattr(self, "_model_selection_ticket", 0) or 0):
                return

            installed_ids = snapshot.get("installed_ids") or set()
            if not isinstance(installed_ids, set):
                installed_ids = {str(x) for x in installed_ids}
            self._installed_models_cache = set(installed_ids)
            self._installed_models_cache_ts = time.time()

            current_id = str(snapshot.get("model_id") or model_id)
            state = {
                "installed": bool(snapshot.get("installed")),
                "initialized": bool(snapshot.get("initialized")),
                "current_model_id": current_id,
            }

            if not state["installed"]:
                self._sync_local_model_status_from_snapshot(state)
                self._emit_voice_icon_state_from_snapshot(state)
                QMessageBox.information(self.view, _("Info", "Info"), _("Model is not installed.", "Model is not installed."))
                return

            if state["initialized"]:
                self._set_combobox_by_model_id(current_id)
                self._sync_local_model_status_from_snapshot(state)
                self._emit_voice_icon_state_from_snapshot(state)
                if snapshot.get("selected") is False:
                    QMessageBox.critical(self.view, _("Error", "Error"), _("Failed to activate model", "Failed to activate model"))
                return

            if not self._show_loading_dialog(current_id):
                self._sync_local_model_status_from_snapshot(state)
                self._emit_voice_icon_state_from_snapshot(state)
                return
            self._emit_voice_icon_state_from_snapshot(state)

            self._initialize_local_model(current_id)

        self._run_async(worker, apply, name=f"voiceover-select:{model_id}")

    def _on_loading_status(self, event: Event):
        status = str((event.data or {}).get("status", "") or "")
        self._ui(lambda: self._set_loading_status(status))

    def _on_finish_loading(self, event: Event):
        model_id = str((event.data or {}).get("model_id", "") or "").strip()

        def apply():
            had_dialog = (self._loading_dialog is not None)
            # #4: инициализацию могли отменить, пока движок догружал модель в
            # фоне. Если ждали НЕ этот model_id (после отмены _loading_model_id
            # обнуляется/восстанавливается) — не применяем результат: не делаем
            # его текущим и не показываем «успешно». Фоновая загрузка в движке
            # уже не остановить, но в приложении отмена реально срабатывает.
            was_awaited = bool(model_id) and (self._loading_model_id == model_id)

            self._close_loading_dialog()
            self._loading_model_id = None

            if not was_awaited:
                self._sync_everything(allow_autoload=False)
                return

            if model_id:
                self._save_setting("NM_CURRENT_VOICEOVER", model_id)

                def after_select(ok: bool):
                    self._sync_everything(allow_autoload=False)
                    if not had_dialog:
                        return
                    if ok:
                        self.event_bus.emit(Events.GUI.SHOW_INFO_MESSAGE, {
                            "title": _("Success", "Success"),
                            "message": _("Model {} initialized successfully!", "Model {} initialized successfully!").format(model_id),
                        })
                    else:
                        self.event_bus.emit(Events.GUI.SHOW_ERROR_MESSAGE, {
                            "title": _("Error", "Error"),
                            "message": _("Model initialized, but failed to activate it.", "Model initialized, but failed to activate it."),
                        })

                self._select_model_async(model_id, after_select, show_error=False)
                return

            ok = True

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

        self._apply_voiceover_visibility_from_widgets()
        self._set_local_voice_loading_placeholders()

        ticket = int(getattr(self, "_sync_ticket", 0) or 0) + 1
        self._sync_ticket = ticket

        def worker():
            cfgs = []
            installed_ids: set[str] = set()
            initialized = False
            current_model_id = self._current_model_id_from_settings()

            local_voice = services().get_optional(LocalVoiceService)
            voice_models = services().get_optional(VoiceModelService)
            cfgs = voice_models.model_catalog_snapshot() if voice_models is not None else []
            installed_ids = self._canonical_installed_model_ids()
            if current_model_id and local_voice is not None:
                initialized = bool(local_voice.check_initialized(current_model_id))

            return {
                "cfgs": cfgs,
                "installed_ids": installed_ids,
                "current_model_id": current_model_id,
                "initialized": initialized,
            }

        def apply(snapshot: dict):
            if ticket != int(getattr(self, "_sync_ticket", 0) or 0):
                return
            self._apply_voiceover_snapshot(snapshot, allow_autoload=allow_autoload)

        self._run_async(worker, apply, name="voiceover-sync")

    def _apply_voiceover_snapshot(self, snapshot: dict, *, allow_autoload: bool):
        cfgs = snapshot.get("cfgs") if isinstance(snapshot, dict) else []
        installed_ids = snapshot.get("installed_ids") if isinstance(snapshot, dict) else set()
        current_model_id = str((snapshot or {}).get("current_model_id") or "")
        initialized = bool((snapshot or {}).get("initialized"))

        if not isinstance(installed_ids, set):
            installed_ids = {str(x) for x in (installed_ids or [])}

        self._model_id_to_name = self._build_model_name_map(cfgs)
        self._model_id_to_name_ts = time.time()
        self._installed_models_cache = set(installed_ids)
        self._installed_models_cache_ts = time.time()

        self._apply_voiceover_visibility_from_widgets()
        current_model_id = self._update_local_models_combobox_from_snapshot(installed_ids, current_model_id)

        state = {
            "installed": bool(current_model_id and current_model_id in installed_ids),
            "initialized": initialized,
            "current_model_id": current_model_id,
        }

        if allow_autoload:
            self._maybe_autoload_local_model_from_snapshot(state)

        self._sync_local_model_status_from_snapshot(state)
        self._update_tg_connect_button()
        self._maybe_autoconnect_tg()

        tg_active = bool(self._effective_use_voice() and self._effective_method() == "TG")
        self._ensure_tg_polling(tg_active)
        self._emit_voice_icon_state_from_snapshot(state)

    def _build_model_name_map(self, cfgs) -> dict[str, str]:
        mp: dict[str, str] = {}
        for c in cfgs or []:
            if not isinstance(c, dict):
                continue
            mid = str(c.get("id") or "").strip()
            name = str(c.get("name") or mid).strip()
            if mid:
                mp[mid] = name

        if mp:
            return mp

        try:
            from presets.local_voice_models import LOCAL_VOICE_MODELS
            for m in LOCAL_VOICE_MODELS:
                mid = str(m.get("id") or "").strip()
                name = str(m.get("name") or mid).strip()
                if mid:
                    mp[mid] = name
        except Exception:
            pass
        return mp

    def _set_local_voice_loading_placeholders(self):
        cb = getattr(self.view, "local_voice_combobox", None)
        self._set_local_model_selector_state(has_models=False, loading=True)
        if cb is not None and cb.count() == 0:
            cb.blockSignals(True)
            try:
                cb.addItem(_("Загрузка...", "Loading..."), "")
            finally:
                cb.blockSignals(False)

        chip = getattr(self.view, "local_model_status_chip", None)
        btn = getattr(self.view, "local_model_action_btn", None)
        if chip is not None and btn is not None and not chip.isVisible():
            self._apply_model_status(chip, btn, "loading", _("Проверка...", "Checking..."), None, "")

    def _set_local_model_selector_state(self, *, has_models: bool, loading: bool = False) -> None:
        combo = getattr(self.view, "local_voice_combobox", None)
        empty = getattr(self.view, "local_voice_empty_status", None)
        settings_button = getattr(self.view, "local_model_settings_btn", None)
        if combo is not None:
            combo.setVisible(bool(has_models or loading))
            combo.setEnabled(bool(has_models))
        if empty is not None:
            empty.setVisible(bool(not has_models and not loading))
        if settings_button is not None:
            settings_button.setVisible(bool(has_models))

    def _update_local_models_combobox_from_snapshot(self, installed_ids: set[str], current_model_id: str) -> str:
        cb = getattr(self.view, "local_voice_combobox", None)
        if cb is None:
            return current_model_id

        ordered_ids = list(self._model_id_to_name.keys())
        ids = [mid for mid in ordered_ids if mid in installed_ids]
        items = [(self._model_id_to_name.get(mid, mid), mid) for mid in ids]
        self._set_local_model_selector_state(has_models=bool(items))

        cb.blockSignals(True)
        try:
            cb.clear()
            for name, mid in items:
                cb.addItem(name, mid)
        finally:
            cb.blockSignals(False)

        if current_model_id and current_model_id in installed_ids:
            self._set_combobox_by_model_id(current_model_id)
            return current_model_id

        if items:
            first_id = items[0][1]
            self._save_setting("NM_CURRENT_VOICEOVER", first_id)
            self._set_combobox_by_model_id(first_id)
            return first_id

        self._save_setting("NM_CURRENT_VOICEOVER", None)
        return ""

    def _maybe_autoload_local_model_from_snapshot(self, state: dict):
        if not self._backend_enabled():
            return
        if not bool(self._get_setting("LOCAL_VOICE_LOAD_LAST", False)):
            return

        model_id = str(state.get("current_model_id") or "")
        if not model_id or not bool(state.get("installed")):
            return

        if bool(state.get("initialized")):
            self._select_model_async(model_id, show_error=False)
            return

        if not self._show_loading_dialog(model_id):
            self._emit_voice_icon_state_from_snapshot(state)
            return

        self._emit_voice_icon_state_from_snapshot({**state, "current_model_id": model_id})

        self._initialize_local_model(model_id)

    def _sync_local_model_status_from_snapshot(self, state: dict):
        chip = getattr(self.view, "local_model_status_chip", None)
        btn = getattr(self.view, "local_model_action_btn", None)
        if chip is None and btn is None:
            return

        use_voice = self._effective_use_voice()
        method = self._effective_method()

        if not use_voice or method != "Local":
            if chip is not None:
                chip.setVisible(False)
            if btn is not None:
                btn.setVisible(False)
            return

        if chip is not None:
            chip.setVisible(True)

        model_id = str(state.get("current_model_id") or "")

        if model_id and self._loading_model_id == model_id:
            self._apply_model_status(chip, btn, "loading", _("Инициализация...", "Initializing..."), None, "")
            return

        if not model_id or not bool(state.get("installed")):
            self._apply_model_status(chip, btn, "red", _("Не установлена", "Not installed"), "install", _("Установить", "Install"))
            return

        if bool(state.get("initialized")):
            self._apply_model_status(chip, btn, "green", _("Готова", "Ready"), None, "")
            return

        self._apply_model_status(
            chip,
            btn,
            "orange",
            _("Требуется инициализация", "Initialization required"),
            "init",
            _("Инициализировать", "Initialize"),
        )

    def _emit_voice_icon_state_from_snapshot(self, state: dict):
        use_voice = self._effective_use_voice()
        method = self._effective_method()

        if not use_voice:
            self.event_bus.emit(Events.GUI.SET_SETTINGS_ICON_INDICATOR, {"category": "voice", "state": None, "tooltip": None})
            return

        if method == "TG":
            self._emit_voice_icon_state()
            return

        if method != "Local":
            self.event_bus.emit(Events.GUI.SET_SETTINGS_ICON_INDICATOR, {"category": "voice", "state": None, "tooltip": None})
            return

        model_id = str(state.get("current_model_id") or "")
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

        if not bool(state.get("installed")):
            self.event_bus.emit(Events.GUI.SET_SETTINGS_ICON_INDICATOR, {
                "category": "voice",
                "state": "red",
                "tooltip": _("Модель не установлена", "Model not installed"),
            })
            return

        initialized = bool(state.get("initialized"))
        # Единый источник правды об инициализации для старого пути индикатора.
        if initialized:
            self._initialized_models_cache.add(model_id)
        else:
            self._initialized_models_cache.discard(model_id)
        # Установлена, но не инициализирована — это НЕ «готово». Жёлтый "warn"
        # (настроено, но требует инициализации), а не зелёный, иначе индикатор
        # на вкладке противоречит плашке «Требуется инициализация» в теле страницы.
        self.event_bus.emit(Events.GUI.SET_SETTINGS_ICON_INDICATOR, {
            "category": "voice",
            "state": "green" if initialized else "warn",
            "tooltip": _("Модель готова", "Model ready") if initialized else _("Требуется инициализация", "Initialization required"),
        })

    def _select_model_async(self, model_id: str, on_done=None, *, show_error: bool = True):
        def worker():
            local_voice = services().get_optional(LocalVoiceService)
            return bool(local_voice and local_voice.select_model(model_id))

        def apply(ok: bool):
            if not ok and show_error:
                self.event_bus.emit(Events.GUI.SHOW_ERROR_MESSAGE, {
                    "title": _("Ошибка", "Error"),
                    "message": _("Не удалось активировать модель", "Failed to activate model"),
                })

            if callable(on_done):
                on_done(bool(ok))

        self._run_async(worker, apply, name="voiceover-select-model")

    def _sync_everything_sync_legacy(self, *, allow_autoload: bool):
        if not self.view:
            return

        self._ensure_voice_model_name_map()

        self._apply_voiceover_visibility_from_widgets()
        self._update_local_models_combobox()

        if allow_autoload:
            self._maybe_autoload_local_model()

        self._sync_local_model_status()

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
            return t or "Local"
        return str(self._get_setting("VOICEOVER_METHOD", "Local") or "Local")

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

        installed_ids = getattr(self, "_installed_models_cache", None)
        if installed_ids is None:
            self.event_bus.emit(Events.GUI.SET_SETTINGS_ICON_INDICATOR, {
                "category": "voice",
                "state": "loading",
                "tooltip": _("Checking model status...", "Checking model status..."),
            })
            return

        if model_id not in installed_ids:
            self.event_bus.emit(Events.GUI.SET_SETTINGS_ICON_INDICATOR, {
                "category": "voice",
                "state": "red",
                "tooltip": _("Model not installed", "Model not installed"),
            })
            return

        # Установлена, но не инициализирована — жёлтый "warn", а не зелёный.
        # Данные об инициализации берём из кэша, который ведёт snapshot-путь
        # (никаких блокирующих CHECK_MODEL_INITIALIZED в пути индикатора).
        initialized = model_id in getattr(self, "_initialized_models_cache", set())
        self.event_bus.emit(Events.GUI.SET_SETTINGS_ICON_INDICATOR, {
            "category": "voice",
            "state": "green" if initialized else "warn",
            "tooltip": _("Модель готова", "Model ready") if initialized else _("Требуется инициализация", "Initialization required"),
        })

    # ---------- local model status (chip + action button) ----------
    def _sync_local_model_status(self):
        chip = getattr(self.view, "local_model_status_chip", None)
        btn = getattr(self.view, "local_model_action_btn", None)
        if chip is None and btn is None:
            return

        use_voice = self._effective_use_voice()
        method = self._effective_method()

        # Локальная озвучка неактуальна — прячем и чип, и кнопку.
        if not use_voice or method != "Local":
            if chip is not None:
                chip.setVisible(False)
            if btn is not None:
                btn.setVisible(False)
            return

        if chip is not None:
            chip.setVisible(True)

        model_id = self._current_model_id_from_settings()

        # Идёт инициализация именно выбранной модели — прогресс виден в диалоге,
        # кнопку прячем, чтобы не давать повторно запускать загрузку.
        if model_id and self._loading_model_id == model_id:
            self._apply_model_status(chip, btn, "loading",
                                     _("Инициализация…", "Initializing…"), None, "")
            return

        # Модель не выбрана или не установлена — предлагаем установить (AI Hub).
        if not model_id or not self._check_installed(model_id):
            self._apply_model_status(chip, btn, "red",
                                     _("Не установлена", "Not installed"),
                                     "install", _("Установить", "Install"))
            return

        # Установлена и уже загружена в память — всё готово, действие не нужно.
        if self._check_initialized(model_id):
            self._apply_model_status(chip, btn, "green",
                                     _("Готова", "Ready"), None, "")
            return

        # Установлена, но не загружена — предлагаем инициализировать.
        self._apply_model_status(chip, btn, "orange",
                                 _("Требуется инициализация", "Initialization required"),
                                 "init", _("Инициализировать", "Initialize"))

    def _apply_model_status(self, chip, btn, state: str, chip_text: str,
                            action: str | None, btn_text: str):
        if chip is not None:
            chip.setText(f"● {chip_text}")
            if chip.property("state") != state:
                chip.setProperty("state", state)
                # Переполировка нужна, чтобы QSS по динамическому свойству применился.
                st = chip.style()
                if st is not None:
                    st.unpolish(chip)
                    st.polish(chip)
        if btn is not None:
            if action:
                btn.setProperty("action", action)
                btn.setText(btn_text)
                btn.setVisible(True)
                st = btn.style()
                if st is not None:
                    st.unpolish(btn)
                    st.polish(btn)
            else:
                btn.setVisible(False)

    # ---------- local combobox ----------
    def _ensure_voice_model_name_map(self):
        now = time.time()
        ts = float(getattr(self, "_model_id_to_name_ts", 0.0) or 0.0)

        if self._model_id_to_name and (now - ts) < 30.0:
            return

        voice_models = services().get_optional(VoiceModelService)
        cfgs = voice_models.model_catalog_snapshot() if voice_models is not None else []

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
                from presets.local_voice_models import LOCAL_VOICE_MODELS
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

        installed_ids = self._canonical_installed_model_ids()

        ordered_ids = list(self._model_id_to_name.keys())
        ids = [mid for mid in ordered_ids if mid in installed_ids]
        items = [(self._model_id_to_name.get(mid, mid), mid) for mid in ids]
        self._set_local_model_selector_state(has_models=bool(items))

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
        if not self._backend_enabled():
            return

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

        if not self._show_loading_dialog(model_id):
            self._emit_voice_icon_state()
            return
        self._emit_voice_icon_state()

        self._initialize_local_model(model_id)

    # ---------- local loading dialog ----------
    def _show_loading_dialog(self, model_id: str) -> bool:
        """Возвращает True, если можно продолжать инициализацию, и False, если
        она должна быть отменена (например, нет папки models) — тогда вызывающий
        НЕ эмитит INIT_VOICE_MODEL."""
        if not self.view:
            return False

        # Гейт по GPU: не запускаем молча CUDA-модель на не-NVIDIA железе —
        # раньше это давало каскад triton «Failed to find CUDA» и путало юзеров
        # без видеокарты NVIDIA (фидбэк Артёма, Intel Iris Xe).
        if not self._confirm_gpu_compatibility(model_id):
            return False

        if not os.path.exists("models"):
            box = QMessageBox(self.view)
            box.setIcon(QMessageBox.Icon.Critical)
            box.setWindowTitle(_("Ошибка", "Error"))
            box.setText(_(
                "Невозможно инициализировать модель — не хватает установленной "
                "папки с моделями (models).\n\nСкачайте голоса Мит через AI Hub.",
                "Cannot initialize the model — the installed models folder is "
                "missing.\n\nDownload the Mita voices via the AI Hub.",
            ))
            open_btn = box.addButton(_("Открыть AI Hub", "Open AI Hub"),
                                     QMessageBox.ButtonRole.AcceptRole)
            box.addButton(_("Отмена", "Cancel"), QMessageBox.ButtonRole.RejectRole)
            box.exec()
            if box.clickedButton() is open_btn:
                try:
                    self.event_bus.emit(
                        Events.GUI.SHOW_WINDOW,
                        {"window_id": "ai_hub", "payload": {"category": "voices"}},
                    )
                except Exception as exc:
                    logger.error(f"Failed to open AI Hub from models error: {exc}")
            return False

        self._loading_model_id = model_id
        model_name = self._model_id_to_name.get(model_id, model_id)

        self._loading_dialog, _progress, self._loading_status_label = create_model_loading_dialog(
            self.view,
            model_name,
            lambda: self._user_cancel_loading()
        )
        self._loading_dialog.show()
        self._set_loading_status(_("Инициализация модели...", "Initializing model..."))
        return True

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

    # ---------- GPU compatibility gate ----------
    def _model_catalog_row(self, model_id: str) -> dict[str, Any]:
        catalog = services().get_optional(InstallableCatalogService)
        if catalog is None:
            return {}
        try:
            return dict(catalog.get_row(f"tts:{model_id}", include_status=False) or {})
        except Exception as exc:
            logger.warning(f"Cannot evaluate compatibility for voice model '{model_id}': {exc}")
            return {}

    def _model_compatibility(self, model_id: str) -> dict[str, Any]:
        row = self._model_catalog_row(model_id)
        verdict = dict(row.get("compatibility") or {})
        if verdict:
            return verdict
        return {
            "supported": False,
            "gpu_vendor": "UNKNOWN",
            "warning": _(
                "Не удалось проверить совместимость модели. Обновите AI Hub и повторите попытку.",
                "Model compatibility could not be verified. Refresh AI Hub and try again.",
            ),
        }

    def _confirm_gpu_compatibility(self, model_id: str) -> bool:
        """True — можно инициализировать; False — юзер отменил из-за несовместимости."""
        compatibility = self._model_compatibility(model_id)
        if bool(compatibility.get("supported")):
            return True
        if not self.view:
            return False

        model_name = self._model_id_to_name.get(model_id, model_id)
        vendors = str(compatibility.get("backend") or "AI")
        detected = str(compatibility.get("gpu_vendor") or "UNKNOWN")
        warning = str(compatibility.get("warning") or "").strip()

        box = QMessageBox(self.view)
        box.setIcon(QMessageBox.Icon.Warning)
        box.setWindowTitle(_("Несовместимая модель", "Incompatible model"))
        box.setText(_(
            f"Модель «{model_name}» использует backend {vendors}, несовместимый с устройством {detected}.\n\n"
            f"{warning}\n\nВсё равно попробовать запустить?",
            f"The model \"{model_name}\" uses the {vendors} backend, which is incompatible with {detected}.\n\n"
            f"{warning}\n\nTry to start it anyway?",
        ))
        yes_btn = box.addButton(_("Всё равно запустить", "Start anyway"),
                                QMessageBox.ButtonRole.AcceptRole)
        cancel_btn = box.addButton(_("Отмена", "Cancel"), QMessageBox.ButtonRole.RejectRole)
        box.setDefaultButton(cancel_btn)     # по умолчанию — безопасная отмена
        box.exec()
        return box.clickedButton() is yes_btn

    # ---------- backend checks ----------
    def _check_installed(self, model_id: str) -> bool:
        model_id = str(model_id or "").strip()
        if not model_id:
            return False
        return model_id in self._get_installed_models_set()

    def _check_initialized(self, model_id: str) -> bool:
        local_voice = services().get_optional(LocalVoiceService)
        return bool(local_voice and local_voice.check_initialized(model_id))

    def _select_model(self, model_id: str) -> bool:
        local_voice = services().get_optional(LocalVoiceService)
        return bool(local_voice and local_voice.select_model(model_id))

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

        super()._save_setting(key, value)

    def _get_setting(self, key: str, default=None):
        try:
            return self.main_controller.settings.get(key, default)
        except Exception:
            return default

    def _current_model_id_from_settings(self) -> str:
        v = self._get_setting("NM_CURRENT_VOICEOVER", None)
        return str(v or "").strip() if v else ""
