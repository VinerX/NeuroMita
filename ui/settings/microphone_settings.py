import base64
import json
import tkinter as tk
from tkinter import ttk

import guiTemplates
from Logger import logger
from SpeechRecognition import SpeechRecognition
from utils import getTranslationVariant as _
import sounddevice as sd


def setup_microphone_controls(self, parent):

    logger.warning(f"Recognition {self.settings.get('RECOGNIZER_TYPE')}")

    # Конфигурация настроек микрофона
    mic_settings = [
        {
            'label': _("Микрофон", "Microphone"),
            'type': 'combobox',
            'key': 'MIC_DEVICE',
            'options': get_microphone_list(self),
            'default': get_microphone_list(self)[0] if get_microphone_list(self) else "",
            'command': lambda: on_mic_selected(self),
            'widget_attrs': {
                'width': 30
            }
        },
        {
            'label': _("Тип распознавания", "Recognition Type"),
            'type': 'combobox',
            'key': 'RECOGNIZER_TYPE',
            'options': ["google", "vosk", "gigaam"],
            'default': "google",
            'tooltip': _("Выберите движок распознавания речи",
                         "Select speech recognition engine"),
            'widget_name':"RECOGNIZER_TYPE",
            # 'command': self.update_vosk_model_visibility
        },
        # {
        #     'label': _("Модель Vosk", "Vosk Model"),
        #     'type': 'combobox',
        #     'key': 'VOSK_MODEL',
        #     'options': ["vosk-model-ru-0.10"],
        #     'default': "vosk-model-ru-0.10",
        #     'tooltip': _("Выберите модель Vosk.", "Select Vosk model."),
        #     'widget_attrs': {
        #         'width': 30
        #     },
        #     'hide': True,
        #     'condition_key': 'RECOGNIZER_TYPE',
        #     'condition_value': 'vosk'
        # },
        {
            'label': _("Порог тишины (VAD)", "Silence Threshold (VAD)"),
            'type': 'entry',
            'key': 'SILENCE_THRESHOLD',
            'default': 0.01,
            'validation': self.validate_float_positive,
            'tooltip': _("Порог громкости для определения начала/конца речи (VAD).",
                         "Volume threshold for Voice Activity Detection (VAD).")
        },
        {
            'label': _("Длительность тишины (VAD, сек)", "Silence Duration (VAD, sec)"),
            'type': 'entry',
            'key': 'SILENCE_DURATION',
            'default': 0.5,
            'validation': self.validate_float_positive,
            'tooltip': _("Длительность тишины для определения конца фразы (VAD).",
                         "Duration of silence to detect end of phrase (VAD).")
        },
        {
            'label': _("Интервал обработки Vosk (сек)", "Vosk Process Interval (sec)"),
            'type': 'entry',
            'key': 'VOSK_PROCESS_INTERVAL',
            'default': 0.1,
            'validation': self.validate_float_positive,
            'tooltip': _("Интервал, с которым Vosk обрабатывает аудио в режиме реального времени.",
                         "Interval at which Vosk processes audio in live recognition mode.")
        },
        {
            'label': _("Распознавание", "Recognition"),
            'type': 'checkbutton',
            'key': 'MIC_ACTIVE',
            'default_checkbutton': False,
            'tooltip': _("Включить/выключить распознавание голоса", "Toggle voice recognition")
        },
        {
            'label': _("Мгновенная отправка", "Immediate sending"),
            'type': 'checkbutton',
            'key': 'MIC_INSTANT_SENT',
            'default_checkbutton': False,
            'tooltip': _("Отправлять сообщение сразу после распознавания",
                         "Send message immediately after recognition")
        },
        {
            'label': _("Обновить список", "Refresh list"),
            'type': 'button',
            'command': lambda: update_mic_list(self)
        }
    ]

    # Создаем секцию
    self.mic_section = self.create_settings_section(
        parent,
        _("Настройки микрофона", "Microphone Settings"),
        mic_settings
    )

    # Сохраняем ссылки на важные виджеты
    for widget in self.mic_section.content_frame.winfo_children():
        if isinstance(widget, tk.Frame):
            for child in widget.winfo_children():
                if isinstance(child, tk.Checkbutton):
                    if 'MIC_ACTIVE' in str(widget):
                        self.mic_active_check = child
                elif isinstance(child, ttk.Combobox) and 'VOSK_MODEL' in str(widget):
                    self.vosk_model_combobox = child

    self.mic_combobox = guiTemplates.find_widget_child_by_type(self.mic_section,"MIC_DEVICE",ttk.Combobox)

# Region MicFunctions

def get_microphone_list(self):
    try:
        devices = sd.query_devices()
        input_devices = [
            f"{d['name']} ({i})"
            for i, d in enumerate(devices)
            if d['max_input_channels'] > 0
        ]
        return input_devices
    except Exception as e:
        logger.info(f"Ошибка получения списка микрофонов: {e}")
        return []


def update_vosk_model_visibility(self, value):
    """Показывает/скрывает настройки Vosk в зависимости от выбранного типа."""
    show_vosk = value == "vosk"
    for widget in self.mic_section.content_frame.winfo_children():
        for child in widget.winfo_children():
            if hasattr(child, 'setting_key') and child.setting_key == 'VOSK_MODEL':
                if show_vosk:
                    widget.pack(fill=tk.X, pady=2)
                else:
                    widget.pack_forget()


def on_mic_selected(self):
    selection = self.mic_combobox.get()
    if selection:
        self.selected_microphone = selection.split(" (")[0]
        device_id = int(selection.split(" (")[-1].replace(")", ""))
        self.device_id = device_id
        logger.info(f"Выбран микрофон: {self.selected_microphone} (ID: {device_id})")
        save_mic_settings(self,device_id)


def update_mic_list(self):
    self.mic_combobox['values'] = get_microphone_list(self)


def save_mic_settings(self, device_id):
    try:
        with open(self.config_path, "rb") as f:
            encoded = f.read()
        decoded = base64.b64decode(encoded)
        settings = json.loads(decoded.decode("utf-8"))
    except FileNotFoundError:
        settings = {}

    settings["NM_MICROPHONE_ID"] = device_id
    settings["NM_MICROPHONE_NAME"] = self.selected_microphone

    json_data = json.dumps(settings, ensure_ascii=False)
    encoded = base64.b64encode(json_data.encode("utf-8"))
    with open(self.config_path, "wb") as f:
        f.write(encoded)


def load_mic_settings(self):
    try:
        with open(self.config_path, "rb") as f:
            encoded = f.read()
        decoded = base64.b64decode(encoded)
        settings = json.loads(decoded.decode("utf-8"))

        device_id = settings.get("NM_MICROPHONE_ID", 0)
        device_name = settings.get("NM_MICROPHONE_NAME", "")

        devices = sd.query_devices()
        if device_id < len(devices):
            self.selected_microphone = device_name
            self.device_id = device_id
            self.mic_combobox.set(f"{device_name} ({device_id})")
            logger.info(f"Загружен микрофон: {device_name} (ID: {device_id})")

    except Exception as e:
        logger.info(f"Ошибка загрузки настроек микрофона: {e}")

# endregion
