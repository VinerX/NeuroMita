from PyQt6.QtCore import QTimer
from PyQt6.QtWidgets import QMessageBox
from core.events import get_event_bus, Events
from utils import getTranslationVariant as _


def wire_voiceover_settings_logic(self):
    eb = get_event_bus()
    self._voiceover_last_method_seen = str(
        getattr(getattr(self, "method_combobox", None), "currentText", lambda: "")()
        or self.settings.get("VOICEOVER_METHOD", "Local")
        or "Local"
    ).strip()

    def request_refresh():
        if bool(getattr(self, "_voiceover_refresh_pending", False)):
            return
        self._voiceover_refresh_pending = True

        def fire():
            self._voiceover_refresh_pending = False
            eb.emit(Events.GUI.VOICEOVER_REFRESH)

        QTimer.singleShot(0, fire)

    def _show_ai_hub_offer():
        if bool(self.settings.get("VOICEOVER_LOCAL_AI_HUB_PROMPTED", False)):
            return

        self.settings.set("VOICEOVER_LOCAL_AI_HUB_PROMPTED", True)
        eb.emit(Events.Settings.SAVE_SETTING, {"key": "VOICEOVER_LOCAL_AI_HUB_PROMPTED", "value": True})

        box = QMessageBox(self)
        box.setIcon(QMessageBox.Icon.Question)
        box.setWindowTitle(_("Локальная озвучка", "Local voiceover"))
        box.setText(_(
            "Для локальной озвучки сначала нужно установить модель.\n\nОткрыть AI Hub сейчас?",
            "A model must be installed before local voiceover can work.\n\nOpen AI Hub now?",
        ))
        box.setStandardButtons(QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
        box.setDefaultButton(QMessageBox.StandardButton.Yes)
        if box.exec() == QMessageBox.StandardButton.Yes:
            eb.emit(Events.GUI.SHOW_WINDOW, {"window_id": "ai_hub", "payload": {"category": "tts"}})

    def maybe_offer_ai_hub_on_local_switch(new_method: str):
        previous_method = str(getattr(self, "_voiceover_last_method_seen", "") or "").strip()
        current_method = str(new_method or "").strip()
        self._voiceover_last_method_seen = current_method

        if current_method != "Local" or previous_method == "Local":
            return
        _show_ai_hub_offer()

    def maybe_offer_ai_hub_for_current_state():
        current_method = str(
            getattr(getattr(self, "method_combobox", None), "currentText", lambda: "")()
            or self.settings.get("VOICEOVER_METHOD", "Local")
            or "Local"
        ).strip()
        if current_method == "Local":
            _show_ai_hub_offer()

    # --- Local model combobox ---
    if hasattr(self, "local_voice_combobox") and self.local_voice_combobox is not None:
        try:
            if hasattr(self, "_on_local_model_changed"):
                self.local_voice_combobox.activated.disconnect(self._on_local_model_changed)
        except Exception:
            pass

        def _on_local_model_changed(_idx: int):
            mid = self.local_voice_combobox.currentData()
            eb.emit(Events.GUI.VOICEOVER_MODEL_SELECTED, {"model_id": mid})

        self._on_local_model_changed = _on_local_model_changed
        self.local_voice_combobox.activated.connect(self._on_local_model_changed)

    # --- Method combobox ---
    if hasattr(self, "method_combobox") and self.method_combobox is not None:
        try:
            if hasattr(self, "_on_voiceover_method_changed"):
                self.method_combobox.currentTextChanged.disconnect(self._on_voiceover_method_changed)
        except Exception:
            pass

        def _on_voiceover_method_changed(_t: str):
            maybe_offer_ai_hub_on_local_switch(_t)
            request_refresh()

        self._on_voiceover_method_changed = _on_voiceover_method_changed
        self.method_combobox.currentTextChanged.connect(self._on_voiceover_method_changed)

    # --- Use voice checkbox ---
    if hasattr(self, "use_voice_checkbox") and self.use_voice_checkbox is not None:
        try:
            if hasattr(self, "_on_use_voice_changed"):
                self.use_voice_checkbox.stateChanged.disconnect(self._on_use_voice_changed)
        except Exception:
            pass

        def _on_use_voice_changed(_s: int):
            if bool(getattr(self, "use_voice_checkbox", None).isChecked()):
                maybe_offer_ai_hub_for_current_state()
            request_refresh()

        self._on_use_voice_changed = _on_use_voice_changed
        self.use_voice_checkbox.stateChanged.connect(self._on_use_voice_changed)

    request_refresh()
