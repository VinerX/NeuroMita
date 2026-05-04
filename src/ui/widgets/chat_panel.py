import base64

import qtawesome as qta

from PyQt6.QtCore import QBuffer, QIODevice, QPoint, Qt
from PyQt6.QtGui import QPixmap
from PyQt6.QtWidgets import (
    QFileDialog,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from core.events import Events
from main_logger import logger
from styles.main_styles import get_stylesheet
from ui.chat.chat_widget import ChatWidget
from ui.widgets.image_preview_widget import ImagePreviewBar
from ui.widgets.image_viewer_widget import ImageViewerWidget
from ui.widgets.mita_status_widget import MitaStatusWidget
from utils import _


class ChatPanel(QWidget):
    def __init__(self, gui):
        super().__init__(gui)
        self.gui = gui
        self.setObjectName("ChatWorkspace")

        self._conversation_title_label = None

        self._build_ui()
        self.gui.chat_panel = self
        self.on_activated()

    def _get_current_character_id(self) -> str:
        try:
            result = self.gui.event_bus.emit_and_wait(Events.Character.GET_CURRENT_PROFILE, timeout=0.5)
            profile = result[0] if result else {}
        except Exception:
            profile = {}
        return str((profile or {}).get("character_id") or "")

    def _refresh_conversation_title(self):
        if self._conversation_title_label is None:
            return

        char_id = self._get_current_character_id()
        self._conversation_title_label.setText(
            _("Разговор с ", "Conversation with ") + (char_id or _("персонажем", "character"))
        )

    def on_activated(self):
        self._refresh_conversation_title()
        update_send_button_state(self.gui)

    def _build_conversation_strip(self) -> QFrame:
        strip = QFrame()
        strip.setObjectName("ChatConversationStrip")

        layout = QHBoxLayout(strip)
        layout.setContentsMargins(14, 8, 14, 8)
        layout.setSpacing(14)

        heart = QLabel()
        heart.setPixmap(qta.icon("fa6s.heart", color="#ff7eb6").pixmap(14, 14))
        layout.addWidget(heart, 0, Qt.AlignmentFlag.AlignVCenter)

        title = QLabel("")
        title.setObjectName("ChatStripTitle")
        layout.addWidget(title, 0, Qt.AlignmentFlag.AlignVCenter)
        self._conversation_title_label = title
        self.gui.chat_strip_title = title

        layout.addStretch(1)

        clear_button = QPushButton(_("Очистить чат", "Clear chat"))
        clear_button.setObjectName("ChatStripGhostButton")
        clear_button.setIcon(qta.icon("fa6s.trash", color="#ffd2ec"))
        clear_button.setCursor(Qt.CursorShape.PointingHandCursor)
        clear_button.clicked.connect(self.gui.clear_chat_display)
        layout.addWidget(clear_button, 0, Qt.AlignmentFlag.AlignVCenter)

        return strip

    def _build_composer(self) -> QFrame:
        input_frame = QFrame()
        input_frame.setObjectName("ChatComposerCard")
        input_frame.setStyleSheet(get_stylesheet())

        input_layout = QVBoxLayout(input_frame)
        input_layout.setContentsMargins(18, 16, 18, 16)
        input_layout.setSpacing(8)

        self.gui.token_count_label = QLabel(_("Токены: 0/0 | Стоимость: 0.00 ₽", "Tokens: 0/0 | Cost: 0.00 ₽"))
        self.gui.token_count_label.setObjectName("TokenCountLabel")
        input_layout.addWidget(self.gui.token_count_label)

        input_container = QWidget()
        input_container.setObjectName("ChatInputContainer")
        container_layout = QGridLayout(input_container)
        container_layout.setContentsMargins(5, 5, 5, 5)
        container_layout.setSpacing(5)

        self.gui.user_entry = QTextEdit()
        self.gui.user_entry.setMinimumHeight(24)
        self.gui.user_entry.setMaximumHeight(80)
        self.gui.user_entry.setFixedHeight(36)
        self.gui.user_entry.setPlaceholderText(_("Напиши что-нибудь Mita…", "Write something to Mita…"))
        self.gui.user_entry.setStyleSheet(
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
        self.gui.user_entry.textChanged.connect(lambda: adjust_input_height(self.gui))
        self.gui.user_entry.textChanged.connect(lambda: update_send_button_state(self.gui))
        self.gui.user_entry.installEventFilter(self.gui)
        container_layout.addWidget(self.gui.user_entry, 0, 0, 1, 2)

        button_container = QWidget()
        button_container.setFixedHeight(24)
        button_container.setStyleSheet("background-color: transparent; border: none;")
        button_layout_inner = QHBoxLayout(button_container)
        button_layout_inner.setContentsMargins(0, 0, 0, 0)
        button_layout_inner.setSpacing(4)

        self.gui.attach_button = QPushButton(qta.icon("fa6s.paperclip", color="#b0b0b0", scale_factor=0.7), "")
        self.gui.attach_button.setObjectName("ChatIconMini")
        self.gui.attach_button.clicked.connect(lambda: attach_images(self.gui))
        self.gui.attach_button.setFixedSize(20, 20)
        self.gui.attach_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.gui.attach_button.setToolTip(_("Прикрепить изображения", "Attach images"))

        self.gui.send_screen_button = QPushButton(qta.icon("fa6s.camera", color="#b0b0b0", scale_factor=0.7), "")
        self.gui.send_screen_button.setObjectName("ChatIconMini")
        self.gui.send_screen_button.clicked.connect(lambda: send_screen_capture(self.gui))
        self.gui.send_screen_button.setFixedSize(20, 20)
        self.gui.send_screen_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.gui.send_screen_button.setToolTip(_("Сделать скриншот экрана", "Take screenshot"))

        button_layout_inner.addWidget(self.gui.attach_button)
        button_layout_inner.addWidget(self.gui.send_screen_button)
        button_layout_inner.addStretch()
        container_layout.addWidget(button_container, 1, 0)

        self.gui.send_button = QPushButton(qta.icon("fa6s.paper-plane", color="white", scale_factor=0.8), "")
        self.gui.send_button.setObjectName("ChatSendButtonCircle")
        self.gui.send_button.clicked.connect(self.gui.send_message)
        self.gui.send_button.setFixedSize(28, 28)
        self.gui.send_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.gui.send_button.setToolTip(_("Отправить сообщение", "Send message"))

        send_container = QWidget()
        send_container.setStyleSheet("background-color: transparent; border: none;")
        send_layout = QHBoxLayout(send_container)
        send_layout.setContentsMargins(0, 0, 0, 0)
        send_layout.addStretch()
        send_layout.addWidget(self.gui.send_button)
        container_layout.addWidget(send_container, 1, 1)

        input_layout.addWidget(input_container)
        self.gui.attachment_label = QLabel("")
        self.gui.attachment_label.setVisible(False)
        self.gui.clear_attach_btn = QPushButton("")
        self.gui.clear_attach_btn.setVisible(False)

        return input_frame

    def _build_ui(self):
        if not hasattr(self.gui, "staged_image_data"):
            self.gui.staged_image_data = []

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(12)
        layout.addWidget(self._build_conversation_strip())

        self.gui.chat_window = ChatWidget()
        self.gui.chat_window.setObjectName("ChatScrollArea")
        self.gui._chat_font_size = int(self.gui._get_setting("CHAT_FONT_SIZE", 12))
        layout.addWidget(self.gui.chat_window, 1)

        self.gui.scroll_to_bottom_btn = self.gui.chat_window._scroll_btn
        self.gui.scroll_to_bottom_anim = self.gui.chat_window._scroll_btn._opacity_anim
        self.gui.mita_status = MitaStatusWidget(self.gui.chat_window)

        layout.addWidget(self._build_composer())


def setup_chat_panel(gui, main_layout):
    from ui.pages.sandbox_page import SandboxPage

    page = SandboxPage(gui)
    gui.sandbox_page = page
    main_layout.addWidget(page, 1)
    return page


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
    if not getattr(gui, "user_entry", None):
        return

    doc = gui.user_entry.document()
    doc_height = doc.size().height()
    new_height = int(doc_height + 10)
    new_height = max(36, min(new_height, 80))
    gui.user_entry.setFixedHeight(new_height)


def update_send_button_state(gui):
    if not getattr(gui, "user_entry", None) or not getattr(gui, "send_button", None):
        return

    has_text = bool(gui.user_entry.toPlainText().strip())
    has_images = bool(getattr(gui, "staged_image_data", []))

    has_auto_images = False
    if gui._get_setting("ENABLE_SCREEN_ANALYSIS", False):
        frames = gui.event_bus.emit_and_wait(Events.Capture.CAPTURE_SCREEN, {"limit": 1}, timeout=0.5)
        has_auto_images = bool(frames and frames[0])

    if gui._get_setting("ENABLE_CAMERA_CAPTURE", False):
        camera_frames = gui.event_bus.emit_and_wait(Events.Capture.GET_CAMERA_FRAMES, {"limit": 1}, timeout=0.5)
        has_auto_images = has_auto_images or bool(camera_frames and camera_frames[0])

    gui.send_button.setEnabled(has_text or has_images or has_auto_images)


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
                for index in range(widget.layout().count()):
                    item = widget.layout().itemAt(index)
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
        if not gui.staged_image_data:
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
    except Exception as exc:
        logger.error(f"Ошибка при показе изображения: {exc}")


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
    if not file_paths:
        return

    for file_path in file_paths:
        gui.event_bus.emit(Events.Chat.STAGE_IMAGE, {"image_data": file_path})

    for file_path in file_paths:
        try:
            with open(file_path, "rb") as file:
                img_data = file.read()
            gui.staged_image_data.append(img_data)
            show_image_preview_bar(gui)
            gui.image_preview_bar.add_image(img_data)
        except Exception as exc:
            logger.error(f"Ошибка чтения файла {file_path}: {exc}")

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
