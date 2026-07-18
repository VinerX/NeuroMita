"""
ChatWidget — QScrollArea-based chat container.

Replaces QTextBrowser with a vertical list of MessageWidget instances
inside a scroll area, giving proper widget-level control over layout.
"""

from PyQt6.QtWidgets import (
    QScrollArea, QWidget, QVBoxLayout, QHBoxLayout, QScrollBar, QPushButton,
    QGraphicsOpacityEffect, QLabel, QFrame, QSizePolicy,
)
from PyQt6.QtCore import Qt, QPropertyAnimation, QPoint, QTimer, QRectF, pyqtSignal
from PyQt6.QtGui import QPainter, QPainterPath, QColor, QBrush, QBitmap, QRegion, QLinearGradient, QPen
import qtawesome as qta
from styles.main_styles import get_theme
from utils import getTranslationVariant as _tr

_THEME = get_theme()
_PANEL_BG = f"rgba({_THEME['sandbox_bg_rgb']}, 0.96)"
_PANEL_BG_COLOR = QColor(8, 8, 18, 245)

MAX_DISPLAYED_MESSAGES = 100  # older widgets are deleted when this limit is exceeded


class RoundedScrollArea(QScrollArea):
    """QScrollArea — background painted normally; outer clipping handled by ChatWidget mask."""

    def __init__(self, radius: int = 12, parent=None):
        super().__init__(parent)
        self._radius = radius


