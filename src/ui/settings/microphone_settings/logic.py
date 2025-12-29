# src/ui/settings/microphone_settings/logic.py
import re
from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtGui import QFontMetrics
from PyQt6.QtWidgets import (
    QWidget, QHBoxLayout, QVBoxLayout, QLabel, QComboBox,
    QSizePolicy, QLineEdit, QCheckBox
)

from utils import getTranslationVariant as _
from main_logger import logger
from core.events import get_event_bus, Events
from styles.main_styles import get_theme
from .ui import make_row


def wire_microphone_settings_logic(self):
    """
    UI-only: подключаем обработчики виджетов и реагируем на Qt-сигналы.
    Никаких подписок на EventBus тут не делаем.
    """
    bus = get_event_bus()
    theme = get_theme()

    def set_pill_called(lbl: QLabel, text: str, kind: str = "info"):
        self.asr_set_pill.emit({
            "label": lbl,
            "text": text,
            "kind": kind
        })

    def set_pill(data):
        lbl: QLabel = data["label"]
        text: str = data["text"]
        kind: str = data["kind"]

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

        lbl.setText(text)
        lbl.setStyleSheet(
            f"QLabel {{ padding: 2px 6px; border-radius: 8px; "
            f"font-weight: 600; font-size: 11px; color: {fg}; background: {bg}; border: 1px solid {br}; }}"
        )

    self.asr_set_pill.connect(set_pill)
    set_pill_called(self.asr_status_label, "—", "info")
    set_pill_called(self.asr_init_status, "—", "info")

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

            current_full = self.settings.get('MIC_DEVICE', mic_list[0] if mic_list else "")
            for i in range(self.mic_combobox.count()):
                if self.mic_combobox.itemData(i, Qt.ItemDataRole.UserRole) == current_full:
                    self.mic_combobox.setCurrentIndex(i)
                    break
            self.mic_combobox.setToolTip(current_full)
        finally:
            self.mic_combobox.blockSignals(False)

    def populate_engines():
        res = bus.emit_and_wait(Events.Speech.GET_ASR_MODELS_GLOSSARY, timeout=1.0)
        glossary_data = res[0] if res else []
        
        engines = [
            item["id"] for item in glossary_data 
            if item.get("installed", False)
        ]
        
        self.recognizer_combobox.blockSignals(True)
        try:
            self.recognizer_combobox.clear()
            self.recognizer_combobox.addItems(engines)
            
            current_engine = self.settings.get('RECOGNIZER_TYPE', 'google')
            
            index = self.recognizer_combobox.findText(current_engine)
            if index >= 0:
                self.recognizer_combobox.setCurrentIndex(index)
            else:
                if self.recognizer_combobox.count() > 0:
                    self.recognizer_combobox.setCurrentIndex(0)
                    new_default = self.recognizer_combobox.currentText()
                    self._save_setting('RECOGNIZER_TYPE', new_default)
                    
                    rebuild_model_settings(new_default)
        finally:
            self.recognizer_combobox.blockSignals(False)

    def on_mic_changed(index):
        if index < 0:
            return
        full_name = self.mic_combobox.itemData(index, Qt.ItemDataRole.UserRole)
        self._save_setting('MIC_DEVICE', full_name)
        self.mic_combobox.setToolTip(full_name)
        on_mic_selected(self, full_name)

    self.mic_combobox.currentIndexChanged.connect(on_mic_changed)
    self.mic_refresh_button.clicked.connect(populate_mics)
    if hasattr(self, "asr_manage_button") and self.asr_manage_button:
        self.asr_manage_button.clicked.connect(
            lambda: bus.emit(Events.GUI.SHOW_WINDOW, {"window_id": "asr_glossary"})
        )

    def clear_layout(lay: QVBoxLayout):
        while lay.count():
            item = lay.takeAt(0)
            w = item.widget()
            if w:
                w.deleteLater()

    def rebuild_model_settings(engine: str):
        clear_layout(self.model_settings_layout)

        schema_res = bus.emit_and_wait(Events.Speech.GET_RECOGNIZER_SETTINGS_SCHEMA, {'engine': engine}, timeout=1.0)
        schema = schema_res[0] if schema_res else []

        vals_res = bus.emit_and_wait(Events.Speech.GET_RECOGNIZER_SETTINGS, {'engine': engine}, timeout=1.0)
        values = vals_res[0] if vals_res else {}

        for field in schema:
            key = field.get("key")
            label_ru = field.get("label_ru", key)
            label_en = field.get("label_en", key)
            label_txt = _(label_ru, label_en)
            ftype = field.get("type", "entry")

            field_widget = QWidget()
            fw_h = QHBoxLayout(field_widget)
            fw_h.setContentsMargins(0, 0, 0, 0)
            fw_h.setSpacing(6)

            if ftype == "combobox":
                cb = QComboBox()
                cb.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
                cb.setMaximumWidth(150)
                for opt in field.get("options", []):
                    cb.addItem(str(opt))
                current = str(values.get(key, field.get("default", "")))
                if current:
                    idx = cb.findText(current, Qt.MatchFlag.MatchFixedString)
                    if idx >= 0:
                        cb.setCurrentIndex(idx)
                    else:
                        cb.setCurrentText(current)
                cb.currentTextChanged.connect(
                    lambda v, e=engine, k=key: bus.emit(
                        Events.Speech.SET_RECOGNIZER_OPTION, {'engine': e, 'key': k, 'value': v}
                    )
                )
                fw_h.addWidget(cb, 1)

            elif ftype == "check":
                chk = QCheckBox("")
                chk.setChecked(bool(values.get(key, field.get("default", False))))
                chk.toggled.connect(
                    lambda state, e=engine, k=key: bus.emit(
                        Events.Speech.SET_RECOGNIZER_OPTION, {'engine': e, 'key': k, 'value': bool(state)}
                    )
                )
                fw_h.addWidget(chk, 0, Qt.AlignmentFlag.AlignLeft)

            else:
                edit = QLineEdit()
                edit.setText(str(values.get(key, field.get("default", ""))))
                edit.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)

                def on_edit_finished(e=engine, k=key, w=edit):
                    bus.emit(Events.Speech.SET_RECOGNIZER_OPTION, {'engine': e, 'key': k, 'value': w.text().strip()})

                edit.editingFinished.connect(on_edit_finished)
                fw_h.addWidget(edit, 1)

            self.model_settings_layout.addWidget(make_row(label_txt, field_widget, self.mic_label_width))

    def _default_install_text():
        return _("Установить модель распознавания", "Install ASR model")

    def apply_asr_install_status(engine: str):
        res = bus.emit_and_wait(Events.Speech.CHECK_ASR_MODEL_INSTALLED, {'model': engine}, timeout=1.0)
        installed = bool(res and res[0])

        if installed:
            set_pill_called(self.asr_status_label, _('Установлено', 'Installed'), "ok")
            self.mic_active_checkbox.setEnabled(True)
        else:
            # Этот кейс редкий (если удалили файлы при запущенном приложении)
            set_pill_called(self.asr_status_label, _('Повреждено', 'Corrupted'), "warn")
            self.mic_active_checkbox.setChecked(False)
            self.mic_active_checkbox.setEnabled(False)

    def set_engine(engine: str):
        if not engine: return
        self._save_setting('RECOGNIZER_TYPE', engine)
        rebuild_model_settings(engine)
        apply_asr_install_status(engine)

    self.recognizer_combobox.currentTextChanged.connect(set_engine)

    self._asr_installing_engine = None

    try:
        if hasattr(self, "_on_asr_install_progress"):
            self.asr_install_progress_signal.disconnect(self._on_asr_install_progress)
    except Exception:
        pass
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

    def on_active_toggled(state: int):
        self._save_setting('MIC_ACTIVE', bool(state))

    def on_instant_toggled(state: int):
        self._save_setting('MIC_INSTANT_SENT', bool(state))

    self.mic_active_checkbox.stateChanged.connect(on_active_toggled)
    self.mic_instant_checkbox.stateChanged.connect(on_instant_toggled)

    def refresh_engine_ui():
        eng = self.recognizer_combobox.currentText()
        if eng:
            rebuild_model_settings(eng)
            apply_asr_install_status(eng)

    populate_mics()
    populate_engines()
    refresh_engine_ui()
    QTimer.singleShot(400, refresh_engine_ui)


