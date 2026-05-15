from ui.gui_templates import create_settings_section, create_section_header
from utils import getTranslationVariant as _
from main_logger import logger
from core.events import get_event_bus, Events

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
        {'label': _('Разрешить обработку изображений', 'Enable Image Analysis'), 'key': 'ENABLE_IMAGE_ANALYSIS', 'type': 'checkbutton', 'default_checkbutton': True, 'hide': True},
        {'label': _('Включить захват экрана', 'Enable Screen Capture'), 'key': 'ENABLE_SCREEN_ANALYSIS', 'type': 'checkbutton', 'default_checkbutton': False},
        {'label': _('Прикладывать кадры к сообщениям', 'Auto-attach frames'), 'key': 'AUTO_ATTACH_IMAGES', 'type': 'checkbutton', 'default_checkbutton': False, 'depends_on': 'ENABLE_SCREEN_ANALYSIS'},
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

    # Четвёртая CollapsibleSection — описание изображений
    # Список пресетов для vision-провайдера (тот же паттерн, что у REACT_PROVIDER_L1)
    _vision_provider_names = [_('Текущий', 'Current')]
    try:
        _eb = get_event_bus()
        _presets_meta = _eb.emit_and_wait(Events.ApiPresets.GET_PRESET_LIST, timeout=1.0)
        if _presets_meta and _presets_meta[0]:
            for _p in _presets_meta[0].get('custom', []):
                _vision_provider_names.append(_p.name)
    except Exception as _e:
        logger.warning(f"[screen_analysis_settings] Не удалось загрузить список пресетов: {_e}")

    image_description_config = [
        {
            'label': _('Инлайн-описание (vision-модели)', 'Inline Description (vision models)'),
            'key': 'IMAGE_INLINE_DESCRIPTION',
            'type': 'checkbutton',
            'default_checkbutton': False,
            'tooltip': _(
                'Модель сама описывает изображение в начале ответа.\n'
                'Описание сохраняется в историю вместо тяжёлого base64 — история не раздувается.',
                'The model describes the image at the start of its reply.\n'
                'The description is stored in history instead of raw base64 — keeps history light.'
            ),
        },
        {
            'label': _('Non-native режим (не-vision модели)', 'Non-native mode (non-vision models)'),
            'key': 'IMAGE_DESCRIPTION_ENABLED',
            'type': 'checkbutton',
            'default_checkbutton': False,
            'tooltip': _(
                'Если основная модель не поддерживает изображения — сначала отдельный\n'
                'vision-провайдер опишет картинку, и описание подставится в текст.',
                'If the main model does not support vision, a separate vision provider\n'
                'describes the image first and the description is injected as text.'
            ),
        },
        {
            'label': _('Vision-провайдер', 'Vision provider'),
            'key': 'IMAGE_DESCRIPTION_PROVIDER',
            'type': 'combobox',
            'options': _vision_provider_names,
            'default': _('Текущий', 'Current'),
            'depends_on': 'IMAGE_DESCRIPTION_ENABLED',
            'tooltip': _(
                'Пресет с vision-моделью для описания изображений.\n'
                '"Текущий" = использовать активный пресет.',
                'Preset with a vision model used to describe images.\n'
                '"Current" = use the currently active preset.'
            ),
        },
        {
            'label': _('Детализация описания', 'Description detail'),
            'key': 'IMAGE_DESCRIPTION_DETAIL',
            'type': 'combobox',
            'options': [
                _('Краткое', 'brief'),
                _('Нормальное', 'normal'),
                _('Подробное', 'detailed'),
            ],
            'default': _('Нормальное', 'normal'),
            'tooltip': _(
                'Влияет на оба режима (инлайн и non-native).\n'
                'Краткое — 1 предложение, только главное.\n'
                'Нормальное — 2-3 предложения, основные объекты и контекст.\n'
                'Подробное — 4-6 предложений: все объекты, цвета, текст, эмоции, атмосфера.',
                'Applies to both modes (inline and non-native).\n'
                'Brief — 1 sentence, key subject only.\n'
                'Normal — 2-3 sentences, main elements and context.\n'
                'Detailed — 4-6 sentences: all objects, colors, text, expressions, mood.'
            ),
        },
    ]
    create_settings_section(gui, parent_layout, _("Описание изображений", "Image Description"), image_description_config)
    # Detail depends on EITHER inline OR non-native mode being on (both use it)
    _wire_detail_dependency(gui)

    # Пятая CollapsibleSection — хранение и очистка изображений
    _setup_image_cleanup_section(gui, parent_layout)


def _wire_detail_dependency(gui) -> None:
    """
    Enable IMAGE_DESCRIPTION_DETAIL when either IMAGE_INLINE_DESCRIPTION
    or IMAGE_DESCRIPTION_ENABLED is checked.

    Both modes use the same detail level setting, so the combobox should be
    available whenever at least one description mode is active.
    """
    from PyQt6.QtWidgets import QLabel

    detail_w     = getattr(gui, 'IMAGE_DESCRIPTION_DETAIL', None)
    detail_frame = getattr(gui, 'IMAGE_DESCRIPTION_DETAIL_frame', None)
    inline_chk   = getattr(gui, 'IMAGE_INLINE_DESCRIPTION', None)
    native_chk   = getattr(gui, 'IMAGE_DESCRIPTION_ENABLED', None)

    if not detail_w:
        return

    def _sync(_=None):
        active = (
            (inline_chk  is not None and inline_chk.isChecked()) or
            (native_chk  is not None and native_chk.isChecked())
        )
        detail_w.setEnabled(active)
        if detail_frame:
            for child in detail_frame.findChildren(QLabel):
                child.setEnabled(active)

    _sync()  # apply current state immediately
    if inline_chk:
        inline_chk.stateChanged.connect(_sync)
    if native_chk:
        native_chk.stateChanged.connect(_sync)


