from __future__ import annotations

from weakref import WeakKeyDictionary

from core.error_utils import format_exception
from main_logger import logger
from ui.dialogs.message_processing_dialog import MessageProcessingDialog

from .base_controller import BaseController


class ProtocolPipelineGuiController(BaseController):
    def subscribe_to_events(self):
        self._ensure_registered()

    def _ensure_registered(self):
        if not self.view or getattr(self.view, "window_manager", None) is None:
            return
        if getattr(self.view, "_protocol_pipeline_registered", False):
            return

        self._apply_callbacks = WeakKeyDictionary()

        def on_ready(dialog, payload):
            payload = payload or {}
            self._apply_callbacks[dialog] = payload.get("on_apply")
            dialog.apply_payload(payload)

        def factory(parent, payload):
            dialog = MessageProcessingDialog(parent)
            dialog.accepted.connect(lambda: self._apply(dialog))
            on_ready(dialog, payload)
            return dialog

        self.view.window_manager.register_dialog(
            "protocol_pipeline",
            factory=factory,
            singleton=True,
            hide_on_close=True,
            modal=True,
            on_ready=on_ready,
        )
        self.view._protocol_pipeline_registered = True
        logger.info("ProtocolPipeline dialog registered in WindowManager")

    def _apply(self, dialog):
        callback = self._apply_callbacks.get(dialog)
        if callable(callback):
            try:
                callback(dialog.transforms())
            except Exception as exc:
                logger.error(
                    f"pipeline on_apply failed: {format_exception(exc)}", exc_info=True
                )
