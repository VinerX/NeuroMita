from __future__ import annotations

import threading
import time

from main_logger import logger
from core.events import Events, Event
from .base_controller import BaseController
from utils import getTranslationVariant as _


class AsrEventsController(BaseController):
    def __init__(self, main_controller, view):
        self._asr_initializing: bool = False
        self._asr_installing: bool = False
        self._install_engine: str | None = None
        self._install_progress: int | None = None
        self._install_status: str | None = None

        self._last_state: str | None = None
        self._last_tooltip: str | None = None

        self._init_token: int = 0

        self._settings_cache: dict[str, object] = {}
        self._installed_cache: dict[str, tuple[bool | None, float]] = {}
        self._installed_inflight: dict[str, int] = {}
        self._installed_ttl_sec: float = 10.0

        self._ready_cache: tuple[bool | None, float] = (None, 0.0)
        self._ready_inflight_token: int = 0
        self._ready_ttl_sec: float = 0.8

        super().__init__(main_controller, view)

    def subscribe_to_events(self):
        eb = self.event_bus

        eb.subscribe(Events.Speech.ASR_MODEL_INIT_STARTED, self._on_asr_init_started, weak=False)
        eb.subscribe(Events.Speech.ASR_MODEL_INITIALIZED, self._on_asr_initialized, weak=False)

        eb.subscribe(Events.Install.TASK_STARTED, self._on_install_started, weak=False)
        eb.subscribe(Events.Install.TASK_PROGRESS, self._on_install_progress, weak=False)
        eb.subscribe(Events.Install.TASK_FINISHED, self._on_install_finished, weak=False)
        eb.subscribe(Events.Install.TASK_FAILED, self._on_install_failed, weak=False)

        eb.subscribe(Events.Core.SETTING_CHANGED, self._on_setting_changed, weak=False)

        try:
            if self.view and getattr(self.view, "settings", None):
                self._settings_cache["MIC_ACTIVE"] = bool(self.view.settings.get("MIC_ACTIVE", False))
                self._settings_cache["RECOGNIZER_TYPE"] = str(self.view.settings.get("RECOGNIZER_TYPE", "google") or "google")
        except Exception:
            pass

        mic_active = bool(self._settings_cache.get("MIC_ACTIVE", False))
        if mic_active:
            self._asr_initializing = True
            self._emit_indicator("loading", _("Инициализация ASR...", "Initializing ASR..."))
            self._sync_indicator(force=True)
        else:
            self._emit_indicator(None, None)

    # ---------------- UI pills from old logic ----------------
    def _on_asr_init_started(self, _event: Event):
        self._asr_initializing = True
        self._init_token += 1
        tok = self._init_token

        if self.view and hasattr(self.view, "asr_set_pill") and hasattr(self.view, "asr_init_status"):
            try:
                self.view.asr_set_pill.emit({
                    "label": self.view.asr_init_status,
                    "text": _("Инициализация...", "Initializing..."),
                    "kind": "progress"
                })
            except Exception as e:
                logger.debug(f"ASR init pill update failed: {e}")

        self._sync_indicator()

        def _timeout_guard():
            time.sleep(35.0)
            if self._init_token != tok:
                return
            if self._asr_initializing:
                self._asr_initializing = False
                self._sync_indicator(force=True)

        threading.Thread(target=_timeout_guard, daemon=True).start()

        self.event_bus.emit(Events.GUI.UPDATE_STATUS_COLORS)

    def _on_asr_initialized(self, _event: Event):
        self._asr_initializing = False

        if self.view and hasattr(self.view, "asr_set_pill") and hasattr(self.view, "asr_init_status"):
            try:
                self.view.asr_set_pill.emit({
                    "label": self.view.asr_init_status,
                    "text": _("Готово", "Ready"),
                    "kind": "ok"
                })
            except Exception as e:
                logger.debug(f"ASR initialized pill update failed: {e}")

        self._sync_indicator(force=True)
        self.event_bus.emit(Events.GUI.UPDATE_STATUS_COLORS)

    # ---------------- install events ----------------
    def _is_asr_task(self, data: dict) -> bool:
        if not isinstance(data, dict):
            return False
        if data.get("kind") == "asr":
            return True
        meta = data.get("meta") if isinstance(data.get("meta"), dict) else {}
        return meta.get("kind") == "asr"

    def _task_model_id(self, data: dict) -> str | None:
        meta = data.get("meta") if isinstance(data.get("meta"), dict) else {}
        return data.get("item_id") or meta.get("item_id") or data.get("model")

    def _emit_install_progress(self, payload: dict):
        if not self.view:
            return
        sig = getattr(self.view, "asr_install_progress_signal", None)
        if sig:
            sig.emit(payload)

    def _emit_install_finished(self, payload: dict):
        if not self.view:
            return
        sig = getattr(self.view, "asr_install_finished_signal", None)
        if sig:
            sig.emit(payload)

    def _emit_install_failed(self, payload: dict):
        if not self.view:
            return
        sig = getattr(self.view, "asr_install_failed_signal", None)
        if sig:
            sig.emit(payload)

    def _on_install_started(self, event: Event):
        data = event.data or {}
        if not self._is_asr_task(data):
            return
        model = self._task_model_id(data)
        if not model:
            return

        self._asr_installing = True
        self._install_engine = str(model)
        self._install_progress = 0
        self._install_status = _("Подготовка...", "Preparing...")

        self._emit_install_progress({
            "model": str(model),
            "progress": 0,
            "status": self._install_status
        })

        self._sync_indicator(force=True)

    def _on_install_progress(self, event: Event):
        data = event.data or {}
        if not self._is_asr_task(data):
            return
        model = self._task_model_id(data)
        if not model:
            return

        self._asr_installing = True
        self._install_engine = str(model)
        self._install_progress = int(data.get("progress", 0) or 0)
        self._install_status = str(data.get("status", "") or "")

        self._emit_install_progress({
            "model": str(model),
            "progress": int(self._install_progress or 0),
            "status": str(self._install_status or "")
        })

        self._sync_indicator()

    def _on_install_finished(self, event: Event):
        data = event.data or {}
        if not self._is_asr_task(data):
            return
        model = self._task_model_id(data)
        if not model:
            return

        self._emit_install_finished({"model": str(model)})

        self._asr_installing = False
        self._install_progress = None
        self._install_status = None
        self._install_engine = None

        self._installed_cache.pop(str(model), None)

        self._sync_indicator(force=True)

    def _on_install_failed(self, event: Event):
        data = event.data or {}
        if not self._is_asr_task(data):
            return
        model = self._task_model_id(data)
        if not model:
            return

        self._emit_install_failed({
            "model": str(model),
            "error": str(data.get("error", "") or "")
        })

        self._asr_installing = False
        self._install_progress = None
        self._install_status = None
        self._install_engine = None

        self._sync_indicator(force=True)

    # ---------------- settings changes ----------------
    def _on_setting_changed(self, event: Event):
        data = event.data or {}
        key = str(data.get("key") or "").strip()
        if key in ("MIC_ACTIVE", "RECOGNIZER_TYPE"):
            self._settings_cache[key] = data.get("value")

            if key == "MIC_ACTIVE":
                try:
                    if not bool(data.get("value", False)):
                        self._asr_initializing = False
                        self._ready_cache = (None, 0.0)
                except Exception:
                    pass

            if key == "RECOGNIZER_TYPE":
                self._ready_cache = (None, 0.0)

            self._sync_indicator(force=True)

    # ---------------- indicator logic ----------------
    def _emit_indicator(self, state: str | None, tooltip: str | None):
        st = state if state in (None, "red", "green", "loading") else None
        tt = str(tooltip) if tooltip else None

        if st == self._last_state and tt == self._last_tooltip:
            return

        self._last_state = st
        self._last_tooltip = tt

        self.event_bus.emit(Events.GUI.SET_SETTINGS_ICON_INDICATOR, {
            "category": "microphone",
            "state": st,
            "tooltip": tt
        })

    def _ui_safe(self, fn):
        try:
            self._ui(fn)
        except Exception:
            try:
                fn()
            except Exception:
                pass

    def _get_cached_setting(self, key: str, default=None):
        if key in self._settings_cache:
            return self._settings_cache.get(key, default)
        try:
            if self.view and getattr(self.view, "settings", None):
                v = self.view.settings.get(key, default)
                self._settings_cache[key] = v
                return v
        except Exception:
            pass
        return default

    def _request_installed_check(self, engine: str):
        eng = str(engine or "").strip()
        if not eng:
            return

        tok = int(self._installed_inflight.get(eng, 0)) + 1
        self._installed_inflight[eng] = tok

        def cb(result, error=None):
            def apply():
                if int(self._installed_inflight.get(eng, 0)) != tok:
                    return
                ok = False
                if error is None:
                    ok = bool(result)
                self._installed_cache[eng] = (ok, time.time())
                self._sync_indicator(force=True)

            self._ui_safe(apply)

        try:
            self.event_bus.emit(Events.Speech.CHECK_ASR_MODEL_INSTALLED, {
                "model": eng,
                "callback": cb
            })
        except Exception:
            pass

    def _get_installed_cached(self, engine: str) -> bool | None:
        eng = str(engine or "").strip()
        if not eng:
            return None
        v = self._installed_cache.get(eng)
        if not v:
            return None
        ok, ts = v
        if (time.time() - float(ts or 0.0)) > self._installed_ttl_sec:
            return None
        return ok

    def _request_ready_check(self):
        self._ready_inflight_token += 1
        tok = self._ready_inflight_token

        def cb(result, error=None):
            def apply():
                if self._ready_inflight_token != tok:
                    return
                ok = False
                if error is None:
                    ok = bool(result)
                self._ready_cache = (ok, time.time())
                self._sync_indicator(force=True)

            self._ui_safe(apply)

        try:
            self.event_bus.emit(Events.Speech.GET_MIC_STATUS, {"callback": cb})
        except Exception:
            pass

    def _get_ready_cached(self) -> bool | None:
        ok, ts = self._ready_cache
        if ok is None:
            return None
        if (time.time() - float(ts or 0.0)) > self._ready_ttl_sec:
            return None
        return ok

    def _sync_indicator(self, force: bool = False):
        mic_active = bool(self._get_cached_setting("MIC_ACTIVE", False))
        engine = str(self._get_cached_setting("RECOGNIZER_TYPE", "google") or "google").strip()

        if self._asr_installing:
            p = self._install_progress
            st = self._install_status or ""
            eng = self._install_engine or engine
            msg = _("Установка ASR: ", "Installing ASR: ") + str(eng)
            if isinstance(p, int):
                msg += f" ({p}%)"
            if st:
                msg += f" — {st}"
            self._emit_indicator("loading", msg)
            return

        if not mic_active:
            self._emit_indicator(None, None)
            return

        installed = self._get_installed_cached(engine)
        if installed is None:
            self._emit_indicator("loading", _("Проверка ASR модели...", "Checking ASR model...") + f" {engine}")
            self._request_installed_check(engine)
            return

        if engine and not installed:
            self._emit_indicator("red", _("ASR модель не установлена: ", "ASR model not installed: ") + engine)
            return

        if self._asr_initializing:
            self._emit_indicator("loading", _("Инициализация ASR...", "Initializing ASR..."))
            return

        ready = self._get_ready_cached()
        if ready is None:
            self._emit_indicator("loading", _("Проверка статуса ASR...", "Checking ASR status..."))
            self._request_ready_check()
            return

        if ready:
            self._emit_indicator("green", _("ASR готов", "ASR ready"))
        else:
            self._emit_indicator("red", _("ASR не готов", "ASR not ready"))