class ChatWidget(QFrame):
    """
    Rounded chat container with scroll area + typing indicator inside scroll.

    Layout (inside scroll container):
      [stretch]
      [messages...]
      [TypingIndicator]  (hidden by default, no space when hidden)
    """

    status_dismissed = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("ChatWidgetFrame")
        self.setStyleSheet("""
            QFrame#ChatWidgetFrame {
                background: transparent;
                border: none;
            }
        """)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        # ── Scroll area ──────────────────────────────────────────────────────
        self._scroll = RoundedScrollArea(radius=12)
        self._scroll.setWidgetResizable(True)
        self._scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self._scroll.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self._scroll.setObjectName("ChatScrollArea")
        self._scroll.setStyleSheet(f"""
            QScrollArea#ChatScrollArea {{
                background-color: {_PANEL_BG};
                border: none;
            }}
        """)
        self._scroll.viewport().setStyleSheet(f"background-color: {_PANEL_BG};")

        # Inner container
        self._container = QWidget()
        self._container.setObjectName("ChatContainer")
        self._container.setStyleSheet(f"background-color: {_PANEL_BG};")
        self._layout = QVBoxLayout(self._container)
        self._layout.setContentsMargins(6, 6, 6, 6)
        self._layout.setSpacing(4)
        self._layout.addStretch()  # push messages to top initially

        # ── Typing indicator (inside scroll area, at bottom of messages) ─────
        self._typing_bar = QWidget()
        self._typing_bar.setObjectName("TypingBar")
        self._typing_bar.setStyleSheet("QWidget#TypingBar { background-color: transparent; }")
        # Start with max-height=0 so it takes no space when hidden
        self._typing_bar.setMinimumHeight(0)
        self._typing_bar.setMaximumHeight(0)
        typing_layout = QHBoxLayout(self._typing_bar)
        typing_layout.setContentsMargins(8, 4, 8, 4)
        typing_layout.setSpacing(6)

        self._typing_avatar = QLabel()
        self._typing_avatar.setFixedSize(24, 24)
        self._typing_avatar.setStyleSheet("background: transparent; border: none;")
        typing_layout.addWidget(self._typing_avatar)

        self._typing_label = QLabel()
        self._typing_label.setStyleSheet(
            "color: rgba(180,180,195,0.75); font-size: 9pt; "
            "background: transparent; border: none;"
        )
        # Длинные ошибки (напр. «провайдер отклонил по региональному
        # ограничению…») не влезали в одну строку и обрезались. Разрешаем
        # перенос и растягиваем метку на всю ширину, крестик уходит вправо.
        self._typing_label.setWordWrap(True)
        _tl_policy = self._typing_label.sizePolicy()
        _tl_policy.setHorizontalPolicy(QSizePolicy.Policy.Expanding)
        _tl_policy.setHeightForWidth(True)
        self._typing_label.setSizePolicy(_tl_policy)
        typing_layout.addWidget(self._typing_label, 1)
        typing_layout.setAlignment(
            self._typing_avatar, Qt.AlignmentFlag.AlignTop
        )

        self._status_close_button = QPushButton("×")
        self._status_close_button.setObjectName("ChatStatusCloseButton")
        self._status_close_button.setFixedSize(22, 22)
        self._status_close_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self._status_close_button.setToolTip(_tr("Закрыть", "Dismiss"))
        self._status_close_button.setStyleSheet(
            "QPushButton#ChatStatusCloseButton {"
            " color: rgba(220,220,230,0.8); background: transparent; border: none;"
            " font-size: 15px; font-weight: 700; padding: 0; }"
            "QPushButton#ChatStatusCloseButton:hover { color: #ffffff; }"
        )
        self._status_close_button.clicked.connect(self._dismiss_status)
        self._status_close_button.hide()
        # Крестик держим у верхней строки, чтобы у многострочной ошибки он не
        # оказывался по вертикальному центру блока.
        typing_layout.addWidget(self._status_close_button, 0, Qt.AlignmentFlag.AlignTop)

        # Add typing bar as last item in scroll container (after stretch + messages)
        self._layout.addWidget(self._typing_bar)
        self._scroll.setWidget(self._container)

        outer.addWidget(self._scroll, 1)

        # Track whether user was at bottom before adding content
        self._auto_scroll = True
        self._scroll.verticalScrollBar().valueChanged.connect(self._on_scroll)
        self._scroll.verticalScrollBar().rangeChanged.connect(self._on_range_changed)

        # Scroll-to-bottom button
        self._scroll_btn = self._create_scroll_button()

        # Message list
        self._messages = []


        # Debounce timer for _apply_mask — avoids bitmap + region alloc on every resize pixel
        self._mask_timer = QTimer(self)
        self._mask_timer.setSingleShot(True)
        self._mask_timer.setInterval(30)
        self._mask_timer.timeout.connect(self._apply_mask)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)

        rect = QRectF(self.rect().adjusted(1, 1, -1, -1))
        path = QPainterPath()
        path.addRoundedRect(rect, 18, 18)

        gradient = QLinearGradient(rect.topLeft(), rect.bottomRight())
        gradient.setColorAt(0.0, QColor(16, 13, 25, 245))
        gradient.setColorAt(0.55, QColor(12, 9, 21, 248))
        gradient.setColorAt(1.0, QColor(8, 8, 18, 250))
        painter.fillPath(path, gradient)

        painter.save()
        painter.setClipPath(path)
        painter.setPen(QPen(QColor(183, 75, 125, 14), 1))
        step = 32
        rl, rt, rr, rb = int(rect.left()), int(rect.top()), int(rect.right()), int(rect.bottom())
        for x in range(rl, rr, step):
            painter.drawLine(x, rt, x, rb)
        for y in range(rt, rb, step):
            painter.drawLine(rl, y, rr, y)
        painter.restore()

        painter.setPen(QPen(QColor(183, 75, 125, 105), 1.15))
        painter.drawPath(path)

    # ── Public API ──────────────────────────────────────────────────────────

    def add_message_widget(self, widget: QWidget, at_start: bool = False):
        """Insert a message widget into the chat. Appends at end by default."""
        if at_start:
            self._layout.insertWidget(0, widget)
            self._messages.insert(0, widget)
        else:
            # Insert before typing bar (last item in layout)
            idx = self._layout.count() - 1
            self._layout.insertWidget(idx, widget)
            self._messages.append(widget)

        # Remove oldest widgets when limit is exceeded to prevent layout slowdown
        while len(self._messages) > MAX_DISPLAYED_MESSAGES:
            old = self._messages.pop(0)
            self._layout.removeWidget(old)
            old.deleteLater()

        if self._auto_scroll and not at_start:
            QTimer.singleShot(10, self.scroll_to_bottom)

    def set_message_voicing(self, message_id, on: bool = True):
        """Показать индикатор «озвучивается» на конкретном пузыре (по message_id)
        и снять с предыдущего. Пузырь с этим id — последний в ответе."""
        self.clear_message_voicing()
        if not message_id or not on:
            return
        for w in self._messages:
            if getattr(w, "_message_id", None) == message_id and hasattr(w, "set_voicing"):
                w.set_voicing(True)
                self._voicing_message_id = message_id
                break

    def clear_message_voicing(self):
        prev = getattr(self, "_voicing_message_id", None)
        if not prev:
            return
        for w in self._messages:
            if getattr(w, "_message_id", None) == prev and hasattr(w, "set_voicing"):
                w.set_voicing(False)
        self._voicing_message_id = None

    def remove_widget(self, widget: QWidget):
        """Remove a specific widget from the chat."""
        if widget in self._messages:
            self._messages.remove(widget)
        self._layout.removeWidget(widget)
        widget.deleteLater()

    def remove_last_n_widgets(self, n: int):
        """Remove the last N widgets from the chat (instantly, no full reload)."""
        for _ in range(min(n, len(self._messages))):
            w = self._messages.pop()
            self._layout.removeWidget(w)
            w.deleteLater()

    def get_last_message(self) -> QWidget | None:
        return self._messages[-1] if self._messages else None

    def clear_messages(self):
        """Remove all message widgets."""
        for w in self._messages:
            self._layout.removeWidget(w)
            w.deleteLater()
        self._messages.clear()

    def scroll_to_bottom(self):
        bar = self._scroll.verticalScrollBar()
        bar.setValue(bar.maximum())

    def message_count(self) -> int:
        return len(self._messages)

    # ── Typing indicator API ─────────────────────────────────────────────────

    def show_typing(self, name: str, avatar_pixmap=None):
        """Show typing indicator with character name and optional avatar."""
        self._status_close_button.hide()
        self._typing_label.setText(_tr("{} печатает...", "{} is typing...").format(name))
        if avatar_pixmap and not avatar_pixmap.isNull():
            from PyQt6.QtGui import QPixmap
            scaled = avatar_pixmap.scaled(24, 24,
                Qt.AspectRatioMode.KeepAspectRatioByExpanding,
                Qt.TransformationMode.SmoothTransformation)
            self._typing_avatar.setPixmap(scaled)
            self._typing_avatar.show()
        else:
            self._typing_avatar.hide()
        # «Думает» — всегда одна строка: фиксированная высота, без переносов.
        self._typing_bar.setMinimumHeight(0)
        self._typing_bar.setMaximumHeight(32)
        self._typing_bar.show()
        if self._auto_scroll:
            QTimer.singleShot(10, self.scroll_to_bottom)

    def show_status(self, text: str, avatar_pixmap=None, *, dismissible: bool = False):
        """Show a persistent status line without the typing suffix."""
        self._typing_label.setText(str(text or ""))
        if avatar_pixmap and not avatar_pixmap.isNull():
            scaled = avatar_pixmap.scaled(
                24,
                24,
                Qt.AspectRatioMode.KeepAspectRatioByExpanding,
                Qt.TransformationMode.SmoothTransformation,
            )
            self._typing_avatar.setPixmap(scaled)
            self._typing_avatar.show()
        else:
            self._typing_avatar.hide()
        self._status_close_button.setVisible(bool(dismissible))
        # Статус (в т.ч. длинная ошибка) может занять несколько строк — снимаем
        # жёсткий потолок в 32px и даём блоку вырасти по содержимому (перенос
        # включён у метки). Потолок держим щедрым, чтобы не обрезать текст.
        self._typing_bar.setMinimumHeight(32)
        self._typing_bar.setMaximumHeight(260)
        self._typing_bar.show()
        self._typing_bar.updateGeometry()
        if self._auto_scroll:
            QTimer.singleShot(10, self.scroll_to_bottom)

    def hide_typing(self):
        self._status_close_button.hide()
        self._typing_bar.setMaximumHeight(0)
        self._typing_bar.hide()

    def _dismiss_status(self):
        self.hide_typing()
        self.status_dismissed.emit()

    # ── Scroll management ───────────────────────────────────────────────────

    def verticalScrollBar(self):
        return self._scroll.verticalScrollBar()

    def _on_scroll(self):
        bar = self._scroll.verticalScrollBar()
        self._auto_scroll = bar.value() >= bar.maximum() - 20
        self._update_scroll_button()

    def _on_range_changed(self):
        if self._auto_scroll:
            QTimer.singleShot(5, self.scroll_to_bottom)

    def _update_scroll_button(self):
        bar = self._scroll.verticalScrollBar()
        at_bottom = bar.value() >= bar.maximum() - 20
        if at_bottom:
            self._fade_button(0.0)
        else:
            self._scroll_btn.show()
            self._fade_button(1.0)
        self._reposition_scroll_button()

    def _on_fade_button_finished(self):
        eff = self._scroll_btn.graphicsEffect()
        if eff and eff.opacity() < 0.05:
            self._scroll_btn.hide()

    def _fade_button(self, target: float):
        anim = self._scroll_btn._opacity_anim
        anim.stop()
        eff = self._scroll_btn.graphicsEffect()
        anim.setStartValue(eff.opacity() if eff else 1.0)
        anim.setEndValue(target)
        anim.start()
        if target == 0.0:
            try:
                anim.finished.disconnect(self._on_fade_button_finished)
            except TypeError:
                pass
            anim.finished.connect(self._on_fade_button_finished)

    def _reposition_scroll_button(self):
        margin = 12
        vp = self._scroll.viewport()
        x = vp.width() - self._scroll_btn.width() - margin
        y = vp.height() - self._scroll_btn.height() - margin
        self._scroll_btn.move(QPoint(max(0, x), max(0, y)))

    def resizeEvent(self, event):
        super().resizeEvent(event)
        # Apply the rounded mask immediately whenever the widget grows in EITHER
        # dimension — otherwise a debounced mask lags behind a taller resize,
        # clipping the widget to its old height (dead space / "ballast" below)
        # and making the bottom edge jitter as resize events stream in.
        # When shrinking, debounce is fine: the old (larger) mask doesn't clip.
        grew = (event.size().width() > event.oldSize().width()
                or event.size().height() > event.oldSize().height())
        if grew:
            self._mask_timer.stop()
            self._apply_mask()
        else:
            self._mask_timer.start()
        self._reposition_scroll_button()

    def _apply_mask(self):
        """Clip widget (and all children) to rounded rect via OS-level bitmap mask."""
        bmp = QBitmap(self.size())
        bmp.fill(Qt.GlobalColor.color0)
        p = QPainter(bmp)
        p.setBrush(Qt.GlobalColor.color1)
        p.setPen(Qt.PenStyle.NoPen)
        p.drawRoundedRect(self.rect(), 12, 12)
        p.end()
        self.setMask(QRegion(bmp))

    def get_layout_parent(self) -> QWidget:
        """Return the widget that owns the message layout (for proper parenting of child widgets)."""
        return self._container

    def viewport(self):
        """Compat: return the scroll area viewport."""
        return self._scroll.viewport()

    # ── Scroll button ───────────────────────────────────────────────────────

    def _create_scroll_button(self) -> QPushButton:
        btn = QPushButton(qta.icon('fa6s.angle-down', color='white'), '', self._scroll)
        btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        btn.setObjectName("ScrollToBottomButton")
        btn.setFixedSize(34, 34)
        btn.setCursor(Qt.CursorShape.PointingHandCursor)
        opacity = QGraphicsOpacityEffect(btn)
        btn.setGraphicsEffect(opacity)
        anim = QPropertyAnimation(opacity, b"opacity", btn)
        anim.setDuration(250)
        btn._opacity_anim = anim
        btn.hide()
        btn.clicked.connect(self.scroll_to_bottom)
        return btn
