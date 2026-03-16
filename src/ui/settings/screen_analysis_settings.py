from ui.gui_templates import create_settings_section, create_section_header
from utils import getTranslationVariant as _
from main_logger import logger

def get_camera_list():
    try:
        import cv2
        camera_list = []
        for i in range(5):
            cap = cv2.VideoCapture(i, cv2.CAP_DSHOW)
            if cap.isOpened():
                camera_list.append(f"Camera {i}")
                cap.release()
        return camera_list if camera_list else [_("Камер не найдено", "No cameras found")]
    except ImportError as ex:
        logger.warning('OpenCV не установлен: камеры не обнаружены.')
        return [_("Камер не найдено", "No cameras found")]

def update_camera_list(gui):
    if hasattr(gui, 'camera_combobox'):
        current_text = gui.camera_combobox.currentText()
        gui.camera_combobox.clear()
        new_list = get_camera_list()
        gui.camera_combobox.addItems(new_list)
        if current_text in new_list:
            gui.camera_combobox.setCurrentText(current_text)

def on_camera_selected(gui):
    if hasattr(gui, 'camera_combobox'):
        selection = gui.camera_combobox.currentText()
        if selection and "Camera" in selection:
            try:
                camera_index = int(selection.split(" ")[-1])
                gui.settings.set("CAMERA_INDEX", camera_index)
                logger.info(f"Выбрана камера: {camera_index}")
            except (IndexError, ValueError):
                logger.error(f"Не удалось извлечь индекс из '{selection}'")

