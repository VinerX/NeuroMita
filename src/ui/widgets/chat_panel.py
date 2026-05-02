import base64

from PyQt6.QtCore import QBuffer, QIODevice, QPoint, QPropertyAnimation, QTimer, Qt
from PyQt6.QtGui import QFont, QPixmap
from PyQt6.QtWidgets import (
    QFileDialog,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QComboBox,
    QSizePolicy,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

import qtawesome as qta

from core.events import Events
from main_logger import logger
from styles.main_styles import get_stylesheet
from ui.chat.chat_widget import ChatWidget
from ui.widgets.image_preview_widget import ImagePreviewBar
from ui.widgets.image_viewer_widget import ImageViewerWidget
from ui.widgets.mita_status_widget import MitaStatusWidget
from ui.widgets.status_indicators_widget import create_status_indicators
from utils import _

TOP_ICON_BUTTON_SIZE = 30


def _populate_chat_character_combobox(gui):
    combo = getattr(gui, "chat_character_combobox", None)
    if combo is None:
        return

    all_characters = gui.event_bus.emit_and_wait(Events.Character.GET_ALL, timeout=1.0)
    character_list = all_characters[0] if all_characters else ["Crazy"]
    if not character_list:
        character_list = ["Crazy"]

    current_profile_res = gui.event_bus.emit_and_wait(Events.Character.GET_CURRENT_PROFILE, timeout=1.0)
    current_profile = current_profile_res[0] if current_profile_res else {}
    current_char_id = current_profile.get("character_id", character_list[0]) if isinstance(current_profile, dict) else character_list[0]

    combo.blockSignals(True)
    try:
        combo.clear()
        combo.addItems(character_list)
        idx = combo.findText(str(current_char_id), Qt.MatchFlag.MatchFixedString)
        if idx >= 0:
            combo.setCurrentIndex(idx)
    finally:
        combo.blockSignals(False)


def _on_chat_character_changed(gui, character_id):
    character_id = str(character_id or "").strip()
    if not character_id:
        return

    settings_combo = getattr(gui, "character_combobox", None)
    if settings_combo is not None and settings_combo.currentText() != character_id:
        idx = settings_combo.findText(character_id, Qt.MatchFlag.MatchFixedString)
        if idx >= 0:
            settings_combo.setCurrentIndex(idx)
            return

    gui.event_bus.emit(Events.Character.SET_CURRENT, {"character_id": character_id})
    gui.event_bus.emit(Events.Character.RELOAD_DATA)


def _open_selected_character_history(gui):
    combo = getattr(gui, "chat_character_combobox", None)
    character_id = combo.currentText().strip() if combo is not None else ""
    if character_id:
        gui.event_bus.emit(Events.Character.SET_CURRENT, {"character_id": character_id})

    try:
        from ui.settings.character_settings.logic import open_db_viewer

        open_db_viewer(gui)
    except Exception as e:
        logger.error(f"Failed to open character history: {e}", exc_info=True)


def _jump_to_settings(gui, category: str):
    gui.switch_main_page("settings")
    gui.show_settings_category(category)


def _make_selector_card(title: str) -> tuple[QFrame, QVBoxLayout]:
    card = QFrame()
    card.setObjectName("SandboxSelectorCard")
    layout = QVBoxLayout(card)
    layout.setContentsMargins(14, 12, 14, 12)
    layout.setSpacing(6)

    label = QLabel(title)
    label.setObjectName("SandboxSelectorLabel")
    layout.addWidget(label)
    return card, layout


def _build_chat_header(gui) -> QFrame:
    hero_card = QFrame()
    hero_card.setObjectName("ChatToolbarCard")
    hero_layout = QVBoxLayout(hero_card)
    hero_layout.setContentsMargins(18, 18, 18, 18)
    hero_layout.setSpacing(12)

    title_row = QHBoxLayout()
    title_row.setSpacing(16)

    title_col = QVBoxLayout()
    title_col.setSpacing(4)
    title_label = QLabel(_("Песочница / SANDBOX", "Sandbox / SANDBOX"))
    title_label.setObjectName("ChatHeroTitle")
    title_col.addWidget(title_label)

    subtitle_label = QLabel(
        _(
            "Экспериментируй, общайся и тестируй возможности NeuroMita в новой launcher-оболочке.",
            "Experiment, chat and test NeuroMita inside the rebuilt launcher shell.",
        )
    )
    subtitle_label.setObjectName("ChatHeroSubtitle")
    subtitle_label.setWordWrap(True)
    title_col.addWidget(subtitle_label)
    title_row.addLayout(title_col, 1)

    guide_button = QPushButton(_("Открыть руководство", "Open guide"))
    guide_button.setObjectName("SecondaryButton")
    guide_button.clicked.connect(gui._show_guide)
    title_row.addWidget(guide_button, 0, Qt.AlignmentFlag.AlignTop)
    hero_layout.addLayout(title_row)

    selectors = QHBoxLayout()
    selectors.setSpacing(10)

    character_card, character_layout = _make_selector_card(_("Персонаж", "Character"))
    gui.chat_character_combobox = QComboBox()
    gui.chat_character_combobox.setObjectName("ChatCharacterCombo")
    gui.chat_character_combobox.setToolTip(_("Выбрать персонажа", "Select character"))
    gui.chat_character_combobox.currentTextChanged.connect(lambda text: _on_chat_character_changed(gui, text))
    character_layout.addWidget(gui.chat_character_combobox)
    _populate_chat_character_combobox(gui)
    selectors.addWidget(character_card, 2)

    model_card, model_layout = _make_selector_card(_("Модель", "Model"))
    model_value = QLabel(str(gui._get_setting("MODEL", "gpt-4o-mini")))
    model_value.setObjectName("SandboxSelectorValue")
    model_layout.addWidget(model_value)
    model_hint = QLabel(str(gui._get_setting("API_TYPE", "OpenAI")))
    model_hint.setObjectName("SandboxSelectorHint")
    model_layout.addWidget(model_hint)
    selectors.addWidget(model_card, 1)

    tts_card, tts_layout = _make_selector_card(_("TTS", "TTS"))
    tts_value = QLabel(str(gui._get_setting("VOICEOVER_METHOD", "TG")))
    tts_value.setObjectName("SandboxSelectorValue")
    tts_layout.addWidget(tts_value)
    selectors.addWidget(tts_card, 1)

    asr_card, asr_layout = _make_selector_card(_("ASR", "ASR"))
    asr_value = QLabel(str(gui._get_setting("ASR_MODEL_NAME", _("По умолчанию", "Default"))))
    asr_value.setObjectName("SandboxSelectorValue")
    asr_layout.addWidget(asr_value)
    selectors.addWidget(asr_card, 1)

    mode_card, mode_layout = _make_selector_card(_("Режим", "Mode"))
    mode_value = QLabel(_("Свободный", "Free"))
    mode_value.setObjectName("SandboxSelectorValue")
    mode_layout.addWidget(mode_value)
    mode_hint = QLabel("Sandbox")
    mode_hint.setObjectName("SandboxSelectorHintAccent")
    mode_layout.addWidget(mode_hint)
    selectors.addWidget(mode_card, 1)

    hero_layout.addLayout(selectors)
    return hero_card


def _build_chat_inspector(gui) -> QWidget:
    inspector = QWidget()
    inspector.setObjectName("SandboxInspector")
    inspector.setFixedWidth(320)
    layout = QVBoxLayout(inspector)
    layout.setContentsMargins(0, 0, 0, 0)
    layout.setSpacing(12)

    status_card = QFrame()
    status_card.setObjectName("SandboxInspectorCard")
    status_layout = QVBoxLayout(status_card)
    status_layout.setContentsMargins(16, 16, 16, 16)
    status_layout.setSpacing(10)
    status_title = QLabel(_("Подключения", "Connections"))
    status_title.setObjectName("SandboxInspectorTitle")
    status_layout.addWidget(status_title)
    create_status_indicators(gui, status_layout)
    layout.addWidget(status_card)

    quick_card = QFrame()
    quick_card.setObjectName("SandboxInspectorCard")
    quick_layout = QVBoxLayout(quick_card)
    quick_layout.setContentsMargins(16, 16, 16, 16)
    quick_layout.setSpacing(10)
    quick_title = QLabel(_("Быстрые действия", "Quick actions"))
    quick_title.setObjectName("SandboxInspectorTitle")
    quick_layout.addWidget(quick_title)

    gui.clear_chat_button = QPushButton(_("Очистить чат", "Clear chat"))
    gui.clear_chat_button.setObjectName("SandboxQuickAction")
    gui.clear_chat_button.clicked.connect(gui.clear_chat_display)
    quick_layout.addWidget(gui.clear_chat_button)

    gui.load_history_button = QPushButton(_("Загрузить историю", "Load history"))
    gui.load_history_button.setObjectName("SandboxQuickAction")
    gui.load_history_button.clicked.connect(gui.load_chat_history)
    quick_layout.addWidget(gui.load_history_button)

    gui.open_character_history_button = QPushButton(_("Открыть DB персонажа", "Open character DB"))
    gui.open_character_history_button.setObjectName("SandboxQuickAction")
    gui.open_character_history_button.clicked.connect(lambda: _open_selected_character_history(gui))
    quick_layout.addWidget(gui.open_character_history_button)

    api_button = QPushButton(_("API и пресеты", "API and presets"))
    api_button.setObjectName("SandboxQuickAction")
    api_button.clicked.connect(lambda: _jump_to_settings(gui, "api"))
    quick_layout.addWidget(api_button)

    memory_button = QPushButton(_("Память и RAG", "Memory and RAG"))
    memory_button.setObjectName("SandboxQuickAction")
    memory_button.clicked.connect(lambda: _jump_to_settings(gui, "models"))
    quick_layout.addWidget(memory_button)
    layout.addWidget(quick_card)

    summary_card = QFrame()
    summary_card.setObjectName("SandboxInspectorCard")
    summary_layout = QVBoxLayout(summary_card)
    summary_layout.setContentsMargins(16, 16, 16, 16)
    summary_layout.setSpacing(8)
    summary_title = QLabel(_("Контекст сессии", "Session context"))
    summary_title.setObjectName("SandboxInspectorTitle")
    summary_layout.addWidget(summary_title)

    summary_lines = [
        (_("Профиль памяти", "Memory profile"), str(gui._get_setting("MEMORY_PROFILE", _("По умолчанию", "Default")))),
        (_("Голос", "Voice"), str(gui._get_setting("VOICEOVER_METHOD", "TG"))),
        (_("Экран", "Screen"), _("Включён", "Enabled") if gui._get_setting("ENABLE_SCREEN_ANALYSIS", False) else _("Выключен", "Disabled")),
        (_("Камера", "Camera"), _("Включена", "Enabled") if gui._get_setting("ENABLE_CAMERA_CAPTURE", False) else _("Выключена", "Disabled")),
    ]
    for label_text, value_text in summary_lines:
        row = QHBoxLayout()
        row.setSpacing(8)
        label = QLabel(label_text)
        label.setObjectName("SandboxInspectorLabel")
        row.addWidget(label)
        row.addStretch()
        value = QLabel(value_text)
        value.setObjectName("SandboxInspectorValue")
        row.addWidget(value)
        summary_layout.addLayout(row)
    layout.addWidget(summary_card)
    layout.addStretch(1)
    return inspector


def setup_chat_panel(gui, main_layout):
    page_root = QWidget()
    page_root.setObjectName("SandboxPage")

    page_layout = QVBoxLayout(page_root)
    page_layout.setContentsMargins(18, 18, 18, 18)
    page_layout.setSpacing(12)
    page_layout.addWidget(_build_chat_header(gui))

    content_row = QHBoxLayout()
    content_row.setSpacing(12)

    chat_column = QWidget()
    chat_column.setObjectName("ChatWorkspace")
    chat_layout = QVBoxLayout(chat_column)
    chat_layout.setContentsMargins(0, 0, 0, 0)
    chat_layout.setSpacing(12)

    gui.chat_window = ChatWidget()
    gui.chat_window.setObjectName("ChatScrollArea")
    initial_font_size = int(gui._get_setting("CHAT_FONT_SIZE", 12))
    gui._chat_font_size = initial_font_size
    chat_layout.addWidget(gui.chat_window, 1)

    gui.scroll_to_bottom_btn = gui.chat_window._scroll_btn
    gui.scroll_to_bottom_anim = gui.chat_window._scroll_btn._opacity_anim
    gui.mita_status = MitaStatusWidget(gui.chat_window)

    input_frame = QFrame()
    input_frame.setObjectName("ChatComposerCard")
    input_frame.setStyleSheet(get_stylesheet())
    input_layout = QVBoxLayout(input_frame)
    input_layout.setContentsMargins(18, 16, 18, 16)
    input_layout.setSpacing(8)

    gui.token_count_label = QLabel(_("Токены: 0/0 | Стоимость: 0.00 ₽", "Tokens: 0/0 | Cost: 0.00 ₽"))
    gui.token_count_label.setObjectName("TokenCountLabel")
    input_layout.addWidget(gui.token_count_label)

    input_container = QWidget()
    input_container.setObjectName("ChatInputContainer")
    container_layout = QGridLayout(input_container)
    container_layout.setContentsMargins(5, 5, 5, 5)
    container_layout.setSpacing(5)

    gui.user_entry = QTextEdit()
    gui.user_entry.setMinimumHeight(24)
    gui.user_entry.setMaximumHeight(80)
    gui.user_entry.setFixedHeight(36)
    gui.user_entry.setPlaceholderText(_("Напиши что-нибудь Mita…", "Write something to Mita…"))
    gui.user_entry.setStyleSheet(
        """
        QTextEdit {
            background-color: transparent;
            border: none;
            color: #f7edf5;
            padding: 4px 2px;
        }
        QTextEdit:focus {
            background-color: transparent;
            border: none;
        }
        """
    )
    gui.user_entry.textChanged.connect(lambda: adjust_input_height(gui))
    gui.user_entry.textChanged.connect(lambda: update_send_button_state(gui))
    gui.user_entry.installEventFilter(gui)
    container_layout.addWidget(gui.user_entry, 0, 0, 1, 2)

    button_container = QWidget()
    button_container.setFixedHeight(24)
    button_container.setStyleSheet("background-color: transparent; border: none;")
    button_layout_inner = QHBoxLayout(button_container)
    button_layout_inner.setContentsMargins(0, 0, 0, 0)
    button_layout_inner.setSpacing(4)

    gui.attach_button = QPushButton(qta.icon("fa6s.paperclip", color="#b0b0b0", scale_factor=0.7), "")
    gui.attach_button.setObjectName("ChatIconMini")
    gui.attach_button.clicked.connect(lambda: attach_images(gui))
    gui.attach_button.setFixedSize(20, 20)
    gui.attach_button.setCursor(Qt.CursorShape.PointingHandCursor)
    gui.attach_button.setToolTip(_("Прикрепить изображения", "Attach images"))

    gui.send_screen_button = QPushButton(qta.icon("fa6s.camera", color="#b0b0b0", scale_factor=0.7), "")
    gui.send_screen_button.setObjectName("ChatIconMini")
    gui.send_screen_button.clicked.connect(lambda: send_screen_capture(gui))
    gui.send_screen_button.setFixedSize(20, 20)
    gui.send_screen_button.setCursor(Qt.CursorShape.PointingHandCursor)
    gui.send_screen_button.setToolTip(_("Сделать скриншот экрана", "Take screenshot"))

    button_layout_inner.addWidget(gui.attach_button)
    button_layout_inner.addWidget(gui.send_screen_button)
    button_layout_inner.addStretch()
    container_layout.addWidget(button_container, 1, 0)

    gui.send_button = QPushButton(qta.icon("fa6s.paper-plane", color="white", scale_factor=0.8), "")
    gui.send_button.setObjectName("ChatSendButtonCircle")
    gui.send_button.clicked.connect(gui.send_message)
    gui.send_button.setFixedSize(28, 28)
    gui.send_button.setCursor(Qt.CursorShape.PointingHandCursor)
    gui.send_button.setToolTip(_("Отправить сообщение", "Send message"))

    send_container = QWidget()
    send_container.setStyleSheet("background-color: transparent; border: none;")
    send_layout = QHBoxLayout(send_container)
    send_layout.setContentsMargins(0, 0, 0, 0)
    send_layout.addStretch()
    send_layout.addWidget(gui.send_button)
    container_layout.addWidget(send_container, 1, 1)

    input_layout.addWidget(input_container)
    gui.attachment_label = QLabel("")
    gui.attachment_label.setVisible(False)
    gui.clear_attach_btn = QPushButton("")
    gui.clear_attach_btn.setVisible(False)

    chat_layout.addWidget(input_frame)
    update_send_button_state(gui)

    content_row.addWidget(chat_column, 1)
    content_row.addWidget(_build_chat_inspector(gui))
    page_layout.addLayout(content_row, 1)
    main_layout.addWidget(page_root, 1)


def create_scroll_to_bottom_button(gui):
    pass


def handle_chat_scroll(gui):
    pass


def fade_in_scroll_button(gui):
    pass


def fade_out_scroll_button(gui):
    pass


def reposition_scroll_button(gui):
    if hasattr(gui, "chat_window") and hasattr(gui.chat_window, "_reposition_scroll_button"):
        gui.chat_window._reposition_scroll_button()


def adjust_input_height(gui):
    doc = gui.user_entry.document()
    doc_height = doc.size().height()
    new_height = int(doc_height + 10)
    new_height = max(36, min(new_height, 80))
    gui.user_entry.setFixedHeight(new_height)


def update_send_button_state(gui):
    has_text = bool(gui.user_entry.toPlainText().strip())
    has_images = bool(getattr(gui, "staged_image_data", []))

    has_auto_images = False
    if gui._get_setting("ENABLE_SCREEN_ANALYSIS", False):
        frames = gui.event_bus.emit_and_wait(Events.Capture.CAPTURE_SCREEN, {"limit": 1}, timeout=0.5)
        has_auto_images = bool(frames and frames[0])

    if gui._get_setting("ENABLE_CAMERA_CAPTURE", False):
        camera_frames = gui.event_bus.emit_and_wait(Events.Capture.GET_CAMERA_FRAMES, {"limit": 1}, timeout=0.5)
        has_auto_images = has_auto_images or bool(camera_frames and camera_frames[0])

    is_enabled = has_text or has_images or has_auto_images
    gui.send_button.setEnabled(is_enabled)


def init_image_preview(gui):
    gui.staged_image_data = []


def show_image_preview_bar(gui):
    if not getattr(gui, "image_preview_bar", None):
        input_frame = None
        widget = gui.user_entry
        while widget:
            if isinstance(widget, QFrame) and widget.objectName() != "":
                break
            if hasattr(widget, "layout") and widget.layout():
                for i in range(widget.layout().count()):
                    item = widget.layout().itemAt(i)
                    if item and item.widget() == gui.token_count_label:
                        input_frame = widget
                        break
            if input_frame:
                break
            widget = widget.parent()
        if not input_frame:
            input_frame = gui.token_count_label.parent()
        if input_frame:
            gui.image_preview_bar = ImagePreviewBar(input_frame)
            gui.image_preview_bar.thumbnail_clicked.connect(lambda img: show_full_image(gui, img))
            gui.image_preview_bar.remove_requested.connect(lambda idx: remove_staged_image(gui, idx))
            input_frame.layout().insertWidget(1, gui.image_preview_bar)
    gui.image_preview_bar.show()


def remove_staged_image(gui, index):
    if 0 <= index < len(gui.staged_image_data):
        gui.staged_image_data.pop(index)
        gui.image_preview_bar.remove_at(index)
        if len(gui.staged_image_data) == 0:
            hide_image_preview_bar(gui)
        update_send_button_state(gui)


def hide_image_preview_bar(gui):
    if getattr(gui, "image_preview_bar", None):
        gui.image_preview_bar.hide()


def show_full_image(gui, image_data):
    try:
        if isinstance(image_data, str) and image_data.startswith("data:image"):
            base64_data = image_data.split(",")[1]
            img_bytes = base64.b64decode(base64_data)
        elif isinstance(image_data, bytes):
            img_bytes = image_data
        else:
            return
        pixmap = QPixmap()
        pixmap.loadFromData(img_bytes)
        viewer = ImageViewerWidget(pixmap)
        viewer.close_requested.connect(gui.overlay.hide_animated)
        gui.overlay.set_content(viewer)
        gui.overlay.show_animated()
    except Exception as e:
        logger.error(f"Ошибка при показе изображения: {e}")


def clipboard_image_to_controller(gui) -> bool:
    from PyQt6.QtWidgets import QApplication

    cb = QApplication.clipboard()
    if not cb.mimeData().hasImage():
        return False
    qimg = cb.image()
    if qimg.isNull():
        return False
    buf = QBuffer()
    buf.open(QIODevice.OpenModeFlag.WriteOnly)
    qimg.save(buf, "PNG")
    img_bytes = buf.data().data()
    gui.staged_image_data.append(img_bytes)
    gui.event_bus.emit(Events.Chat.STAGE_IMAGE, {"image_data": img_bytes})
    show_image_preview_bar(gui)
    gui.image_preview_bar.add_image(img_bytes)
    update_send_button_state(gui)
    return True


def attach_images(gui):
    file_paths, __ = QFileDialog.getOpenFileNames(
        gui,
        _("Выберите изображения", "Select Images"),
        "",
        _("Файлы изображений (*.png *.jpg *.jpeg *.bmp *.gif)", "Image Files (*.png *.jpg *.jpeg *.bmp *.gif)"),
    )
    if file_paths:
        for file_path in file_paths:
            gui.event_bus.emit(Events.Chat.STAGE_IMAGE, {"image_data": file_path})
        for file_path in file_paths:
            try:
                with open(file_path, "rb") as f:
                    img_data = f.read()
                    gui.staged_image_data.append(img_data)
                    show_image_preview_bar(gui)
                    gui.image_preview_bar.add_image(img_data)
            except Exception as e:
                logger.error(f"Ошибка чтения файла {file_path}: {e}")
        logger.info(f"Прикреплены изображения: {file_paths}")
        update_send_button_state(gui)


def clear_staged_images(gui):
    gui.event_bus.emit(Events.Chat.CLEAR_STAGED_IMAGES)
    gui.staged_image_data.clear()
    if getattr(gui, "image_preview_bar", None):
        gui.image_preview_bar.clear()
        hide_image_preview_bar(gui)
    update_send_button_state(gui)


def send_screen_capture(gui):
    logger.info("Запрошена отправка скриншота.")
    frames = gui.event_bus.emit_and_wait(Events.Capture.CAPTURE_SCREEN, {"limit": 1}, timeout=0.5)
    if not frames or not frames[0]:
        from PyQt6.QtWidgets import QMessageBox

        QMessageBox.warning(
            gui,
            _("Ошибка", "Error"),
            _(
                "Не удалось захватить экран. Убедитесь, что анализ экрана включен в настройках.",
                "Failed to capture the screen. Make sure screen analysis is enabled in settings.",
            ),
        )
        return
    for frame_data in frames[0]:
        gui.staged_image_data.append(frame_data)
        gui.event_bus.emit(Events.Chat.STAGE_IMAGE, {"image_data": frame_data})
        show_image_preview_bar(gui)
        gui.image_preview_bar.add_image(frame_data)
    update_send_button_state(gui)


def position_mita_status(gui):
    if not hasattr(gui, "mita_status") or not gui.mita_status:
        return
    chat_viewport = gui.chat_window.viewport().rect()
    status_width = gui.mita_status.width()
    status_height = gui.mita_status.height()
    x = chat_viewport.width() - status_width - 20
    y = chat_viewport.height() - status_height - 20
    gui.mita_status.move(gui.chat_window.mapToParent(QPoint(x, y)))
