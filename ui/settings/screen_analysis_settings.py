import tkinter as tk
import cv2
from utils import getTranslationVariant as _
import cv2
from tkinter import ttk
from Logger import logger

def get_camera_list(self):
    camera_list = []
    for i in range(5):  # Проверяем первые 10 камер
        cap = cv2.VideoCapture(i)
        if cap.isOpened():
            camera_list.append(f"Camera {i}")
            cap.release()
    return camera_list

def update_camera_list(self):
    self.camera_combobox.config(values=get_camera_list(self))

def on_camera_selected(self):
    selection = self.camera_combobox.get()
    if selection:
        camera_index = int(selection.split(" ")[-1])
        self.selected_camera = camera_index
        logger.info(f"Выбрана камера: {self.selected_camera}")


def setup_screen_analysis_controls(self, parent):
    """Creates a settings section for screen analysis."""
    screen_analysis_config = [
        {'label': _('Включить анализ экрана', 'Enable Screen Analysis'), 'key': 'ENABLE_SCREEN_ANALYSIS',
         'type': 'checkbutton',
         'default_checkbutton': False,
         'tooltip': _('Включает захват экрана и отправку кадров в модель для анализа.',
                      'Enables screen capture and sending frames to the model for analysis.')},
        {'label': _('Интервал захвата (сек)', 'Capture Interval (sec)'), 'key': 'SCREEN_CAPTURE_INTERVAL',
         'type': 'entry',
         'default': 5.0, 'validation': self.validate_float_positive,
         'tooltip': _('Интервал между захватом кадров в секундах (минимум 0.1).',
                      'Interval between frame captures in seconds (minimum 0.1).')},
        {'label': _('Сжатие (%)', 'Compression (%)'), 'key': 'SCREEN_CAPTURE_QUALITY', 'type': 'entry',
         'default': 25, 'validation': self.validate_positive_integer,
         'tooltip': _('Качество JPEG (0-100).', 'JPEG quality (0-100).')},
        {'label': _('Кадров в секунду', 'Frames per second'), 'key': 'SCREEN_CAPTURE_FPS', 'type': 'entry',
         'default': 1, 'validation': self.validate_positive_integer,
         'tooltip': _('Количество кадров в секунду (минимум 1).', 'Frames per second (minimum 1).')},
        {'label': _('Кол-во кадров в истории', 'Number of frames in history'),
         'key': 'SCREEN_CAPTURE_HISTORY_LIMIT', 'type': 'entry',
         'default': 1, 'validation': self.validate_positive_integer,
         'tooltip': _('Максимальное количество последних кадров для отправки в модель (минимум 1).',
                      'Maximum number of recent frames to send to the model (минимум 1).')},
        {'label': _('Кол-во кадров для передачи', 'Number of frames for transfer'),
         'key': 'SCREEN_CAPTURE_TRANSFER_LIMIT', 'type': 'entry',
         'default': 1, 'validation': self.validate_positive_integer,
         'tooltip': _('Максимальное количество кадров, передаваемых за один запрос (минимум 1).',
                      'Maximum number of frames transferred per request (minimum 1).')},
        {'label': _('Ширина захвата', 'Capture Width'), 'key': 'SCREEN_CAPTURE_WIDTH', 'type': 'entry',
         'default': 1024, 'validation': self.validate_positive_integer,
         'tooltip': _('Ширина захватываемого изображения в пикселях.', 'Width of the captured image in pixels.')},
        {'label': _('Высота захвата', 'Capture Height'), 'key': 'SCREEN_CAPTURE_HEIGHT', 'type': 'entry',
         'default': 768, 'validation': self.validate_positive_integer,
         'tooltip': _('Высота захватываемого изображения в пикселях.', 'Height of the captured image in pixels.')},
        {'label': _('Отправлять запросы с изображениями', 'Send Image Requests'), 'key': 'SEND_IMAGE_REQUESTS',
         'type': 'checkbutton',
         'default_checkbutton': False,
         'tooltip': _('Автоматически отправлять запросы с захваченными изображениями.',
                      'Automatically send requests with captured images.')},
        {'label': _('Период запросов (сек)', 'Image Request Interval (sec)'), 'key': 'IMAGE_REQUEST_INTERVAL',
         'type': 'entry',
         'default': 20.0, 'validation': self.validate_float_positive,
         'tooltip': _('Интервал между автоматической отправкой запросов с изображениями в секундах (минимум 1.0).',
                      'Interval between automatic sending of image requests in seconds (minimum 1.0).')},
        {'label': _('Исключить окно GUI из захвата', 'Exclude GUI Window from Capture'), 'key': 'EXCLUDE_GUI_WINDOW',
         'type': 'checkbutton',
         'default_checkbutton': False,
         'tooltip': _('Если включено, окно NeuroMita GUI будет исключено из захвата экрана.',
                      'If enabled, the NeuroMita GUI window will be excluded from capture.')},
        {'label': _('Заголовок исключаемого окна', 'Excluded Window Title'), 'key': 'EXCLUDE_WINDOW_TITLE',
         'type': 'entry',
         'default': '',
         'tooltip': _('Заголовок окна, которое нужно исключить из захвата (оставьте пустым для GUI).',
                      'Title of the window to exclude from capture (leave empty for GUI).')},
        {'label': _('Снижение качества изображений', 'Image Quality Reduction'), 'type': 'text'},
        {'label': _('Включить снижение качества', 'Enable Quality Reduction'), 'key': 'IMAGE_QUALITY_REDUCTION_ENABLED',
         'type': 'checkbutton', 'default_checkbutton': False,
         'tooltip': _('Включает динамическое снижение качества изображений в истории сообщений.',
                      'Enables dynamic image quality reduction in message history.')},
        {'label': _('Начальный индекс снижения', 'Reduction Start Index'), 'key': 'IMAGE_QUALITY_REDUCTION_START_INDEX',
         'type': 'entry', 'default': 25, 'validation': self.validate_positive_integer_or_zero,
         'tooltip': _('Индекс сообщения, с которого начинается снижение качества (0 = первое сообщение).',
                      'Message index from which quality reduction begins (0 = first message).')},
        {'label': _('Использовать процентное снижение', 'Use Percentage Reduction'),
         'key': 'IMAGE_QUALITY_REDUCTION_USE_PERCENTAGE',
         'type': 'checkbutton', 'default_checkbutton': False,
         'tooltip': _('Если включено, качество снижается на процент, иначе - до минимального значения.',
                      'If enabled, quality is reduced by a percentage, otherwise to a minimum value.')},
        {'label': _('Минимальное качество (%)', 'Minimum Quality (%)'), 'key': 'IMAGE_QUALITY_REDUCTION_MIN_QUALITY',
         'type': 'entry', 'default': 30, 'validation': self.validate_positive_integer_or_zero,
         'tooltip': _(
             'Минимальное качество JPEG (0-100), до которого может быть снижено изображение. 0 означает удаление изображения.',
             'Minimum JPEG quality (0-100) to which an image can be reduced. 0 means image deletion.')},
        {'label': _('Скорость снижения качества', 'Quality Decrease Rate'),
         'key': 'IMAGE_QUALITY_REDUCTION_DECREASE_RATE',
         'type': 'entry', 'default': 5, 'validation': self.validate_positive_integer,
         'tooltip': _('На сколько единиц снижается качество за каждое сообщение после начального индекса.',
                      'By how many units quality decreases for each message after the start index.')},
    ]
    self.create_settings_section(parent,
                                 _("Настройки анализа экрана", "Screen Analysis Settings"),
                                 screen_analysis_config)

    camera_analysis_config = [
        {'label': _('Включить захват с камеры', 'Enable Camera Capture'), 'key': 'ENABLE_CAMERA_CAPTURE',
         'type': 'checkbutton',
         'default_checkbutton': False,
         'tooltip': _('Включает захват с камеры и отправку кадров в модель для анализа.',
                      'Enables camera capture and sending frames to the model for analysis.')},
        {'label': _('Камера', 'Camera'), 'key': 'CAMERA_DEVICE',
                 'type': 'combobox',
                 'options': [_("Обновите","Update")],#get_camera_list(self),
                 'default': [_("Обновите","Update")],#get_camera_list(self)[0] if get_camera_list(self) else "",
                 'command': lambda: on_camera_selected(self),
                 'tooltip': _('Выберите камеру.', 'Select camera.'),
                 'widget_name': 'camera_combobox'},
                {'label': _("Обновить список", "Refresh list"),
                 'type': 'button',
                 'command': lambda: update_camera_list(self)
                },
        {'label': _('Интервал захвата (сек)', 'Capture Interval (sec)'), 'key': 'CAMERA_CAPTURE_INTERVAL',
         'type': 'entry',
         'default': 5.0, 'validation': self.validate_float_positive,
         'tooltip': _('Интервал между захватом кадров в секундах (минимум 0.1).',
                      'Interval between frame captures in seconds (minimum 0.1).')},
        {'label': _('Сжатие (%)', 'Compression (%)'), 'key': 'CAMERA_CAPTURE_QUALITY', 'type': 'entry',
         'default': 25, 'validation': self.validate_positive_integer,
         'tooltip': _('Качество JPEG (0-100).', 'JPEG quality (0-100).')},
        {'label': _('Кадров в секунду', 'Frames per second'), 'key': 'CAMERA_CAPTURE_FPS', 'type': 'entry',
         'default': 1, 'validation': self.validate_positive_integer,
         'tooltip': _('Количество кадров в секунду (минимум 1).', 'Frames per second (minimum 1).')},
        {'label': _('Кол-во кадров в истории', 'Number of frames in history'),
         'key': 'CAMERA_CAPTURE_HISTORY_LIMIT', 'type': 'entry',
         'default': 1, 'validation': self.validate_positive_integer,
         'tooltip': _('Максимальное количество последних кадров для отправки в модель (минимум 1).',
                      'Maximum number of recent frames to send to the model (минимум 1).')},
        {'label': _('Кол-во кадров для передачи', 'Number of frames for transfer'),
         'key': 'CAMERA_CAPTURE_TRANSFER_LIMIT', 'type': 'entry',
         'default': 1, 'validation': self.validate_positive_integer,
         'tooltip': _('Максимальное количество кадров, передаваемых за один запрос (минимум 1).',
                      'Maximum number of frames transferred per request (минимум 1).')},
        {'label': _('Ширина захвата', 'Capture Width'), 'key': 'CAMERA_CAPTURE_WIDTH', 'type': 'entry',
         'default': 640, 'validation': self.validate_positive_integer,
         'tooltip': _('Ширина захватываемого изображения в пикселях.', 'Width of the captured image in pixels.')},
        {'label': _('Высота захвата', 'Capture Height'), 'key': 'CAMERA_CAPTURE_HEIGHT', 'type': 'entry',
         'default': 480, 'validation': self.validate_positive_integer,
         'tooltip': _('Высота захватываемого изображения в пикселях.', 'Height of the captured image in pixels.')},
    ]
    self.camera_section = self.create_settings_section(parent,
                                 _("Настройки захвата с камеры", "Camera Capture Settings"),
                                 camera_analysis_config)

    # # Сохраняем ссылки на важные виджеты
    # for widget in self.camera_section.content_frame.winfo_children():
    #     if isinstance(widget, tk.Frame):
    #         for child in widget.winfo_children():
    #             if isinstance(child, ttk.Combobox) and 'CAMERA_DEVICE' in str(child):
    #                 self.camera_combobox = child


    # Сохраняем ссылку на combobox камеры
    for widget in self.camera_section.content_frame.winfo_children():
        if hasattr(widget, 'widget_name') and widget.widget_name == 'camera_combobox':
            for child in widget.winfo_children():
                if isinstance(child, ttk.Combobox):
                    self.camera_combobox = child
                    break