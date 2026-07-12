from PyQt6.QtCore import QTimer

from core.events import Events, Event
from core.services import services
from main_logger import logger
from services.contracts import SpeechService
from .base_controller import BaseController

from ui.windows.asr_glossary_view import AsrGlossaryView


class AsrGlossaryGuiController(BaseController):
    def __init__(self, main_controller, view):
        self._dialog = None
        self._glossary_view: AsrGlossaryView | None = AsrGlossaryView()
        super().__init__(main_controller, view)

        self._register_window_on_ready()

        self._glossary_view.request_install.connect(self._request_install)
        self._glossary_view.request_refresh.connect(self._request_refresh)
        self._glossary_view.request_settings.connect(self._request_settings)
        self._glossary_view.setting_changed.connect(self._set_recognizer_option)

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

        QTimer.singleShot(0, self._glossary_view.refresh)

    def _request_install(self, engine_id: str):
        self.event_bus.emit(Events.Speech.INSTALL_ASR_MODEL, {"model": engine_id})

    def _request_refresh(self):
        view = self._glossary_view
        if view is None:
            return
        ticket = view.begin_refresh()
        speech = services().get_optional(SpeechService)
        if speech is None:
            view.catalog_loaded_signal.emit(
                {
                    "ticket": ticket,
                    "models": [],
                    "error": "Speech service is unavailable",
                }
            )
            return

        def callback(models, error=None):
            view.catalog_loaded_signal.emit(
                {
                    "ticket": ticket,
                    "models": models if isinstance(models, list) else [],
                    "error": str(error or ""),
                }
            )

        try:
            speech.asr_models_glossary_async(callback, refresh=True)
        except Exception as exc:
            callback([], exc)


    def _set_recognizer_option(self, engine_id: str, key: str, value) -> None:
        self.event_bus.emit(
            Events.Speech.SET_RECOGNIZER_OPTION,
            {"engine": str(engine_id), "key": str(key), "value": value},
        )

    def _request_settings(self, engine_id: str, ticket: int) -> None:
        view = self._glossary_view
        if view is None:
            return

        def worker():
            speech = services().get_optional(SpeechService)
            if speech is None:
                raise RuntimeError("Speech service is unavailable")
            return {
                "ticket": int(ticket),
                "engine_id": str(engine_id),
                "schema": speech.recognizer_settings_schema(str(engine_id)) or [],
                "values": speech.recognizer_settings(str(engine_id)) or {},
            }

        def apply(payload: dict) -> None:
            view.settings_loaded_signal.emit(payload)

        def fail(exc: Exception) -> None:
            view.settings_loaded_signal.emit(
                {
                    "ticket": int(ticket),
                    "engine_id": str(engine_id),
                    "schema": [],
                    "values": {},
                    "error": str(exc),
                }
            )

        self._run_async(
            worker,
            apply,
            fail,
            name=f"asr-settings:{engine_id}",
        )

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
        if not self._glossary_view:
            return
        data = event.data or {}
        if not self._is_asr_task(data):
            return
        model = self._task_model_id(data)
        if not model:
            return
        self._glossary_view.on_install_progress(
            model=str(model),
            progress=int(data.get("progress", 0) or 0),
            status=str(data.get("status", "") or "")
        )

    def _on_install_finished(self, event: Event):
        if not self._glossary_view:
            return
        data = event.data or {}
        if not self._is_asr_task(data):
            return
        model = self._task_model_id(data)
        if not model:
            return
        self._glossary_view.on_install_finished(str(model))

    def _on_install_failed(self, event: Event):
        if not self._glossary_view:
            return
        data = event.data or {}
        if not self._is_asr_task(data):
            return
        model = self._task_model_id(data)
        if not model:
            return
        self._glossary_view.on_install_failed(str(model), str(data.get("error", "") or ""))