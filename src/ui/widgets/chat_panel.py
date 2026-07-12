import base64

import qtawesome as qta

from PyQt6.QtCore import QBuffer, QIODevice, QPoint, Qt
from PyQt6.QtGui import QPixmap
from PyQt6.QtWidgets import (
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from main_logger import logger
from ui.chat.chat_widget import ChatWidget
from ui.widgets.chat_panel_presentation import (
    ChatCaptureScreenRequested,
    ChatClearStagedRequested,
    ChatImagesStaged,
    ChatInputChanged,
    ChatOpenHistoryRequested,
    ChatPanelActivated,
    ChatPanelState,
    ChatShowError,
    ChatStageFilesRequested,
    ChatStageImageRequested,
    ChatStagedCleared,
)
from ui.widgets.image_preview_widget import ImagePreviewBar
from ui.widgets.image_viewer_widget import ImageViewerWidget
from ui.widgets.mita_status_widget import MitaStatusWidget
from utils import _
from localization.live import tr_set


class ChatPanel(QWidget):
    def __init__(self, gui, view_model):
        super().__init__(gui)
        self.gui = gui
        self._view_model = view_model
        self._state: ChatPanelState = view_model.state
        self.setObjectName("ChatWorkspace")

        self._conversation_title_label = None

        self._build_ui()
        self._view_model.state_changed.connect(self.render)
        self._view_model.effect_emitted.connect(self._handle_effect)
        self.destroyed.connect(lambda *_: self._view_model.close())
        self.render(self._state)
        self.gui.chat_panel = self

    def _get_current_character_id(self) -> str:
        return str(self._state.character_id or "")

    def render(self, state: ChatPanelState) -> None:
        self._state = state
        self.gui._composer_blocked = bool(state.blocked)
        self.gui._composer_block_category = str(state.settings_category or "api")
        if self._conversation_title_label is not None:
            self._conversation_title_label.setText(
                _("Разговор с ", "Conversation with ")
                + (state.character_id or _("персонажем", "character"))
            )
        warning_label = getattr(self.gui, "composer_warning_label", None)
        if warning_label is not None:
            warning_label.setText(state.warning)
        composer = getattr(self.gui, "composer_bar", None)
        warning = getattr(self.gui, "composer_warning", None)
        if composer is not None:
            composer.setVisible(not state.blocked)
        if warning is not None:
            warning.setVisible(state.blocked)
        send_button = getattr(self.gui, "send_button", None)
        if send_button is not None:
            send_button.setEnabled(bool(state.can_send))

    def _handle_effect(self, effect) -> None:
        if isinstance(effect, ChatImagesStaged):
            for image in effect.images:
                self.gui.staged_image_data.append(image)
                show_image_preview_bar(self.gui)
                self.gui.image_preview_bar.add_image(image)
            self._dispatch_input_state()
            return
        if isinstance(effect, ChatStagedCleared):
            self.gui.staged_image_data.clear()
            if getattr(self.gui, "image_preview_bar", None):
                self.gui.image_preview_bar.clear()
                hide_image_preview_bar(self.gui)
            self._dispatch_input_state()
            return
        if isinstance(effect, ChatShowError):
            from PyQt6.QtWidgets import QMessageBox

            QMessageBox.warning(self, effect.title, effect.message)

    def _dispatch_input_state(self) -> None:
        entry = getattr(self.gui, "user_entry", None)
        has_text = bool(entry and entry.toPlainText().strip())
        staged_count = len(getattr(self.gui, "staged_image_data", []) or [])
        self._view_model.dispatch(ChatInputChanged(has_text, staged_count))

    def _refresh_conversation_title(self):
        if self._conversation_title_label is None:
            return

        combo = getattr(self.gui, "chat_character_combobox", None)
        char_id = combo.currentText().strip() if combo is not None else ""
        if not char_id or char_id == "...":
            char_id = ""
        self._conversation_title_label.setText(
            _("Разговор с ", "Conversation with ") + (char_id or _("персонажем", "character"))
        )

    def on_activated(self):
        self._view_model.dispatch(ChatPanelActivated())

    def _open_block_settings(self):
        category = getattr(self.gui, "_composer_block_category", "api") or "api"
        try:
            if hasattr(self.gui, "switch_main_page"):
                self.gui.switch_main_page("settings")
            if hasattr(self.gui, "show_settings_category"):
                self.gui.show_settings_category(category, force=True)
        except Exception as exc:
            logger.error(f"Failed to open settings from composer warning: {exc}", exc_info=True)

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

        history_button = QPushButton()
        tr_set(history_button, "История", "History", "setText")
        history_button.setObjectName("ChatStripGhostButton")
        history_button.setIcon(qta.icon("fa6s.database", color="#ffd2ec"))
        history_button.setCursor(Qt.CursorShape.PointingHandCursor)
        tr_set(history_button, "Открыть базу истории персонажа", "Open character history database", "setToolTip")
        history_button.clicked.connect(self._open_character_history)
        layout.addWidget(history_button, 0, Qt.AlignmentFlag.AlignVCenter)

        refresh_button = QPushButton()
        tr_set(refresh_button, "Обновить", "Refresh", "setText")
        refresh_button.setObjectName("ChatStripGhostButton")
        refresh_button.setIcon(qta.icon("fa6s.rotate", color="#ffd2ec"))
        refresh_button.setCursor(Qt.CursorShape.PointingHandCursor)
        tr_set(refresh_button, "Загрузить историю чата", "Load chat history", "setToolTip")
        refresh_button.clicked.connect(self.gui.load_chat_history)
        layout.addWidget(refresh_button, 0, Qt.AlignmentFlag.AlignVCenter)

        clear_button = QPushButton()
        tr_set(clear_button, "Очистить чат", "Clear chat", "setText")
        clear_button.setObjectName("ChatStripGhostButton")
        clear_button.setIcon(qta.icon("fa6s.trash", color="#ffd2ec"))
        clear_button.setCursor(Qt.CursorShape.PointingHandCursor)
        clear_button.clicked.connect(self.gui.clear_chat_display)
        layout.addWidget(clear_button, 0, Qt.AlignmentFlag.AlignVCenter)

        return strip

    def _open_character_history(self):
        combo = getattr(self.gui, "chat_character_combobox", None)
        character_id = combo.currentText().strip() if combo is not None else ""
        self._view_model.dispatch(ChatOpenHistoryRequested(character_id))

    def _build_composer(self) -> QWidget:
        wrapper = QWidget()
        wrapper.setObjectName("ChatComposerWrapper")
        wrapper_layout = QVBoxLayout(wrapper)
        wrapper_layout.setContentsMargins(0, 0, 0, 0)
        wrapper_layout.setSpacing(4)

        bar = QFrame()
        bar.setObjectName("ChatComposerBar")
        bar_layout = QHBoxLayout(bar)
        bar_layout.setContentsMargins(12, 6, 6, 6)
        bar_layout.setSpacing(4)

        self.gui.attach_button = QPushButton(qta.icon("fa6s.paperclip", color="#a0a0b4", scale_factor=0.75), "")
        self.gui.attach_button.setObjectName("ChatComposerIconBtn")
        self.gui.attach_button.clicked.connect(lambda: attach_images(self.gui))
        self.gui.attach_button.setFixedSize(32, 32)
        self.gui.attach_button.setCursor(Qt.CursorShape.PointingHandCursor)
        tr_set(self.gui.attach_button, "Прикрепить изображения", "Attach images", "setToolTip")
        bar_layout.addWidget(self.gui.attach_button, 0, Qt.AlignmentFlag.AlignVCenter)

        self.gui.user_entry = QTextEdit()
        self.gui.user_entry.setMinimumHeight(24)
        self.gui.user_entry.setMaximumHeight(80)
        self.gui.user_entry.setFixedHeight(36)
        tr_set(self.gui.user_entry, "Напиши что-нибудь Crazy Mita…", "Write something to Mita…", "setPlaceholderText")
        self.gui.user_entry.setStyleSheet(
            "QTextEdit { background-color: transparent; border: none; color: #f7edf5; padding: 4px 2px; }"
            "QTextEdit:focus { background-color: transparent; border: none; }"
        )
        self.gui.user_entry.textChanged.connect(lambda: adjust_input_height(self.gui))
        self.gui.user_entry.textChanged.connect(lambda: update_send_button_state(self.gui))
        self.gui.user_entry.installEventFilter(self.gui)
        bar_layout.addWidget(self.gui.user_entry, 1)

        self.gui.send_screen_button = QPushButton(qta.icon("fa6s.camera", color="#a0a0b4", scale_factor=0.75), "")
        self.gui.send_screen_button.setObjectName("ChatComposerIconBtn")
        self.gui.send_screen_button.clicked.connect(lambda: send_screen_capture(self.gui))
        self.gui.send_screen_button.setFixedSize(32, 32)
        self.gui.send_screen_button.setCursor(Qt.CursorShape.PointingHandCursor)
        tr_set(self.gui.send_screen_button, "Сделать скриншот экрана", "Take screenshot", "setToolTip")
        bar_layout.addWidget(self.gui.send_screen_button, 0, Qt.AlignmentFlag.AlignVCenter)

        self.gui.send_button = QPushButton(qta.icon("fa6s.paper-plane", color="white", scale_factor=0.85), "")
        self.gui.send_button.setObjectName("ChatSendButtonPill")
        self.gui.send_button.clicked.connect(self.gui.send_message)
        self.gui.send_button.setFixedSize(38, 38)
        self.gui.send_button.setCursor(Qt.CursorShape.PointingHandCursor)
        tr_set(self.gui.send_button, "Отправить сообщение", "Send message", "setToolTip")
        bar_layout.addWidget(self.gui.send_button, 0, Qt.AlignmentFlag.AlignVCenter)

        wrapper_layout.addWidget(bar)
        self.gui.composer_bar = bar

        # (#5) Предупреждение вместо строки ввода, когда нельзя отправлять
        # (не настроен пресет / нет набора промптов). По умолчанию скрыто —
        # refresh_composer_state() покажет при необходимости.
        warning = QFrame()
        warning.setObjectName("ChatComposerBar")
        warn_layout = QHBoxLayout(warning)
        warn_layout.setContentsMargins(12, 6, 6, 6)
        warn_layout.setSpacing(8)
        warn_icon = QLabel()
        warn_icon.setPixmap(qta.icon("fa6s.triangle-exclamation", color="#ffb454").pixmap(18, 18))
        warn_layout.addWidget(warn_icon, 0, Qt.AlignmentFlag.AlignVCenter)
        self.gui.composer_warning_label = QLabel("")
        self.gui.composer_warning_label.setObjectName("ComposerWarningLabel")
        self.gui.composer_warning_label.setWordWrap(True)
        self.gui.composer_warning_label.setStyleSheet("color:#ffd2a0;")
        warn_layout.addWidget(self.gui.composer_warning_label, 1, Qt.AlignmentFlag.AlignVCenter)
        warn_settings_btn = QPushButton()
        warn_settings_btn.setObjectName("ChatComposerIconBtn")
        warn_settings_btn.setIcon(qta.icon("fa6s.gear", color="#ffd2ec"))
        warn_settings_btn.setFixedSize(32, 32)
        warn_settings_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        tr_set(warn_settings_btn, "Открыть настройки", "Open settings", "setToolTip")
        warn_settings_btn.clicked.connect(self._open_block_settings)
        warn_layout.addWidget(warn_settings_btn, 0, Qt.AlignmentFlag.AlignVCenter)
        warning.setVisible(False)
        self.gui.composer_warning = warning
        wrapper_layout.addWidget(warning)

        token_row = QHBoxLayout()
        token_row.setContentsMargins(6, 0, 8, 0)
        token_row.addStretch()
        self.gui.token_count_label = QLabel(_("Токены: 0/0 | Стоимость: 0.00 ₽", "Tokens: 0/0 | Cost: 0.00 ₽"))
        self.gui.token_count_label.setObjectName("TokenCountLabel")
        token_row.addWidget(self.gui.token_count_label)
        wrapper_layout.addLayout(token_row)

        self.gui.attachment_label = QLabel("")
        self.gui.attachment_label.setVisible(False)
        self.gui.clear_attach_btn = QPushButton("")
        self.gui.clear_attach_btn.setVisible(False)

        return wrapper

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

        on_ready = getattr(self.gui, "_on_chat_ui_ready", None)
        if callable(on_ready):
            on_ready()


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


def refresh_composer_state(gui):
    panel = getattr(gui, "chat_panel", None)
    view_model = getattr(panel, "_view_model", None)
    if view_model is not None:
        view_model.dispatch(ChatPanelActivated())


def refresh_composer_state_sync_legacy(gui):
    refresh_composer_state(gui)


def update_send_button_state(gui):
    panel = getattr(gui, "chat_panel", None)
    if panel is not None:
        panel._dispatch_input_state()


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
    panel = getattr(gui, "chat_panel", None)
    if panel is None:
        return False
    panel._view_model.dispatch(ChatStageImageRequested(bytes(img_bytes)))
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
    panel = getattr(gui, "chat_panel", None)
    if panel is not None:
        panel._view_model.dispatch(ChatStageFilesRequested(tuple(file_paths)))


def clear_staged_images(gui):
    panel = getattr(gui, "chat_panel", None)
    if panel is not None:
        panel._view_model.dispatch(ChatClearStagedRequested())


def send_screen_capture(gui):
    logger.info("Запрошена отправка скриншота.")
    panel = getattr(gui, "chat_panel", None)
    if panel is not None:
        panel._view_model.dispatch(ChatCaptureScreenRequested())


def position_mita_status(gui):
    if not hasattr(gui, "mita_status") or not gui.mita_status:
        return

    chat_viewport = gui.chat_window.viewport().rect()
    status_width = gui.mita_status.width()
    status_height = gui.mita_status.height()
    x = chat_viewport.width() - status_width - 20
    y = chat_viewport.height() - status_height - 20
    gui.mita_status.move(gui.chat_window.mapToParent(QPoint(x, y)))
