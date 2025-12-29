# src/ui/settings/microphone_settings/logic.py
import re
from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtGui import QFontMetrics

from utils import getTranslationVariant as _
from main_logger import logger
from core.events import get_event_bus, Events
from styles.main_styles import get_theme


def wire_microphone_settings_logic(self):
    bus = get_event_bus()
    theme = get_theme()

    def _pill_style(kind: str):
        if kind == "ok":
            fg = theme["success"]
            bg = "rgba(61,166,110,0.12)"
            br = "rgba(61,166,110,0.45)"
        elif kind == "warn":
            fg = theme["danger"]
            bg = "rgba(214,69,69,0.12)"
            br = "rgba(214,69,69,0.45)"
        elif kind == "progress":
            fg = theme["accent"]
            bg = "rgba(138,43,226,0.12)"
            br = theme["accent_border"]
        else:
            fg = theme["text"]
            bg = theme["chip_bg"]
            br = theme["border_soft"]
        return fg, bg, br

    def set_pill(data: dict):
        try:
            lbl = data.get("label")
            if lbl is None:
                return
            text = str(data.get("text", "") or "")
            kind = str(data.get("kind", "info") or "info")

            fg, bg, br = _pill_style(kind)
            lbl.setText(text)
            lbl.setStyleSheet(
                f"QLabel {{ padding: 2px 6px; border-radius: 8px; "
                f"font-weight: 600; font-size: 11px; "
                f"color: {fg}; background: {bg}; border: 1px solid {br}; }}"
            )
        except Exception as e:
            logger.debug(f"asr_set_pill handler failed: {e}")

    def set_pill_called(lbl, text: str, kind: str = "info"):
        if hasattr(self, "asr_set_pill"):
            try:
                self.asr_set_pill.emit({"label": lbl, "text": text, "kind": kind})
                return
            except Exception:
                pass
        try:
            set_pill({"label": lbl, "text": text, "kind": kind})
        except Exception:
            pass

    def reset_init_status():
        if hasattr(self, "asr_init_status") and self.asr_init_status is not None:
            set_pill_called(self.asr_init_status, "—", "info")

    # подключаем обработчик "пилюль" (его используют AsrEventsController и др.)
    if hasattr(self, "asr_set_pill"):
        try:
            if hasattr(self, "_on_asr_set_pill"):
                self.asr_set_pill.disconnect(self._on_asr_set_pill)
        except Exception:
            pass

        self._on_asr_set_pill = set_pill
        try:
            self.asr_set_pill.connect(self._on_asr_set_pill)
        except Exception:
            pass

    reset_init_status()

    def truncate_text_for_width(text, widget, max_width):
        metrics = QFontMetrics(widget.font())
        ellipsis = "..."
        ellipsis_width = metrics.horizontalAdvance(ellipsis)
        available_width = max(max_width - ellipsis_width - 20, 20)

        if metrics.horizontalAdvance(text) <= available_width:
            return text

        left, right = 0, len(text)
        result = ""
        while left <= right:
            mid = (left + right) // 2
            truncated = text[:mid]
            if metrics.horizontalAdvance(truncated) <= available_width:
                result = truncated
                left = mid + 1
            else:
                right = mid - 1

        return result + ellipsis if result else ellipsis

    def populate_mics():
        res = bus.emit_and_wait(Events.Speech.GET_MICROPHONE_LIST, timeout=1.0)
        mic_list = res[0] if res else [_("Микрофоны не найдены", "No microphones found")]

        self.mic_combobox.blockSignals(True)
        try:
            self.mic_combobox.clear()
            max_text_width = self.mic_combobox.maximumWidth() if self.mic_combobox.maximumWidth() < 10000 else 180

            for mic_name in mic_list:
                display = truncate_text_for_width(mic_name, self.mic_combobox, max_text_width)
                if len(display) > 30:
                    display = mic_name[:27] + "..."
                self.mic_combobox.addItem(display)
                idx = self.mic_combobox.count() - 1
                self.mic_combobox.setItemData(idx, mic_name, Qt.ItemDataRole.UserRole)
                self.mic_combobox.setItemData(idx, mic_name, Qt.ItemDataRole.ToolTipRole)

            current_full = self.settings.get("MIC_DEVICE", mic_list[0] if mic_list else "")
            for i in range(self.mic_combobox.count()):
                if self.mic_combobox.itemData(i, Qt.ItemDataRole.UserRole) == current_full:
                    self.mic_combobox.setCurrentIndex(i)
                    break
            self.mic_combobox.setToolTip(current_full)
        finally:
            self.mic_combobox.blockSignals(False)

    def apply_asr_install_status(engine: str):
        if not engine or not getattr(self, "recognizer_combobox", None) or not self.recognizer_combobox.isEnabled():
            try:
                self.mic_active_checkbox.setChecked(False)
                self.mic_active_checkbox.setEnabled(False)
            except Exception:
                pass
            return

        res = bus.emit_and_wait(Events.Speech.CHECK_ASR_MODEL_INSTALLED, {"model": engine}, timeout=1.0)
        installed = bool(res and res[0])

        try:
            self.mic_active_checkbox.setEnabled(bool(installed))
            if not installed:
                self.mic_active_checkbox.setChecked(False)
        except Exception:
            pass

    def populate_engines(select_engine: str | None = None):
        prev_engine = ""
        try:
            prev_engine = self.recognizer_combobox.currentText() if self.recognizer_combobox.isEnabled() else ""
        except Exception:
            prev_engine = ""

        res = bus.emit_and_wait(Events.Speech.GET_ASR_MODELS_GLOSSARY, timeout=1.0)
        glossary_data = res[0] if res else []

        engines = []
        for item in (glossary_data or []):
            if item.get("installed", False) and item.get("id"):
                engines.append(str(item["id"]))

        desired = (select_engine or self.settings.get("RECOGNIZER_TYPE") or "").strip()

        self.recognizer_combobox.blockSignals(True)
        try:
            self.recognizer_combobox.clear()

            if engines:
                self.recognizer_combobox.setEnabled(True)
                self.recognizer_combobox.addItems(engines)

                idx = self.recognizer_combobox.findText(desired)
                if idx >= 0:
                    self.recognizer_combobox.setCurrentIndex(idx)
                else:
                    self.recognizer_combobox.setCurrentIndex(0)
                    self._save_setting("RECOGNIZER_TYPE", self.recognizer_combobox.currentText())
            else:
                self.recognizer_combobox.setEnabled(False)
                self.recognizer_combobox.addItem(_("Нет установленных моделей", "No installed models"))
        finally:
            self.recognizer_combobox.blockSignals(False)

        new_engine = ""
        try:
            new_engine = self.recognizer_combobox.currentText() if self.recognizer_combobox.isEnabled() else ""
        except Exception:
            new_engine = ""

        if new_engine != prev_engine:
            reset_init_status()

        apply_asr_install_status(new_engine if engines else "")

    def on_mic_changed(index):
        if index < 0:
            return
        full_name = self.mic_combobox.itemData(index, Qt.ItemDataRole.UserRole)
        self._save_setting("MIC_DEVICE", full_name)
        self.mic_combobox.setToolTip(full_name)
        on_mic_selected(self, full_name)

    def set_engine(engine: str):
        if not engine or not self.recognizer_combobox.isEnabled():
            return
        reset_init_status()
        self._save_setting("RECOGNIZER_TYPE", engine)
        apply_asr_install_status(engine)

    def on_active_toggled(state: int):
        self._save_setting("MIC_ACTIVE", bool(state))

    def on_instant_toggled(state: int):
        self._save_setting("MIC_INSTANT_SENT", bool(state))

    self.mic_combobox.currentIndexChanged.connect(on_mic_changed)
    self.mic_refresh_button.clicked.connect(populate_mics)

    self.recognizer_combobox.currentTextChanged.connect(set_engine)
    if hasattr(self, "asr_refresh_button") and self.asr_refresh_button:
        self.asr_refresh_button.clicked.connect(populate_engines)

    if hasattr(self, "asr_manage_button") and self.asr_manage_button:
        self.asr_manage_button.clicked.connect(
            lambda: bus.emit(Events.GUI.SHOW_WINDOW, {"window_id": "asr_glossary"})
        )

    self.mic_active_checkbox.stateChanged.connect(on_active_toggled)
    self.mic_instant_checkbox.stateChanged.connect(on_instant_toggled)

    # Авто-обновление списка установленных моделей после установки/ошибки
    try:
        if hasattr(self, "_on_asr_install_finished"):
            self.asr_install_finished_signal.disconnect(self._on_asr_install_finished)
    except Exception:
        pass
    try:
        if hasattr(self, "_on_asr_install_failed"):
            self.asr_install_failed_signal.disconnect(self._on_asr_install_failed)
    except Exception:
        pass

    def _on_asr_install_finished(_payload: dict):
        QTimer.singleShot(0, populate_engines)

    def _on_asr_install_failed(_payload: dict):
        QTimer.singleShot(0, populate_engines)

    if getattr(self, "asr_install_finished_signal", None):
        self._on_asr_install_finished = _on_asr_install_finished
        self.asr_install_finished_signal.connect(self._on_asr_install_finished)
    if getattr(self, "asr_install_failed_signal", None):
        self._on_asr_install_failed = _on_asr_install_failed
        self.asr_install_failed_signal.connect(self._on_asr_install_failed)

    populate_mics()
    populate_engines()
    QTimer.singleShot(400, populate_engines)


