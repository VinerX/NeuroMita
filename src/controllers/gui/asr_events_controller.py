from main_logger import logger
from core.events import Events, Event
from .base_controller import BaseController
from utils import getTranslationVariant as _


class AsrEventsController(BaseController):
    def subscribe_to_events(self):
        eb = self.event_bus

        eb.subscribe(Events.Speech.ASR_MODEL_INIT_STARTED, self._on_asr_init_started, weak=False)
        eb.subscribe(Events.Speech.ASR_MODEL_INITIALIZED, self._on_asr_initialized, weak=False)

        eb.subscribe(Events.Install.TASK_STARTED, self._on_install_started, weak=False)
        eb.subscribe(Events.Install.TASK_PROGRESS, self._on_install_progress, weak=False)
        eb.subscribe(Events.Install.TASK_FINISHED, self._on_install_finished, weak=False)
        eb.subscribe(Events.Install.TASK_FAILED, self._on_install_failed, weak=False)

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

    def _on_asr_init_started(self, _event: Event):
        if not self.view:
            return
        if hasattr(self.view, "asr_set_pill") and hasattr(self.view, "asr_init_status"):
            try:
                self.view.asr_set_pill.emit({
                    "label": self.view.asr_init_status,
                    "text": _("Инициализация...", "Initializing..."),
                    "kind": "progress"
                })
            except Exception as e:
                logger.debug(f"ASR init pill update failed: {e}")

        self.event_bus.emit(Events.GUI.UPDATE_STATUS_COLORS)

    def _on_asr_initialized(self, _event: Event):
        if not self.view:
            return
        if hasattr(self.view, "asr_set_pill") and hasattr(self.view, "asr_init_status"):
            try:
                self.view.asr_set_pill.emit({
                    "label": self.view.asr_init_status,
                    "text": _("Готово", "Ready"),
                    "kind": "ok"
                })
            except Exception as e:
                logger.debug(f"ASR initialized pill update failed: {e}")

        self.event_bus.emit(Events.GUI.UPDATE_STATUS_COLORS)

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

    def _on_install_started(self, event: Event):
        data = event.data or {}
        if not self._is_asr_task(data):
            return
        model = self._task_model_id(data)
        if not model:
            return
        self._emit_install_progress({
            "model": str(model),
            "progress": 0,
            "status": _("Подготовка...", "Preparing...")
        })

    def _on_install_progress(self, event: Event):
        data = event.data or {}
        if not self._is_asr_task(data):
            return
        model = self._task_model_id(data)
        if not model:
            return
        self._emit_install_progress({
            "model": str(model),
            "progress": int(data.get("progress", 0) or 0),
            "status": str(data.get("status", "") or "")
        })

    def _on_install_finished(self, event: Event):
        data = event.data or {}
        if not self._is_asr_task(data):
            return
        model = self._task_model_id(data)
        if not model:
            return
        self._emit_install_finished({"model": str(model)})

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