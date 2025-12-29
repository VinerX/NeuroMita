from PyQt6.QtCore import QTimer

from core.events import Events, Event
from main_logger import logger
from .base_controller import BaseController

from ui.windows.asr_glossary_view import AsrGlossaryView


class AsrGlossaryGuiController(BaseController):
    def __init__(self, main_controller, view):
        self._dialog = None
        self._glossary_view: AsrGlossaryView | None = AsrGlossaryView()
        super().__init__(main_controller, view)

        self._register_window_on_ready()

        # wiring view actions
        self._glossary_view.request_install.connect(self._request_install)
        self._glossary_view.request_refresh.connect(self._request_refresh)

    def _register_window_on_ready(self):
        if not self.view or not hasattr(self.view, "window_manager") or self.view.window_manager is None:
            return
        self.view.window_manager.set_dialog_on_ready("asr_glossary", self._on_dialog_ready)

    def subscribe_to_events(self):
        eb = self.event_bus

        eb.subscribe(Events.Speech.ASR_MODEL_INSTALL_PROGRESS, self._on_install_progress, weak=False)
        eb.subscribe(Events.Speech.ASR_MODEL_INSTALL_FINISHED, self._on_install_finished, weak=False)
        eb.subscribe(Events.Speech.ASR_MODEL_INSTALL_FAILED, self._on_install_failed, weak=False)

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
        if self._glossary_view:
            self._glossary_view.refresh()

    def _on_install_progress(self, event: Event):
        if not self._glossary_view:
            return
        data = event.data or {}
        model = data.get("model")
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
        model = data.get("model")
        if not model:
            return
        self._glossary_view.on_install_finished(str(model))

    def _on_install_failed(self, event: Event):
        if not self._glossary_view:
            return
        data = event.data or {}
        model = data.get("model")
        if not model:
            return
        self._glossary_view.on_install_failed(str(model), str(data.get("error", "") or ""))