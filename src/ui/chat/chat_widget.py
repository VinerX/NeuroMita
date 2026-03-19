"""
ChatWidget — QScrollArea-based chat container.

Replaces QTextBrowser with a vertical list of MessageWidget instances
inside a scroll area, giving proper widget-level control over layout.
"""

from PyQt6.QtWidgets import (
    QScrollArea, QWidget, QVBoxLayout, QScrollBar, QPushButton,
    QGraphicsOpacityEffect,
)
from PyQt6.QtCore import Qt, QPropertyAnimation, QPoint, QTimer
import qtawesome as qta


class ChatWidget(QScrollArea):
    """Scrollable container that hosts message widgets vertically."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWidgetResizable(True)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.setObjectName("ChatScrollArea")

        # Inner container
        self._container = QWidget()
        self._container.setObjectName("ChatContainer")
        self._layout = QVBoxLayout(self._container)
        self._layout.setContentsMargins(6, 6, 6, 6)
        self._layout.setSpacing(4)
        self._layout.addStretch()  # push messages to top initially
        self.setWidget(self._container)

        # Track whether user was at bottom before adding content
        self._auto_scroll = True
        self.verticalScrollBar().valueChanged.connect(self._on_scroll)
        self.verticalScrollBar().rangeChanged.connect(self._on_range_changed)

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
            # Insert before the trailing stretch
            idx = self._layout.count() - 1  # before stretch
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
        bar = self.verticalScrollBar()
        bar.setValue(bar.maximum())

    def message_count(self) -> int:
        return len(self._messages)

    # ── Scroll management ───────────────────────────────────────────────────

    def _on_scroll(self):
        bar = self.verticalScrollBar()
        self._auto_scroll = bar.value() >= bar.maximum() - 20
        self._update_scroll_button()

    def _on_range_changed(self):
        if self._auto_scroll:
            QTimer.singleShot(5, self.scroll_to_bottom)

    def _update_scroll_button(self):
        bar = self.verticalScrollBar()
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
        vp = self.viewport()
        x = vp.width() - self._scroll_btn.width() - margin
        y = vp.height() - self._scroll_btn.height() - margin
        self._scroll_btn.move(QPoint(max(0, x), max(0, y)))

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._reposition_scroll_button()

    # ── Scroll button ───────────────────────────────────────────────────────

    def _create_scroll_button(self) -> QPushButton:
        btn = QPushButton(qta.icon('fa6s.angle-down', color='white'), '', self)
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