def setup_screen_analysis_controls(gui, parent_layout):
    # ОДИН ОБЩИЙ ЗАГОЛОВОК для всех настроек экрана
    create_section_header(parent_layout, _("Настройки экрана", "Screen Settings"))
    
    # Первая CollapsibleSection
    screen_analysis_config = [
        {'label': _('Включить анализ экрана', 'Enable Screen Analysis'), 'key': 'ENABLE_SCREEN_ANALYSIS', 'type': 'checkbutton', 'default_checkbutton': False},
        {'label': _('Интервал захвата (сек)', 'Capture Interval (sec)'), 'key': 'SCREEN_CAPTURE_INTERVAL', 'type': 'entry', 'default': '5.0', 'validation': gui.validate_float_positive},
        {'label': _('Сжатие (%)', 'Compression (%)'), 'key': 'SCREEN_CAPTURE_QUALITY', 'type': 'entry', 'default': '25', 'validation': gui.validate_positive_integer},
        {'label': _('Кадров в секунду', 'Frames per second'), 'key': 'SCREEN_CAPTURE_FPS', 'type': 'entry', 'default': '1', 'validation': gui.validate_positive_integer},
        {'label': _('Кол-во кадров в истории', 'Frames in history'), 'key': 'SCREEN_CAPTURE_HISTORY_LIMIT', 'type': 'entry', 'default': '1', 'validation': gui.validate_positive_integer},
        {'label': _('Кол-во кадров для передачи', 'Frames for transfer'), 'key': 'SCREEN_CAPTURE_TRANSFER_LIMIT', 'type': 'entry', 'default': '1', 'validation': gui.validate_positive_integer},
        {'label': _('Ширина захвата', 'Capture Width'), 'key': 'SCREEN_CAPTURE_WIDTH', 'type': 'entry', 'default': '1024', 'validation': gui.validate_positive_integer},
        {'label': _('Высота захвата', 'Capture Height'), 'key': 'SCREEN_CAPTURE_HEIGHT', 'type': 'entry', 'default': '768', 'validation': gui.validate_positive_integer},
        {'label': _('Отправлять запросы с кадрами', 'Send Image Requests'), 'key': 'SEND_IMAGE_REQUESTS', 'type': 'checkbutton', 'default_checkbutton': False},
        {'label': _('Период запросов (сек)', 'Request Interval (sec)'), 'key': 'IMAGE_REQUEST_INTERVAL', 'type': 'entry', 'depends_on': "SEND_IMAGE_REQUESTS", 'default': '20.0', 'validation': gui.validate_float_positive},
        {'label': _('Исключить окно GUI', 'Exclude GUI Window'), 'key': 'EXCLUDE_GUI_WINDOW', 'type': 'checkbutton', 'default_checkbutton': False},
        {'label': _('Заголовок искл. окна', 'Excluded Window Title'), 'key': 'EXCLUDE_WINDOW_TITLE', 'type': 'entry', 'default': ''},
    ]
    create_settings_section(gui, parent_layout, _("Настройки анализа экрана", "Screen Analysis Settings"), screen_analysis_config)

    # Вторая CollapsibleSection
    camera_analysis_config = [
        {'label': _('Включить захват с камеры', 'Enable Camera Capture'), 'key': 'ENABLE_CAMERA_CAPTURE', 'type': 'checkbutton', 'default_checkbutton': False},
        {'label': _('Камера', 'Camera'), 'key': 'CAMERA_DEVICE', 'type': 'combobox', 'options': get_camera_list(), 'default': get_camera_list()[0], 'command': lambda _: on_camera_selected(gui), 'widget_name': 'camera_combobox'},
        {'label': _("Обновить список", "Refresh list"), 'type': 'button', 'command': lambda: update_camera_list(gui)},
        {'label': _('Интервал захвата (сек)', 'Capture Interval (sec)'), 'key': 'CAMERA_CAPTURE_INTERVAL', 'type': 'entry', 'default': '5.0', 'validation': gui.validate_float_positive},
        {'label': _('Сжатие (%)', 'Compression (%)'), 'key': 'CAMERA_CAPTURE_QUALITY', 'type': 'entry', 'default': '25', 'validation': gui.validate_positive_integer},
        {'label': _('Кадров в секунду', 'Frames per second'), 'key': 'CAMERA_CAPTURE_FPS', 'type': 'entry', 'default': '1', 'validation': gui.validate_positive_integer},
        {'label': _('Кол-во кадров в истории', 'Frames in history'), 'key': 'CAMERA_CAPTURE_HISTORY_LIMIT', 'type': 'entry', 'default': '1', 'validation': gui.validate_positive_integer},
        {'label': _('Кол-во кадров для передачи', 'Frames for transfer'), 'key': 'CAMERA_CAPTURE_TRANSFER_LIMIT', 'type': 'entry', 'default': '1', 'validation': gui.validate_positive_integer},
        {'label': _('Ширина захвата', 'Capture Width'), 'key': 'CAMERA_CAPTURE_WIDTH', 'type': 'entry', 'default': '640', 'validation': gui.validate_positive_integer},
        {'label': _('Высота захвата', 'Capture Height'), 'key': 'CAMERA_CAPTURE_HEIGHT', 'type': 'entry', 'default': '480', 'validation': gui.validate_positive_integer},
    ]
    gui.camera_section = create_settings_section(gui, parent_layout, _("Настройки захвата с камеры", "Camera Capture Settings"), camera_analysis_config)

    # Третья CollapsibleSection
    frame_compression_config = [
        {'label': _('Включить угасание кадров', 'Enable Frame Regression'), 'key': 'IMAGE_QUALITY_REDUCTION_ENABLED', 'type': 'checkbutton', 'default_checkbutton': False},
        {'label': _('Начальный индекс снижения', 'Reduction Start Index'), 'key': 'IMAGE_QUALITY_REDUCTION_START_INDEX', 'type': 'entry', 'default': '25', 'validation': gui.validate_positive_integer_or_zero},
        {'label': _('Исп. процентное снижение', 'Use Percentage Reduction'), 'key': 'IMAGE_QUALITY_REDUCTION_USE_PERCENTAGE', 'type': 'checkbutton', 'default_checkbutton': False},
        {'label': _('Минимальное качество (%)', 'Minimum Quality (%)'), 'key': 'IMAGE_QUALITY_REDUCTION_MIN_QUALITY', 'type': 'entry', 'default': '30', 'validation': gui.validate_positive_integer_or_zero},
        {'label': _('Скорость снижения', 'Decrease Rate'), 'key': 'IMAGE_QUALITY_REDUCTION_DECREASE_RATE', 'type': 'entry', 'default': '5', 'validation': gui.validate_positive_integer},
    ]
    create_settings_section(gui, parent_layout, _("Настройки угасания кадров", "Frame Regression Settings"), frame_compression_config)