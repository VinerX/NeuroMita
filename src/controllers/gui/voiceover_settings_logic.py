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

    def _local_model_already_installed() -> bool:
        """Установлена ли уже выбранная локальная модель.

        Пользователь мог положить файлы модели вручную (или поставить её раньше) —
        тогда предлагать «сначала установить модель» не нужно (фидбэк Артёма:
        предложение всплывало поверх готовой установки). Источник — тот же
        синхронный реестр установленных моделей, что и у иконки статуса."""
        combo = getattr(self, "local_voice_combobox", None)
        if combo is None:
            return True

        installed = set()
        try:
            for index in range(combo.count()):
                model_id = str(combo.itemData(index) or "").strip()
                if model_id:
                    installed.add(model_id)
        except Exception:
            installed = set()

        if not installed:
            return True
        current = str(self.settings.get("NM_CURRENT_VOICEOVER", "") or "").strip()
        # Что-то уже установлено: если конкретная выбранная модель стоит — точно
        # не предлагаем; если модель не выбрана, но установленные есть — тоже не
        # навязываем (пользователю есть чем озвучивать).
        return (not current) or (current in installed)

    def _show_ai_hub_offer():
        if bool(self.settings.get("VOICEOVER_LOCAL_AI_HUB_PROMPTED", False)):
            return

        if _local_model_already_installed():
            return

        self._save_setting("VOICEOVER_LOCAL_AI_HUB_PROMPTED", True)

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

    # --- Local model action button (Установить / Инициализировать) ---
    # Кнопка одна, а действие зависит от свойства "action", которое выставляет
    # VoiceoverGuiController._sync_local_model_status в зависимости от состояния
    # выбранной модели. Так пользователь всегда видит, что именно нажать.
    if hasattr(self, "local_model_action_btn") and self.local_model_action_btn is not None:
        try:
            if hasattr(self, "_on_local_model_action"):
                self.local_model_action_btn.clicked.disconnect(self._on_local_model_action)
        except Exception:
            pass

        def _on_local_model_action():
            action = str(self.local_model_action_btn.property("action") or "").strip()
            if action == "install":
                eb.emit(Events.GUI.SHOW_WINDOW, {"window_id": "ai_hub", "payload": {"category": "tts"}})
            elif action == "init":
                mid = self.local_voice_combobox.currentData() if self.local_voice_combobox is not None else None
                if mid:
                    # Тот же поток, что и выбор модели в комбобоксе: покажет диалог
                    # загрузки и запустит INIT_VOICE_MODEL.
                    eb.emit(Events.GUI.VOICEOVER_MODEL_SELECTED, {"model_id": mid})

        self._on_local_model_action = _on_local_model_action
        self.local_model_action_btn.clicked.connect(self._on_local_model_action)

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
