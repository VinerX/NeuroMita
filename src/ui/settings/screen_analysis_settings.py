from ui.gui_templates import create_settings_section
from ui.settings.runtime_options import (
    refresh_camera_options,
    register_camera_options,
    register_provider_options,
    select_camera_option,
)
from main_logger import logger
from utils import getTranslationVariant as _

def update_camera_list(gui, *, force: bool = False):
    if force:
        refresh_camera_options(gui)
    else:
        register_camera_options(gui)

def on_camera_selected(gui):
    if hasattr(gui, 'camera_combobox'):
        select_camera_option(gui, gui.camera_combobox.currentText())

def setup_screen_analysis_controls(gui, parent_layout, *, runtime_options_view_model):
    from ui.settings.runtime_options import attach_runtime_options_view_model

    attach_runtime_options_view_model(gui, runtime_options_view_model)
    # No group header here: the page already carries the "Изображения и камера"
    # title, so a separate "Настройки экрана" heading just duplicated it.

    # Первая CollapsibleSection
    screen_analysis_config = [
        {
            'label': _('Настройки регулярного захвата и отправки кадров экрана модели.',
                       'Configure periodic screen capture and sending frames to the model.'),
            'type': 'text',
        },
        {'label': _('Разрешить обработку изображений', 'Enable Image Analysis'), 'key': 'ENABLE_IMAGE_ANALYSIS', 'type': 'checkbutton', 'default_checkbutton': True, 'hide': True},
        {'label': _('Прикладывать скриншот к каждому сообщению', 'Attach a screenshot to every message'), 'key': 'AUTO_ATTACH_IMAGES', 'type': 'checkbutton', 'default_checkbutton': False,
         'tooltip': _(
             'При каждой отправке сообщения делает свежий снимок экрана и прикладывает его к запросу — модель видит, что сейчас на экране.\n'
             'Работает и без «Включить захват экрана»: если непрерывный захват выключен, берётся одиночный снимок в момент отправки.\n'
             'Требует включённой «Разрешить обработку изображений» и vision-модели.',
             'On every message send, takes a fresh screenshot and attaches it to the request — the model sees what is on screen right now.\n'
             'Works without "Enable Screen Capture": if continuous capture is off, a single snapshot is taken at send time.\n'
             'Requires "Enable Image Analysis" and a vision-capable model.'
         )},
        {'label': _('Включить захват экрана (фоновый)', 'Enable Screen Capture (background)'), 'key': 'ENABLE_SCREEN_ANALYSIS', 'type': 'checkbutton', 'default_checkbutton': False,
         'tooltip': _(
             'Непрерывный фоновый захват: отдельный поток снимает экран каждые N секунд в буфер кадров.\n'
             'Нужен НЕ для обычного прикрепления (для него хватает галки выше), а для:\n'
             '• периодической отправки кадров Мите по таймеру («Отправлять запросы с кадрами»);\n'
             '• прикрепления нескольких последних кадров сразу (история кадров).\n'
             'Если нужно просто «Мита видит мой экран, когда я пишу» — это можно НЕ включать.',
             'Continuous background capture: a separate thread grabs the screen every N seconds into a frame buffer.\n'
             'NOT needed for normal attachment (the checkbox above is enough), but for:\n'
             '• sending frames to Mita periodically on a timer ("Send Image Requests");\n'
             '• attaching several recent frames at once (frame history).\n'
             'If you just want "Mita sees my screen when I type" — you can leave this off.'
         )},
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
    create_settings_section(gui, parent_layout, _("Настройки анализа экрана", "Screen Analysis Settings"), screen_analysis_config, icon_name="fa6s.display")

    # Вторая CollapsibleSection
    camera_analysis_config = [
        {
            'label': _('Настройки захвата изображения с веб-камеры для отправки модели.',
                       'Configure webcam capture for sending frames to the model.'),
            'type': 'text',
        },
        {'label': _('Включить захват с камеры', 'Enable Camera Capture'), 'key': 'ENABLE_CAMERA_CAPTURE', 'type': 'checkbutton', 'default_checkbutton': False},
        {'label': _('Камера', 'Camera'), 'key': 'CAMERA_DEVICE', 'type': 'combobox',
         'options': [_("Загрузка камер...", "Loading cameras...")],
         'default': _("Загрузка камер...", "Loading cameras..."),
         'command': lambda _: on_camera_selected(gui), 'widget_name': 'camera_combobox'},
        {'label': _("Обновить список", "Refresh list"), 'type': 'button', 'command': lambda: update_camera_list(gui, force=True)},
        {'label': _('Интервал захвата (сек)', 'Capture Interval (sec)'), 'key': 'CAMERA_CAPTURE_INTERVAL', 'type': 'entry', 'default': '5.0', 'validation': gui.validate_float_positive},
        {'label': _('Сжатие (%)', 'Compression (%)'), 'key': 'CAMERA_CAPTURE_QUALITY', 'type': 'entry', 'default': '25', 'validation': gui.validate_positive_integer},
        {'label': _('Кадров в секунду', 'Frames per second'), 'key': 'CAMERA_CAPTURE_FPS', 'type': 'entry', 'default': '1', 'validation': gui.validate_positive_integer},
        {'label': _('Кол-во кадров в истории', 'Frames in history'), 'key': 'CAMERA_CAPTURE_HISTORY_LIMIT', 'type': 'entry', 'default': '1', 'validation': gui.validate_positive_integer},
        {'label': _('Кол-во кадров для передачи', 'Frames for transfer'), 'key': 'CAMERA_CAPTURE_TRANSFER_LIMIT', 'type': 'entry', 'default': '1', 'validation': gui.validate_positive_integer},
        {'label': _('Ширина захвата', 'Capture Width'), 'key': 'CAMERA_CAPTURE_WIDTH', 'type': 'entry', 'default': '640', 'validation': gui.validate_positive_integer},
        {'label': _('Высота захвата', 'Capture Height'), 'key': 'CAMERA_CAPTURE_HEIGHT', 'type': 'entry', 'default': '480', 'validation': gui.validate_positive_integer},
    ]
    gui.camera_section = create_settings_section(gui, parent_layout, _("Настройки захвата с камеры", "Camera Capture Settings"), camera_analysis_config, icon_name="fa6s.camera")
    update_camera_list(gui)

    # Третья CollapsibleSection
    frame_compression_config = [
        {
            'label': _('Постепенное снижение качества старых кадров для экономии трафика.',
                       'Gradually reduces the quality of older frames to save bandwidth.'),
            'type': 'text',
        },
        {'label': _('Включить угасание кадров', 'Enable Frame Regression'), 'key': 'IMAGE_QUALITY_REDUCTION_ENABLED', 'type': 'checkbutton', 'default_checkbutton': False},
        {'label': _('Начальный индекс снижения', 'Reduction Start Index'), 'key': 'IMAGE_QUALITY_REDUCTION_START_INDEX', 'type': 'entry', 'default': '25', 'validation': gui.validate_positive_integer_or_zero},
        {'label': _('Исп. процентное снижение', 'Use Percentage Reduction'), 'key': 'IMAGE_QUALITY_REDUCTION_USE_PERCENTAGE', 'type': 'checkbutton', 'default_checkbutton': False},
        {'label': _('Минимальное качество (%)', 'Minimum Quality (%)'), 'key': 'IMAGE_QUALITY_REDUCTION_MIN_QUALITY', 'type': 'entry', 'default': '30', 'validation': gui.validate_positive_integer_or_zero},
        {'label': _('Скорость снижения', 'Decrease Rate'), 'key': 'IMAGE_QUALITY_REDUCTION_DECREASE_RATE', 'type': 'entry', 'default': '5', 'validation': gui.validate_positive_integer},
    ]
    create_settings_section(gui, parent_layout, _("Настройки угасания кадров", "Frame Regression Settings"), frame_compression_config, icon_name="fa6s.hourglass-half")

    # Четвёртая CollapsibleSection — описание изображений
    _vision_provider_names = [_("Текущий", "Current")]

    image_description_config = [
        {
            'label': _('Настройки автоматического текстового описания изображений моделью.',
                       'Configure automatic text description of images by the model.'),
            'type': 'text',
        },
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
    create_settings_section(gui, parent_layout, _("Описание изображений", "Image Description"), image_description_config, icon_name="fa6s.comment-dots")
    register_provider_options(gui, ("IMAGE_DESCRIPTION_PROVIDER",))
    # Detail depends on EITHER inline OR non-native mode being on (both use it)
    _wire_detail_dependency(gui)

    # Пятая CollapsibleSection — хранение и очистка изображений
    _setup_image_cleanup_section(gui, parent_layout)

    # Шестая CollapsibleSection — камера на голове Миты
    _setup_mita_camera_section(gui, parent_layout)


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
            'label': _('Инструменты для просмотра и удаления накопленных файлов изображений.',
                       'Tools for viewing and removing accumulated image files.'),
            'type': 'text',
        },
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
    create_settings_section(
        gui, parent_layout,
        _("Хранение и очистка изображений", "Image Storage & Cleanup"),
        cleanup_config,
        icon_name="fa6s.box-archive"
    )
    # Вставляем label с результатом прямо под секцией
    parent_layout.addWidget(result_label)


def _setup_mita_camera_section(gui, parent_layout) -> None:
    """
    Настройки FrameRecorder — камеры на голове Миты.

    Два режима:
      • Непрерывный — автозахват каждые N секунд, кадры складываются в буфер.
      • По команде  — Мита добавляет \"camera_snapshot\" в поле commands сегмента, Unity
                      немедленно захватывает кадр и отправляет Python как отдельный диалог.
    """
    mita_camera_config = [
        {
            'label': _('Настройки виртуальной камеры на голове Миты в игре.',
                       'Configure the in-game head-mounted camera on Mita.'),
            'type': 'text',
        },
        {
            'label': _('Включить камеру Миты (FrameRecorder)', 'Enable Mita Camera (FrameRecorder)'),
            'key': 'MITA_CAMERA_ENABLED',
            'type': 'checkbutton',
            'default_checkbutton': False,
            'tooltip': _(
                'Активирует систему камеры на голове Миты.\n'
                'Необходимо назначить Camera-компонент в Unity-сцене.',
                'Activates the head-mounted camera system on Mita.\n'
                'Requires a Camera component assigned in the Unity scene.'
            ),
        },
        {
            'label': _('Режим: непрерывный захват', 'Mode: continuous capture'),
            'key': 'MITA_CAMERA_CONTINUOUS',
            'type': 'checkbutton',
            'default_checkbutton': False,
            'depends_on': 'MITA_CAMERA_ENABLED',
            'tooltip': _(
                'Автоматически захватывает кадры с заданным интервалом.\n'
                'Кадры накапливаются в буфере и прикладываются к следующему запросу.',
                'Automatically captures frames at the set interval.\n'
                'Frames accumulate in a buffer and are attached to the next request.'
            ),
        },
        {
            'label': _('Режим: по команде Миты (DSL)', 'Mode: on-demand (DSL command)'),
            'key': 'MITA_CAMERA_ON_DEMAND',
            'type': 'checkbutton',
            'default_checkbutton': False,
            'depends_on': 'MITA_CAMERA_ENABLED',
            'tooltip': _(
                'Мита может сделать снимок, добавив "camera_snapshot" в поле commands сегмента.\n'
                'Unity захватывает кадр и немедленно отправляет его Мите\n'
                'как новый диалоговый запрос (event_type = camera_snapshot_result).',
                'Mita can take a snapshot by adding "camera_snapshot" to the commands field of a segment.\n'
                'Unity captures the frame and immediately sends it to Mita\n'
                'as a new dialogue request (event_type = camera_snapshot_result).'
            ),
        },
        {
            'label': _('Интервал захвата (сек)', 'Capture interval (sec)'),
            'key': 'MITA_CAMERA_INTERVAL',
            'type': 'entry',
            'default': '5.0',
            'depends_on': 'MITA_CAMERA_ENABLED',
            'validation': gui.validate_float_positive,
            'tooltip': _(
                'Интервал между кадрами в режиме непрерывного захвата (секунды).',
                'Interval between frames in continuous capture mode (seconds).'
            ),
        },
        {
            'label': _('Макс. кадров в буфере', 'Max frames in buffer'),
            'key': 'MITA_CAMERA_MAX_FRAMES',
            'type': 'entry',
            'default': '8',
            'depends_on': 'MITA_CAMERA_ENABLED',
            'validation': gui.validate_positive_integer,
            'tooltip': _(
                'Максимальное количество кадров, хранимых в кольцевом буфере.\n'
                'При переполнении старые кадры удаляются.',
                'Maximum number of frames kept in the ring buffer.\n'
                'Oldest frames are dropped when the buffer is full.'
            ),
        },
        {
            'label': _('Кадров для отправки', 'Frames to send'),
            'key': 'MITA_CAMERA_FRAMES_TO_SEND',
            'type': 'entry',
            'default': '1',
            'depends_on': 'MITA_CAMERA_ENABLED',
            'validation': gui.validate_positive_integer,
            'tooltip': _(
                'Сколько последних кадров из буфера прикладывать к запросу.',
                'How many latest frames from the buffer to attach to the request.'
            ),
        },
        {
            'label': _('Качество JPEG (%)', 'JPEG quality (%)'),
            'key': 'MITA_CAMERA_JPEG_QUALITY',
            'type': 'entry',
            'default': '40',
            'depends_on': 'MITA_CAMERA_ENABLED',
            'validation': gui.validate_positive_integer,
            'tooltip': _(
                'Степень сжатия JPEG (1–100). Ниже = меньше трафика, хуже качество.',
                'JPEG compression level (1–100). Lower = less traffic, worse quality.'
            ),
        },
        {
            'label': _('Передавать через файл (не base64)', 'Transfer via file path (not base64)'),
            'key': 'MITA_CAMERA_USE_FILE_TRANSFER',
            'type': 'checkbutton',
            'default_checkbutton': False,
            'depends_on': 'MITA_CAMERA_ENABLED',
            'tooltip': _(
                'Unity сохраняет кадры на диск и передаёт Python путь к файлу.\n'
                'Снижает нагрузку на сокет при больших изображениях.\n'
                'Требует, чтобы Python и Unity были на одной машине.',
                'Unity saves frames to disk and sends Python the file path.\n'
                'Reduces socket load for large images.\n'
                'Requires Python and Unity to run on the same machine.'
            ),
        },
    ]
    create_settings_section(
        gui, parent_layout,
        _("Камера Миты (FrameRecorder)", "Mita Camera (FrameRecorder)"),
        mita_camera_config,
        icon_name="fa6s.film"
    )
