from main_logger import logger
from core.events import Events, Event
from .base_controller import BaseController
from utils import getTranslationVariant as _


class AsrEventsController(BaseController):
    def subscribe_to_events(self):
        eb = self.event_bus

        eb.subscribe(Events.Speech.ASR_MODEL_INIT_STARTED, self._on_asr_init_started, weak=False)
        eb.subscribe(Events.Speech.ASR_MODEL_INITIALIZED, self._on_asr_initialized, weak=False)

        eb.subscribe(Events.Speech.ASR_MODEL_INSTALL_STARTED, self._on_install_started, weak=False)
        eb.subscribe(Events.Speech.ASR_MODEL_INSTALL_PROGRESS, self._on_install_progress, weak=False)
        eb.subscribe(Events.Speech.ASR_MODEL_INSTALL_FINISHED, self._on_install_finished, weak=False)
        eb.subscribe(Events.Speech.ASR_MODEL_INSTALL_FAILED, self._on_install_failed, weak=False)

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

    def _on_install_started(self, event: Event):
        data = event.data or {}
        model = data.get("model")
        if not model:
            return
        # Нормализуем: старт тоже прокидываем как progress=0, чтобы UI мог реагировать единообразно
        self._emit_install_progress({
            "model": model,
            "progress": 0,
            "status": data.get("status") or _("Подготовка...", "Preparing...")
        })

    def _on_install_progress(self, event: Event):
        data = event.data or {}
        model = data.get("model")
        if not model:
            return
        self._emit_install_progress({
            "model": model,
            "progress": int(data.get("progress", 0) or 0),
            "status": data.get("status", "")
        })

    def _on_install_finished(self, event: Event):
        
        logger.notify("[DEBUG] asr_events_controller.py: зашёл")
        data = event.data or {}
        model = data.get("model")
        if not model:
            
            logger.notify("[DEBUG] asr_events_controller.py: NOT MODEL!")
            return
        
        logger.notify("[DEBUG] asr_events_controller.py: Перед эмитом _emit_install_finished.")
        self._emit_install_finished({"model": model})
        logger.notify("[DEBUG] asr_events_controller.py: После эмита _emit_install_finished.")

    def _on_install_failed(self, event: Event):
        data = event.data or {}
        model = data.get("model")
        if not model:
            return
        self._emit_install_failed({"model": model, "error": data.get("error", "")})