def on_mic_selected(gui, full_device_name=None):
    if not hasattr(gui, 'mic_combobox'):
        return
    bus = get_event_bus()

    if full_device_name is None:
        idx = gui.mic_combobox.currentIndex()
        if idx >= 0:
            full_device_name = gui.mic_combobox.itemData(idx, Qt.ItemDataRole.UserRole)

    selection = full_device_name or ""
    if selection and '(' in selection:
        try:
            microphone_name = selection.rsplit(" (", 1)[0]
            m = re.search(r'\((\d+)\)\s*$', selection)
            if m:
                device_id = int(m.group(1))
                bus.emit(Events.Speech.SET_MICROPHONE, {'name': microphone_name, 'device_id': device_id})
                if gui.settings.get("MIC_ACTIVE", False):
                    bus.emit(Events.Speech.RESTART_SPEECH_RECOGNITION, {'device_id': device_id})
        except Exception as e:
            logger.error(f"Ошибка выбора микрофона: {e}")


def load_mic_settings(gui):
    try:
        bus = get_event_bus()
        device_id = gui.settings.get("NM_MICROPHONE_ID", 0)
        device_name = gui.settings.get("NM_MICROPHONE_NAME", "")
        full = f"{device_name} ({device_id})"

        if hasattr(gui, 'mic_combobox'):
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

        bus.emit(Events.Speech.SET_MICROPHONE, {'name': device_name, 'device_id': device_id})

        if gui.settings.get("MIC_ACTIVE", False) and hasattr(gui, 'mic_active_checkbox'):
            gui.mic_active_checkbox.setChecked(True)

    except Exception as e:
        logger.error(f"Ошибка загрузки настроек микрофона: {e}")