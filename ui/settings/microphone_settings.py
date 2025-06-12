import base64
import json
import tkinter as tk
from tkinter import ttk

from Logger import logger
from SpeechRecognition import SpeechRecognition
from utils import getTranslationVariant as _


def setup_microphone_controls(self, parent):
    # Конфигурация настроек микрофона
    mic_settings = [
        {
            'label': _("Микрофон", "Microphone"),
            'type': 'combobox',
            'key': 'MIC_DEVICE',
            'options': self.get_microphone_list(),
            'default': self.get_microphone_list()[0] if self.get_microphone_list() else "",
            'command': self.on_mic_selected,
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
            'command': lambda value: SpeechRecognition.set_recognizer_type(value),
            'tooltip': _("Выберите движок распознавания речи",
                         "Select speech recognition engine"),
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
            'command': self.update_mic_list
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
                if isinstance(child, ttk.Combobox):
                    self.mic_combobox = child
                elif isinstance(child, tk.Checkbutton):
                    if 'MIC_ACTIVE' in str(widget):
                        self.mic_active_check = child
                elif isinstance(child, ttk.Combobox) and 'VOSK_MODEL' in str(widget):
                    self.vosk_model_combobox = child


