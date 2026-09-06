from __future__ import annotations

import base64

import qtawesome as qta

from PyQt6.QtCore import QBuffer, QEvent, QIODevice, QPoint, QRectF, QSize, Qt
from PyQt6.QtGui import QColor, QIcon, QKeyEvent, QPainter, QPixmap
from PyQt6.QtWidgets import (
    QApplication,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from localization.live import tr_set
from ui.chat.chat_widget import ChatWidget
from ui.chat.dialogue_presentation import format_conversation_title, format_runtime_source
from ui.widgets.chat_panel_presentation import (
    ChatCaptureScreenRequested,
    ChatClearStagedRequested,
    ChatImagesStaged,
    ChatInputChanged,
    ChatOpenHistoryRequested,
    ChatPanelActions,
    ChatPanelActivated,
    ChatPanelState,
    ChatShowError,
    ChatStageFilesRequested,
    ChatStageImageRequested,
    ChatStagedCleared,
)
from ui.widgets.image_preview_widget import ImagePreviewBar
from ui.widgets.mita_status_widget import MitaStatusWidget
from utils import _


class ChatPanel(QWidget):
    """Passive chat surface driven by ``ChatPanelViewModel``.

    The widget owns only Qt presentation state. Application operations are
    represented by typed intents or the narrow shell actions supplied by the
    composition root; no state is exported by mutating the parent window.
    """

    def __init__(
        self,
        parent: QWidget,
        view_model,
        actions: ChatPanelActions,
    ) -> None:
        super().__init__(parent)
        self._view_model = view_model
        self._actions = actions
        self._state: ChatPanelState = view_model.state
        self._staged_images: list[bytes] = []
        self._conversation_title_label: QLabel | None = None
        self._conversation_source_label: QLabel | None = None
        self.image_preview_bar: ImagePreviewBar | None = None

        self.attach_button: QPushButton
        self.user_entry: QTextEdit
        self.send_screen_button: QPushButton
        self.send_button: QPushButton
        self.composer_bar: QFrame
        self.composer_warning: QFrame
        self.composer_warning_label: QLabel
        self.token_count_label: QLabel
        self.attachment_label: QLabel
        self.clear_attach_btn: QPushButton
        self.chat_window: ChatWidget
        self.scroll_to_bottom_btn = None
        self.scroll_to_bottom_anim = None
        self.mita_status: MitaStatusWidget

        self.setObjectName("ChatWorkspace")
        self._build_ui()
        self._view_model.state_changed.connect(self.render)
        self._view_model.effect_emitted.connect(self._handle_effect)
        self.destroyed.connect(lambda *_: self._view_model.close())
        self.render(self._state)
        self._actions.surface_ready(self)

    @property
    def staged_images(self) -> list[bytes]:
        return self._staged_images

    def staged_images_snapshot(self) -> list[bytes]:
        return list(self._staged_images)

    def render(self, state: ChatPanelState) -> None:
        self._state = state
        if self._conversation_title_label is not None:
            self._conversation_title_label.setText(
                format_conversation_title(state.dialogue_snapshot, state.character_id)
            )
        if self._conversation_source_label is not None:
            source_label = format_runtime_source(state.dialogue_snapshot)
            self._conversation_source_label.setText(source_label)
            self._conversation_source_label.setVisible(bool(source_label))
        self.composer_warning_label.setText(state.warning)
        self.composer_bar.setVisible(not state.blocked)
        self.composer_warning.setVisible(state.blocked)
        cancel_mode = state.active_generation_count > 0
        self._set_send_button_mode(cancel_mode)
        self.send_button.setEnabled(cancel_mode or bool(state.can_send))

    def _set_send_button_mode(self, cancel_mode: bool) -> None:
        if bool(self.send_button.property("cancelMode")) == cancel_mode:
            return
        self.send_button.setProperty("cancelMode", cancel_mode)
        if cancel_mode:
            self.send_button.setIcon(self._stop_icon())
            self.send_button.setIconSize(QSize(20, 20))
            self.send_button.setToolTip(_("Остановить генерацию", "Stop generation"))
        else:
            self.send_button.setIcon(
                qta.icon("fa6s.paper-plane", color="white", scale_factor=0.85)
            )
            self.send_button.setIconSize(QSize(18, 18))
            self.send_button.setToolTip(_("Отправить сообщение", "Send message"))
        self.send_button.style().unpolish(self.send_button)
        self.send_button.style().polish(self.send_button)

    @staticmethod
    def _stop_icon() -> QIcon:
        pixmap = QPixmap(20, 20)
        pixmap.fill(Qt.GlobalColor.transparent)
        painter = QPainter(pixmap)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor("#ffffff"))
        painter.drawRoundedRect(QRectF(2.0, 2.0, 16.0, 16.0), 3.0, 3.0)
        painter.end()
        return QIcon(pixmap)

    def _on_send_button_clicked(self) -> None:
        if self._state.active_generation_count > 0:
            self._actions.cancel_active_generations()
            return
        self._actions.send_message()

    def _handle_effect(self, effect) -> None:
        if isinstance(effect, ChatImagesStaged):
            for image in effect.images:
                payload = bytes(image)
                self._staged_images.append(payload)
                self.image_preview_bar.add_image(payload)
            self.image_preview_bar.setVisible(bool(self._staged_images))
            self._dispatch_input_state()
            return
        if isinstance(effect, ChatStagedCleared):
            self.clear_staged_images_view()
            return
        if isinstance(effect, ChatShowError):
            QMessageBox.warning(self, effect.title, effect.message)

    def on_activated(self) -> None:
        self._view_model.dispatch(ChatPanelActivated())

    def refresh_state(self) -> None:
        self._view_model.dispatch(ChatPanelActivated())

    def clear_staged_images(self) -> None:
        self._view_model.dispatch(ChatClearStagedRequested())

    def clear_staged_images_view(self) -> None:
        self._staged_images.clear()
        self.image_preview_bar.clear()
        self.image_preview_bar.hide()
        self._dispatch_input_state()

    def reposition_status(self) -> None:
        viewport = self.chat_window.viewport().rect()
        x = viewport.width() - self.mita_status.width() - 20
        y = viewport.height() - self.mita_status.height() - 20
        self.mita_status.move(self.chat_window.mapToParent(QPoint(x, y)))

    def reposition_scroll_button(self) -> None:
        reposition = getattr(self.chat_window, "_reposition_scroll_button", None)
        if callable(reposition):
            reposition()

    def eventFilter(self, obj, event):
        chat_window = getattr(self, "chat_window", None)
        user_entry = getattr(self, "user_entry", None)
        if (
            chat_window is not None
            and obj == chat_window.viewport()
            and event.type() in (QEvent.Type.Resize, QEvent.Type.Paint)
        ):
            self.reposition_scroll_button()
        elif (
            chat_window is not None
            and obj == chat_window
            and event.type() == QEvent.Type.Resize
        ):
            self.reposition_status()
        elif (
            user_entry is not None
            and obj == user_entry
            and event.type() == QEvent.Type.KeyPress
        ):
            if not isinstance(event, QKeyEvent):
                return super().eventFilter(obj, event)
            key = event.key()
            modifiers = event.modifiers()
            paste_shortcut = (
                key == Qt.Key.Key_V
                and modifiers
                & (
                    Qt.KeyboardModifier.ControlModifier
                    | Qt.KeyboardModifier.MetaModifier
                )
            ) or (
                key == Qt.Key.Key_Insert
                and modifiers & Qt.KeyboardModifier.ShiftModifier
            )
            if paste_shortcut and self._stage_clipboard_image():
                return True
            if key in (Qt.Key.Key_Return, Qt.Key.Key_Enter) and not (
                modifiers & Qt.KeyboardModifier.ShiftModifier
            ):
                self._actions.send_message()
                return True
        return super().eventFilter(obj, event)

    def _dispatch_input_state(self) -> None:
        self._view_model.dispatch(
            ChatInputChanged(
                bool(self.user_entry.toPlainText().strip()),
                len(self._staged_images),
            )
        )

    def _adjust_input_height(self) -> None:
        height = int(self.user_entry.document().size().height() + 10)
        self.user_entry.setFixedHeight(max(36, min(height, 80)))

    def _open_block_settings(self) -> None:
        self._actions.open_settings(self._state.settings_category or "api")

    def _open_character_history(self) -> None:
        self._view_model.dispatch(
            ChatOpenHistoryRequested(str(self._state.character_id or ""))
        )

    def _attach_images(self) -> None:
        paths, _selected_filter = QFileDialog.getOpenFileNames(
            self,
            _("Выберите изображения", "Select Images"),
            "",
            _(
                "Файлы изображений (*.png *.jpg *.jpeg *.webp *.bmp *.gif)",
                "Image Files (*.png *.jpg *.jpeg *.webp *.bmp *.gif)",
            ),
        )
        if paths:
            self._view_model.dispatch(ChatStageFilesRequested(tuple(paths)))

    def _stage_clipboard_image(self) -> bool:
        clipboard = QApplication.clipboard()
        if not clipboard.mimeData().hasImage():
            return False
        image = clipboard.image()
        if image.isNull():
            return False
        buffer = QBuffer()
        buffer.open(QIODevice.OpenModeFlag.WriteOnly)
        image.save(buffer, "PNG")
        self._view_model.dispatch(ChatStageImageRequested(bytes(buffer.data())))
        return True

    def _remove_staged_image(self, index: int) -> None:
        if not 0 <= index < len(self._staged_images):
            return
        self._staged_images.pop(index)
        self.image_preview_bar.remove_at(index)
        self.image_preview_bar.setVisible(bool(self._staged_images))
        self._dispatch_input_state()

    def _show_full_image(self, image_data) -> None:
        if isinstance(image_data, str) and image_data.startswith("data:image"):
            try:
                image_data = base64.b64decode(image_data.split(",", 1)[1])
            except Exception:
                return
        if isinstance(image_data, (bytes, bytearray)):
            self._actions.show_image(bytes(image_data))

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

        source_label = QLabel("")
        source_label.setObjectName("ChatStripSourceBadge")
        source_label.setVisible(False)
        layout.addWidget(source_label, 0, Qt.AlignmentFlag.AlignVCenter)
        self._conversation_source_label = source_label
        layout.addStretch(1)

        history_button = QPushButton()
        tr_set(history_button, "История", "History", "setText")
        history_button.setObjectName("ChatStripGhostButton")
        history_button.setIcon(qta.icon("fa6s.database", color="#ffd2ec"))
        history_button.setCursor(Qt.CursorShape.PointingHandCursor)
        tr_set(
            history_button,
            "Открыть базу истории персонажа",
            "Open character history database",
            "setToolTip",
        )
        history_button.clicked.connect(self._open_character_history)
        layout.addWidget(history_button, 0, Qt.AlignmentFlag.AlignVCenter)

        refresh_button = QPushButton()
        tr_set(refresh_button, "Обновить", "Refresh", "setText")
        refresh_button.setObjectName("ChatStripGhostButton")
        refresh_button.setIcon(qta.icon("fa6s.rotate", color="#ffd2ec"))
        refresh_button.setCursor(Qt.CursorShape.PointingHandCursor)
        refresh_button.clicked.connect(self._actions.reload_history)
        layout.addWidget(refresh_button, 0, Qt.AlignmentFlag.AlignVCenter)

        clear_button = QPushButton()
        tr_set(clear_button, "Очистить чат", "Clear chat", "setText")
        clear_button.setObjectName("ChatStripGhostButton")
        clear_button.setIcon(qta.icon("fa6s.trash", color="#ffd2ec"))
        clear_button.setCursor(Qt.CursorShape.PointingHandCursor)
        clear_button.clicked.connect(self._actions.clear_chat)
        layout.addWidget(clear_button, 0, Qt.AlignmentFlag.AlignVCenter)
        return strip

    def _build_composer(self) -> QWidget:
        wrapper = QWidget()
        wrapper.setObjectName("ChatComposerWrapper")
        layout = QVBoxLayout(wrapper)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)

        self.composer_bar = QFrame()
        self.composer_bar.setObjectName("ChatComposerBar")
        bar_layout = QHBoxLayout(self.composer_bar)
        bar_layout.setContentsMargins(12, 6, 6, 6)
        bar_layout.setSpacing(4)

        self.attach_button = QPushButton(
            qta.icon("fa6s.paperclip", color="#a0a0b4", scale_factor=0.75), ""
        )
        self.attach_button.setObjectName("ChatComposerIconBtn")
        self.attach_button.clicked.connect(self._attach_images)
        self.attach_button.setFixedSize(32, 32)
        self.attach_button.setCursor(Qt.CursorShape.PointingHandCursor)
        tr_set(
            self.attach_button,
            "Прикрепить изображения",
            "Attach images",
            "setToolTip",
        )
        bar_layout.addWidget(self.attach_button, 0, Qt.AlignmentFlag.AlignVCenter)

        self.user_entry = QTextEdit()
        self.user_entry.setMinimumHeight(24)
        self.user_entry.setMaximumHeight(80)
        self.user_entry.setFixedHeight(36)
        tr_set(
            self.user_entry,
            "Напиши что-нибудь Мите…",
            "Write something to Mita…",
            "setPlaceholderText",
        )
        self.user_entry.setStyleSheet(
            "QTextEdit { background-color: transparent; border: none; "
            "color: #f7edf5; padding: 4px 2px; }"
            "QTextEdit:focus { background-color: transparent; border: none; }"
        )
        self.user_entry.textChanged.connect(self._adjust_input_height)
        self.user_entry.textChanged.connect(self._dispatch_input_state)
        self.user_entry.installEventFilter(self)
        bar_layout.addWidget(self.user_entry, 1)

        self.send_screen_button = QPushButton(
            qta.icon("fa6s.camera", color="#a0a0b4", scale_factor=0.75), ""
        )
        self.send_screen_button.setObjectName("ChatComposerIconBtn")
        self.send_screen_button.clicked.connect(
            lambda: self._view_model.dispatch(ChatCaptureScreenRequested())
        )
        self.send_screen_button.setFixedSize(32, 32)
        self.send_screen_button.setCursor(Qt.CursorShape.PointingHandCursor)
        tr_set(
            self.send_screen_button,
            "Сделать скриншот экрана",
            "Take screenshot",
            "setToolTip",
        )
        bar_layout.addWidget(
            self.send_screen_button, 0, Qt.AlignmentFlag.AlignVCenter
        )

        self.send_button = QPushButton(
            qta.icon("fa6s.paper-plane", color="white", scale_factor=0.85), ""
        )
        self.send_button.setObjectName("ChatSendButtonPill")
        self.send_button.clicked.connect(self._on_send_button_clicked)
        self.send_button.setFixedSize(42, 42)
        self.send_button.setIconSize(QSize(18, 18))
        self.send_button.setCursor(Qt.CursorShape.PointingHandCursor)
        tr_set(
            self.send_button,
            "Отправить сообщение",
            "Send message",
            "setToolTip",
        )
        bar_layout.addWidget(self.send_button, 0, Qt.AlignmentFlag.AlignVCenter)
        layout.addWidget(self.composer_bar)

        self.image_preview_bar = ImagePreviewBar(wrapper)
        self.image_preview_bar.thumbnail_clicked.connect(self._show_full_image)
        self.image_preview_bar.remove_requested.connect(self._remove_staged_image)
        self.image_preview_bar.hide()
        layout.addWidget(self.image_preview_bar)

        self.composer_warning = QFrame()
        self.composer_warning.setObjectName("ChatComposerBar")
        warning_layout = QHBoxLayout(self.composer_warning)
        warning_layout.setContentsMargins(12, 6, 6, 6)
        warning_layout.setSpacing(8)
        warning_icon = QLabel()
        warning_icon.setPixmap(
            qta.icon("fa6s.triangle-exclamation", color="#ffb454").pixmap(18, 18)
        )
        warning_layout.addWidget(warning_icon, 0, Qt.AlignmentFlag.AlignVCenter)
        self.composer_warning_label = QLabel("")
        self.composer_warning_label.setObjectName("ComposerWarningLabel")
        self.composer_warning_label.setWordWrap(True)
        self.composer_warning_label.setStyleSheet("color:#ffd2a0;")
        warning_layout.addWidget(
            self.composer_warning_label, 1, Qt.AlignmentFlag.AlignVCenter
        )
        warning_settings = QPushButton()
        warning_settings.setObjectName("ChatComposerIconBtn")
        warning_settings.setIcon(qta.icon("fa6s.gear", color="#ffd2ec"))
        warning_settings.setFixedSize(32, 32)
        warning_settings.setCursor(Qt.CursorShape.PointingHandCursor)
        warning_settings.clicked.connect(self._open_block_settings)
        warning_layout.addWidget(
            warning_settings, 0, Qt.AlignmentFlag.AlignVCenter
        )
        self.composer_warning.hide()
        layout.addWidget(self.composer_warning)

        token_row = QHBoxLayout()
        token_row.setContentsMargins(6, 0, 8, 0)
        token_row.addStretch()
        # Заглушка до первого пересчёта — без выдуманной стоимости в рублях
        # (реальное значение подставит update_token_count).
        self.token_count_label = QLabel(
            _(
                "Контекст: подсчёт…",
                "Context: estimating…",
            )
        )
        self.token_count_label.setObjectName("TokenCountLabel")
        token_row.addWidget(self.token_count_label)
        layout.addLayout(token_row)

        self.attachment_label = QLabel("")
        self.attachment_label.hide()
        self.clear_attach_btn = QPushButton("")
        self.clear_attach_btn.hide()
        return wrapper

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(12)
        layout.addWidget(self._build_conversation_strip())

        self.chat_window = ChatWidget()
        self.chat_window.setObjectName("ChatScrollArea")
        self.chat_window.installEventFilter(self)
        self.chat_window.viewport().installEventFilter(self)
        layout.addWidget(self.chat_window, 1)
        self.scroll_to_bottom_btn = self.chat_window._scroll_btn
        self.scroll_to_bottom_anim = self.chat_window._scroll_btn._opacity_anim
        self.mita_status = MitaStatusWidget(self.chat_window)

        layout.addWidget(self._build_composer())
