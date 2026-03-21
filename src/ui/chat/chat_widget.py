"""
ChatWidget — QScrollArea-based chat container.

Replaces QTextBrowser with a vertical list of MessageWidget instances
inside a scroll area, giving proper widget-level control over layout.
"""

from PyQt6.QtWidgets import (
    QScrollArea, QWidget, QVBoxLayout, QHBoxLayout, QScrollBar, QPushButton,
    QGraphicsOpacityEffect, QLabel, QFrame,
)
from PyQt6.QtCore import Qt, QPropertyAnimation, QPoint, QTimer, QRectF
from PyQt6.QtGui import QPainter, QPainterPath, QColor, QBrush
import qtawesome as qta

_PANEL_BG = "rgba(18,18,22,0.92)"
_PANEL_BG_COLOR = QColor(18, 18, 22, 234)  # 0.92 * 255 ≈ 234


class RoundedScrollArea(QScrollArea):
    """QScrollArea with truly rounded corners (clips content)."""

    def __init__(self, radius: int = 12, parent=None):
        super().__init__(parent)
        self._radius = radius

    def paintEvent(self, event):
        painter = QPainter(self.viewport())
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        path = QPainterPath()
        path.addRoundedRect(QRectF(self.viewport().rect()), self._radius, self._radius)
        painter.setClipPath(path)
        painter.setBrush(QBrush(_PANEL_BG_COLOR))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.drawRoundedRect(QRectF(self.viewport().rect()), self._radius, self._radius)
        painter.end()
        super().paintEvent(event)


class ChatWidget(QFrame):
    """
    Rounded chat container with scroll area + typing indicator inside scroll.

    Layout (inside scroll container):
      [stretch]
      [messages...]
      [TypingIndicator]  (hidden by default, no space when hidden)
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("ChatWidgetFrame")
        self.setStyleSheet(f"""
            QFrame#ChatWidgetFrame {{
                background-color: {_PANEL_BG};
                border: 1px solid rgba(255,255,255,0.08);
                border-radius: 12px;
            }}
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
        typing_layout.addWidget(self._typing_label)
        typing_layout.addStretch()

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

        if self._auto_scroll and not at_start:
            QTimer.singleShot(10, self.scroll_to_bottom)

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
        self._typing_label.setText(f"{name} печатает...")
        if avatar_pixmap and not avatar_pixmap.isNull():
            from PyQt6.QtGui import QPixmap
            scaled = avatar_pixmap.scaled(24, 24,
                Qt.AspectRatioMode.KeepAspectRatioByExpanding,
                Qt.TransformationMode.SmoothTransformation)
            self._typing_avatar.setPixmap(scaled)
            self._typing_avatar.show()
        else:
            self._typing_avatar.hide()
        self._typing_bar.setMaximumHeight(32)
        self._typing_bar.show()
        if self._auto_scroll:
            QTimer.singleShot(10, self.scroll_to_bottom)

    def hide_typing(self):
        self._typing_bar.setMaximumHeight(0)
        self._typing_bar.hide()

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

    def _fade_button(self, target: float):
        anim = self._scroll_btn._opacity_anim
        anim.stop()
        eff = self._scroll_btn.graphicsEffect()
        anim.setStartValue(eff.opacity() if eff else 1.0)
        anim.setEndValue(target)
        anim.start()
        if target == 0.0:
            anim.finished.connect(
                lambda: self._scroll_btn.hide() if self._scroll_btn.graphicsEffect().opacity() < 0.05 else None
            )

    def _reposition_scroll_button(self):
        margin = 12
        vp = self._scroll.viewport()
        x = vp.width() - self._scroll_btn.width() - margin
        y = vp.height() - self._scroll_btn.height() - margin
        self._scroll_btn.move(QPoint(max(0, x), max(0, y)))

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._reposition_scroll_button()

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
