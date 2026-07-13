import threading

from PyQt6.QtCore import QTimer

from core.events import Events, Event
from core.services import services
from main_logger import logger
from services.contracts import SpeechService
from .base_controller import BaseController
from .asr_glossary_view_model import AsrGlossaryViewModel

from ui.windows.asr_glossary_view import AsrGlossaryView


class AsrGlossaryGuiController(BaseController):
    def __init__(self, main_controller, view):
        self._dialog = None
        self._view_model = AsrGlossaryViewModel(
            load_catalog=self._load_catalog,
            load_settings=self._load_settings,
            install_model=self._install_model,
            set_option=self._set_recognizer_option,
        )
        self._glossary_view: AsrGlossaryView | None = AsrGlossaryView(self._view_model)
        self._view_model.setParent(self._glossary_view)
        super().__init__(main_controller, view)

        self._register_window_on_ready()

    def _register_window_on_ready(self):
        if not self.view or not hasattr(self.view, "window_manager") or self.view.window_manager is None:
            return
        self.view.window_manager.set_dialog_on_ready("asr_glossary", self._on_dialog_ready)

    def subscribe_to_events(self):
        eb = self.event_bus
        eb.subscribe(Events.Install.TASK_PROGRESS, self._on_install_progress, weak=False)
        eb.subscribe(Events.Install.TASK_FINISHED, self._on_install_finished, weak=False)
        eb.subscribe(Events.Install.TASK_FAILED, self._on_install_failed, weak=False)

    def _on_dialog_ready(self, dialog, payload: dict):
        self._dialog = dialog

        if not self._glossary_view:
            return

        if dialog.layout() is None:
            logger.error("ASR glossary dialog has no layout")
            return

        try:
            if self._glossary_view.parent() is not None:
                self._glossary_view.setParent(None)
        except Exception:
            pass

        lay = dialog.layout()
        while lay.count():
            it = lay.takeAt(0)
            if it.widget():
                it.widget().deleteLater()

        lay.addWidget(self._glossary_view)

        QTimer.singleShot(0, self._view_model.refresh)

    def _install_model(self, engine_id: str) -> None:
        self.event_bus.emit(Events.Speech.INSTALL_ASR_MODEL, {"model": engine_id})

    def _speech_service(self) -> SpeechService:
        speech = services().get_optional(SpeechService)
        if speech is not None:
            return speech

        ensure = getattr(self.main_controller, "ensure_feature", None)
        if callable(ensure):
            ensure("speech", timeout=60.0)

        speech = services().get_optional(SpeechService)
        if speech is None:
            raise RuntimeError("Speech service failed to become ready")
        return speech

    def _load_catalog(self, refresh: bool) -> list[dict]:
        speech = self._speech_service()

        completed = threading.Event()
        result: dict[str, object] = {"models": [], "error": None}

        def callback(models, error=None):
            result["models"] = models if isinstance(models, list) else []
            result["error"] = error
            completed.set()

        speech.asr_models_glossary_async(callback, refresh=bool(refresh))
        if not completed.wait(timeout=60.0):
            raise TimeoutError("ASR model catalog request timed out")
        error = result.get("error")
        if error:
            raise RuntimeError(str(error))
        return list(result.get("models") or [])


    def _set_recognizer_option(self, engine_id: str, key: str, value) -> None:
        self.event_bus.emit(
            Events.Speech.SET_RECOGNIZER_OPTION,
            {"engine": str(engine_id), "key": str(key), "value": value},
        )

    def _load_settings(self, engine_id: str) -> dict:
        speech = self._speech_service()
        return {
            "schema": speech.recognizer_settings_schema(str(engine_id)) or [],
            "values": speech.recognizer_settings(str(engine_id)) or {},
        }

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

    def _on_install_progress(self, event: Event):
        data = event.data or {}
        if not self._is_asr_task(data):
            return
        model = self._task_model_id(data)
        if not model:
            return
        self._view_model.install_progress(
            engine_id=str(model),
            progress=int(data.get("progress", 0) or 0),
            status=str(data.get("status", "") or ""),
        )

    def _on_install_finished(self, event: Event):
        data = event.data or {}
        if not self._is_asr_task(data):
            return
        model = self._task_model_id(data)
        if not model:
            return
        self._view_model.install_finished(str(model))

    def _on_install_failed(self, event: Event):
        data = event.data or {}
        if not self._is_asr_task(data):
            return
        model = self._task_model_id(data)
        if not model:
            return
        self._view_model.install_failed(
            str(model),
            str(data.get("error", "") or ""),
        )

    def close(self) -> None:
        self._view_model.close()
        super().close()