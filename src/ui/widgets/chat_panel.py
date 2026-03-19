import base64
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QLabel, QFrame,
    QTextEdit, QGridLayout, QGraphicsOpacityEffect, QFileDialog
)
from PyQt6.QtCore import Qt, QPropertyAnimation, QPoint, QTimer, QBuffer, QIODevice
from PyQt6.QtGui import QFont, QPixmap
import qtawesome as qta
from styles.main_styles import get_stylesheet
from ui.widgets.mita_status_widget import MitaStatusWidget
from ui.widgets.image_preview_widget import ImagePreviewBar
from ui.widgets.image_viewer_widget import ImageViewerWidget
from ui.widgets.status_indicators_widget import create_status_indicators_inline
from ui.chat.chat_widget import ChatWidget
from utils import _
from core.events import Events
from main_logger import logger

def setup_chat_panel(gui, main_layout):
    chat_widget = QWidget()
    chat_layout = QVBoxLayout(chat_widget)
    chat_layout.setContentsMargins(10, 10, 10, 10)
    chat_layout.setSpacing(5)

    top_panel_layout = QHBoxLayout()

    gui.clear_chat_button = QPushButton(_("Очистить", "Clear"))
    gui.clear_chat_button.clicked.connect(gui.clear_chat_display)
    gui.clear_chat_button.setMaximumHeight(30)

    gui.load_history_button = QPushButton(_("Взять из истории", "Load from history"))
    gui.load_history_button.clicked.connect(gui.load_chat_history)
    gui.load_history_button.setMaximumHeight(30)

    gui.guide_button = QPushButton(qta.icon('fa5s.question-circle', color='#dcdcdc'), '')
    gui.guide_button.setObjectName("GuideButtonSmall")
    gui.guide_button.clicked.connect(gui._show_guide)
    gui.guide_button.setMaximumHeight(30)
    gui.guide_button.setFixedWidth(30)
    gui.guide_button.setToolTip(_("Открыть руководство пользователя", "Open user guide"))


    top_panel_layout.addWidget(gui.clear_chat_button)
    top_panel_layout.addWidget(gui.load_history_button)
    top_panel_layout.addWidget(gui.guide_button)

    top_panel_layout.addSpacing(20)
    create_status_indicators_inline(gui, top_panel_layout)
    top_panel_layout.addStretch()
    chat_layout.addLayout(top_panel_layout)

    # ── Chat display: widget-based scroll area ──────────────────────────────
    gui.chat_window = ChatWidget()
    gui.chat_window.setObjectName("ChatScrollArea")
    initial_font_size = int(gui._get_setting("CHAT_FONT_SIZE", 12))
    gui._chat_font_size = initial_font_size
    chat_layout.addWidget(gui.chat_window, 1)

    # Scroll-to-bottom button is built into ChatWidget, expose for compat
    gui.scroll_to_bottom_btn = gui.chat_window._scroll_btn
    gui.scroll_to_bottom_anim = gui.chat_window._scroll_btn._opacity_anim

    gui.mita_status = MitaStatusWidget(gui.chat_window)
    position_mita_status(gui)

    input_frame = QFrame()
    input_frame.setStyleSheet(get_stylesheet())
    input_layout = QVBoxLayout(input_frame)

    gui.token_count_label = QLabel(_("Токены: 0/0 | Стоимость: 0.00 ₽", "Tokens: 0/0 | Cost: 0.00 ₽"))
    gui.token_count_label.setStyleSheet("font-size: 10px;")
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
    gui.user_entry.setStyleSheet("""
        QTextEdit {
            background-color: transparent;
            border: none;
            color: #dcdcdc;
            padding: 2px;
        }
        QTextEdit:focus {
            background-color: transparent;
            border: none;
        }
    """)
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

    gui.attach_button = QPushButton(qta.icon('fa6s.paperclip', color='#b0b0b0', scale_factor=0.7), '')
    gui.attach_button.setObjectName("ChatIconMini")
    gui.attach_button.clicked.connect(lambda: attach_images(gui))
    gui.attach_button.setFixedSize(20, 20)
    gui.attach_button.setCursor(Qt.CursorShape.PointingHandCursor)
    gui.attach_button.setToolTip(_("Прикрепить изображения", "Attach images"))

    gui.send_screen_button = QPushButton(qta.icon('fa6s.camera', color='#b0b0b0', scale_factor=0.7), '')
    gui.send_screen_button.setObjectName("ChatIconMini")
    gui.send_screen_button.clicked.connect(lambda: send_screen_capture(gui))
    gui.send_screen_button.setFixedSize(20, 20)
    gui.send_screen_button.setCursor(Qt.CursorShape.PointingHandCursor)
    gui.send_screen_button.setToolTip(_("Сделать скриншот экрана", "Take screenshot"))

    button_layout_inner.addWidget(gui.attach_button)
    button_layout_inner.addWidget(gui.send_screen_button)
    button_layout_inner.addStretch()
    container_layout.addWidget(button_container, 1, 0)

    gui.send_button = QPushButton(qta.icon('fa6s.paper-plane', color='white', scale_factor=0.8), '')
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
    main_layout.addWidget(chat_widget, 1)