def _run_orphan_scan(label_widget=None) -> None:
    try:
        from utils.image_cleanup import scan_orphaned_images, format_bytes
        orphans, total_bytes = scan_orphaned_images()
        msg = _(
            f"Найдено осиротевших файлов: {len(orphans)} ({format_bytes(total_bytes)})",
            f"Orphaned files found: {len(orphans)} ({format_bytes(total_bytes)})"
        )
        logger.info(f"[image_cleanup] {msg}")
        if label_widget is not None:
            label_widget.setText(msg)
            label_widget.show()
    except Exception as e:
        logger.error(f"[image_cleanup] Scan failed: {e}", exc_info=True)
        if label_widget is not None:
            label_widget.setText(_("Ошибка при сканировании", "Scan error"))
            label_widget.show()


def _run_orphan_delete(label_widget=None) -> None:
    try:
        from utils.image_cleanup import delete_orphaned_images, format_bytes
        count, freed = delete_orphaned_images(dry_run=False)
        msg = _(
            f"Удалено: {count} файлов, освобождено {format_bytes(freed)}",
            f"Deleted: {count} files, freed {format_bytes(freed)}"
        )
        logger.info(f"[image_cleanup] {msg}")
        if label_widget is not None:
            label_widget.setText(msg)
            label_widget.show()
    except Exception as e:
        logger.error(f"[image_cleanup] Delete failed: {e}", exc_info=True)
        if label_widget is not None:
            label_widget.setText(_("Ошибка при удалении", "Delete error"))
            label_widget.show()


def _show_image_stats(label_widget=None) -> None:
    try:
        from utils.image_cleanup import get_image_stats, format_bytes
        stats = get_image_stats()
        lines = [_(
            f"Всего: {stats.total_files} файлов ({format_bytes(stats.total_bytes)})",
            f"Total: {stats.total_files} files ({format_bytes(stats.total_bytes)})"
        )]
        for char, cs in sorted(stats.by_character.items()):
            lines.append(f"  {char}: {cs.files} ({format_bytes(cs.bytes)})")
        msg = "\n".join(lines)
        if label_widget is not None:
            label_widget.setText(msg)
            label_widget.show()
        logger.info(f"[image_cleanup] Stats:\n{msg}")
    except Exception as e:
        logger.error(f"[image_cleanup] Stats failed: {e}", exc_info=True)
        if label_widget is not None:
            label_widget.setText(_("Ошибка при подсчёте", "Stats error"))
            label_widget.show()


def _setup_image_cleanup_section(gui, parent_layout) -> None:
    from PyQt6.QtWidgets import QLabel
    from PyQt6.QtCore import Qt

    result_label = QLabel()
    result_label.setWordWrap(True)
    result_label.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft)
    result_label.hide()  # shown only after a button is pressed

    cleanup_config = [
        {
            'label': _('Подсчитать файлы', 'Count files'),
            'type': 'button',
            'command': lambda: _show_image_stats(result_label),
            'tooltip': _(
                'Показывает количество и вес сохранённых изображений по персонажам.',
                'Shows count and size of stored images per character.'
            ),
        },
        {
            'label': _('Найти осиротевшие файлы', 'Find orphaned files'),
            'type': 'button',
            'command': lambda: _run_orphan_scan(result_label),
            'tooltip': _(
                'Ищет файлы изображений, которые не упоминаются ни в одном сообщении истории.',
                'Finds image files not referenced by any history message.'
            ),
        },
        {
            'label': _('Удалить осиротевшие файлы', 'Delete orphaned files'),
            'type': 'button',
            'command': lambda: _run_orphan_delete(result_label),
            'tooltip': _(
                'Удаляет файлы изображений, не упоминаемые в истории. Действие необратимо.',
                'Deletes image files not referenced in history. Irreversible.'
            ),
        },
        {
            'label': _('Включить авто-очистку', 'Enable auto-cleanup'),
            'key': 'IMAGE_CLEANUP_TTL_ENABLED',
            'type': 'checkbutton',
            'default_checkbutton': False,
            'tooltip': _(
                'При каждом запуске удаляет изображения старше заданного числа дней.',
                'On each start, removes images older than the specified number of days.'
            ),
        },
        {
            'label': _('Хранить изображения (дней)', 'Keep images for (days)'),
            'key': 'IMAGE_CLEANUP_TTL_DAYS',
            'type': 'entry',
            'default': '30',
            'depends_on': 'IMAGE_CLEANUP_TTL_ENABLED',
            'validation': gui.validate_positive_integer,
        },
        {
            'label': _('Макс. файлов на персонажа', 'Max files per character'),
            'key': 'IMAGE_CLEANUP_MAX_PER_CHAR',
            'type': 'entry',
            'default': '500',
            'depends_on': 'IMAGE_CLEANUP_TTL_ENABLED',
            'validation': gui.validate_positive_integer,
        },
    ]
    section = create_settings_section(
        gui, parent_layout,
        _("Хранение и очистка изображений", "Image Storage & Cleanup"),
        cleanup_config
    )
    # Вставляем label с результатом прямо под секцией
    parent_layout.addWidget(result_label)