def on_mic_selected(gui, full_device_name=None):
    if not hasattr(gui, "mic_combobox"):
        return
    bus = get_event_bus()

    if full_device_name is None:
        idx = gui.mic_combobox.currentIndex()
        if idx >= 0:
            full_device_name = gui.mic_combobox.itemData(idx, Qt.ItemDataRole.UserRole)

    selection = full_device_name or ""
    if selection and "(" in selection:
        try:
            microphone_name = selection.rsplit(" (", 1)[0]
            m = re.search(r"\((\d+)\)\s*$", selection)
            if m:
                device_id = int(m.group(1))
                bus.emit(Events.Speech.SET_MICROPHONE, {"name": microphone_name, "device_id": device_id})
                if gui.settings.get("MIC_ACTIVE", False):
                    bus.emit(Events.Speech.RESTART_SPEECH_RECOGNITION, {"device_id": device_id})
        except Exception as e:
            logger.error(f"Ошибка выбора микрофона: {e}")


def load_mic_settings(gui):
    try:
        bus = get_event_bus()
        device_id = gui.settings.get("NM_MICROPHONE_ID", 0)
        device_name = gui.settings.get("NM_MICROPHONE_NAME", "")
        full = f"{device_name} ({device_id})"

        if hasattr(gui, "mic_combobox"):
            found = False
            for i in range(gui.mic_combobox.count()):
                if gui.mic_combobox.itemData(i, Qt.ItemDataRole.UserRole) == full:
                    gui.mic_combobox.setCurrentIndex(i)
                    gui.mic_combobox.setToolTip(full)
                    found = True
                    break
            if not found and gui.mic_combobox.count() > 0:
                gui.mic_combobox.setCurrentIndex(0)
                gui.mic_combobox.setToolTip(gui.mic_combobox.itemData(0, Qt.ItemDataRole.UserRole))

        bus.emit(Events.Speech.SET_MICROPHONE, {"name": device_name, "device_id": device_id})

        if gui.settings.get("MIC_ACTIVE", False) and hasattr(gui, "mic_active_checkbox"):
            gui.mic_active_checkbox.setChecked(True)

    except Exception as e:
        logger.error(f"Ошибка загрузки настроек микрофона: {e}")