# ── Scroll button compat wrappers ───────────────────────────────────────────
# ChatWidget has its own scroll button, but main_view.py still calls these

def create_scroll_to_bottom_button(gui):
    """No-op: ChatWidget creates its own scroll button."""
    pass

def handle_chat_scroll(gui):
    """Compat wrapper — ChatWidget handles scrolling internally."""
    pass

def fade_in_scroll_button(gui):
    pass

def fade_out_scroll_button(gui):
    pass

def reposition_scroll_button(gui):
    if hasattr(gui, 'chat_window') and hasattr(gui.chat_window, '_reposition_scroll_button'):
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
        frames = gui.event_bus.emit_and_wait(Events.Capture.CAPTURE_SCREEN, {'limit': 1}, timeout=0.5)
        has_auto_images = bool(frames and frames[0])

    if gui._get_setting("ENABLE_CAMERA_CAPTURE", False):
        camera_frames = gui.event_bus.emit_and_wait(Events.Capture.GET_CAMERA_FRAMES, {'limit': 1}, timeout=0.5)
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
            if hasattr(widget, 'layout') and widget.layout():
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
    cb = gui.clipboard() if hasattr(gui, "clipboard") else None
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
    gui.event_bus.emit(Events.Chat.STAGE_IMAGE, {'image_data': img_bytes})
    show_image_preview_bar(gui)
    gui.image_preview_bar.add_image(img_bytes)
    update_send_button_state(gui)
    return True

def attach_images(gui):
    file_paths, __ = QFileDialog.getOpenFileNames(
        gui,
        _("Выберите изображения", "Select Images"),
        "",
        _("Файлы изображений (*.png *.jpg *.jpeg *.bmp *.gif)", "Image Files (*.png *.jpg *.jpeg *.bmp *.gif)")
    )
    if file_paths:
        for file_path in file_paths:
            gui.event_bus.emit(Events.Chat.STAGE_IMAGE, {'image_data': file_path})
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
    frames = gui.event_bus.emit_and_wait(Events.Capture.CAPTURE_SCREEN, {'limit': 1}, timeout=0.5)
    if not frames or not frames[0]:
        from PyQt6.QtWidgets import QMessageBox
        QMessageBox.warning(gui, _("Ошибка", "Error"),
                            _("Не удалось захватить экран. Убедитесь, что анализ экрана включен в настройках.",
                              "Failed to capture the screen. Make sure screen analysis is enabled in settings."))
        return
    for frame_data in frames[0]:
        gui.staged_image_data.append(frame_data)
        gui.event_bus.emit(Events.Chat.STAGE_IMAGE, {'image_data': frame_data})
    show_image_preview_bar(gui)
    for frame_data in frames[0]:
        gui.image_preview_bar.add_image(frame_data)
    update_send_button_state(gui)

def position_mita_status(gui):
    if not hasattr(gui, 'mita_status') or not gui.mita_status:
        return
    chat_width = gui.chat_window.width()
    chat_height = gui.chat_window.height()
    status_width = min(300, chat_width - 20)
    status_height = 40
    x = (chat_width - status_width) // 2
    y = chat_height - status_height + 3
    gui.mita_status.setGeometry(x, y, status_width, status_height)
