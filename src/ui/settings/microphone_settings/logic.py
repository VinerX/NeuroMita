import re
from PyQt6.QtCore import Qt
from utils import getTranslationVariant as _
from main_logger import logger
from core.events import get_event_bus, Events
from styles.main_styles import get_theme


def wire_microphone_settings_logic(self):
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

    def reset_init_status():
        if hasattr(self, "asr_init_status") and self.asr_init_status is not None:
            try:
                if hasattr(self, "asr_set_pill"):
                    self.asr_set_pill.emit({"label": self.asr_init_status, "text": "—", "kind": "info"})
                    return
            except Exception:
                pass
            try:
                set_pill({"label": self.asr_init_status, "text": "—", "kind": "info"})
            except Exception:
                pass

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
        bus.emit(Events.Speech.SET_MICROPHONE, {"name": device_name, "device_id": device_id})

        if gui.settings.get("MIC_ACTIVE", False) and hasattr(gui, "mic_active_checkbox"):
            gui.mic_active_checkbox.setChecked(True)

    except Exception as e:
        logger.error(f"Ошибка загрузки настроек микрофона: {e}")