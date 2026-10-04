from __future__ import annotations

import qtawesome as qta
from PyQt6.QtCore import (
    QEasingCurve,
    QPropertyAnimation,
    QRect,
    QRectF,
    Qt,
    QTimer,
    pyqtProperty,
    pyqtSignal,
)
from PyQt6.QtGui import QColor, QLinearGradient, QPainter, QPainterPath, QPen
from PyQt6.QtWidgets import QSizePolicy, QToolButton, QVBoxLayout, QWidget

from localization import translate
from localization.live import tr_set, register
from styles.theme import get_theme
from ui.character_names import character_display_name
from ui.chat.message_widget import resolve_character_avatar


class CharacterVoiceTabs(QWidget):
    """Paints avatar tabs and their editor as one animated Chrome-style surface."""

    currentChanged = pyqtSignal(int)
    TAB_HEIGHT = 82
    TAB_WIDTH = 88
    TAB_STEP = 96

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("CharacterVoiceControl")
        self.setMouseTracking(True)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self._characters = None
        self._entries = []
        self._index = 0
        self._active_position = 0.0
        self._scroll_offset = 0.0
        self._hovered = -1
        self._hover = {}
        self._theme = get_theme()
        self._motion = self._animation(b"activePosition", 230)
        self._scroll_motion = self._animation(b"scrollOffset", 180)
        self._hover_timer = QTimer(self)
        self._hover_timer.setInterval(16)
        self._hover_timer.timeout.connect(self._advance_hover)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, self.TAB_HEIGHT + 16, 18, 16)
        self.content = QWidget()
        self.content.setObjectName("CharacterVoiceEditor")
        self.content_layout = QVBoxLayout(self.content)
        self.content_layout.setContentsMargins(0, 0, 0, 0)
        self.content_layout.setSpacing(9)
        layout.addWidget(self.content)
        self._previous = self._scroll_button("left", -1)
        self._next = self._scroll_button("right", 1)
        register(self, lambda w: w._refresh_labels())

    def _tab_label(self, index):
        cid, name, _avatar = self._entries[index]
        return (
            character_display_name(cid, name)
            if cid
            else translate("Общий голос", "Default voice")
        )

    def _refresh_labels(self):
        if self._entries:
            self.setAccessibleDescription(self._tab_label(self._index))
        self.setToolTip(self._tab_label(self._hovered) if self._hovered >= 0 else "")

    def _animation(self, property_name, duration):
        animation = QPropertyAnimation(self, property_name, self)
        animation.setDuration(duration)
        animation.setEasingCurve(QEasingCurve.Type.OutCubic)
        return animation

    def _scroll_button(self, direction, step):
        button = QToolButton(self)
        button.setObjectName("CharacterVoiceScrollButton")
        button.setIcon(
            qta.icon(f"fa5s.chevron-{direction}", color=self._theme["muted"])
        )
        button.setFixedSize(28, 32)
        button.setCursor(Qt.CursorShape.PointingHandCursor)
        tr_set(button, "Прокрутить голоса", "Scroll voices", "setToolTip")
        button.clicked.connect(
            lambda: self._scroll_to(self._scroll_offset + step * self.TAB_STEP * 2)
        )
        return button

    def count(self):
        return len(self._entries)

    def currentIndex(self):
        return self._index

    def tabData(self, index):
        return self._entries[index][0]

    def tabRect(self, index):
        return QRect(
            round(16 + index * self.TAB_STEP - self._scroll_offset),
            6,
            self.TAB_WIDTH,
            self.TAB_HEIGHT - 6,
        )

    def set_characters(self, characters, selected_id):
        if characters != self._characters:
            self._characters = characters
            default = qta.icon("fa5s.users", color=self._theme["muted"]).pixmap(60, 60)
            self._entries = [(None, "Общий голос", default)]
            self._entries.extend(
                (
                    c.character_id,
                    c.display_name,
                    resolve_character_avatar(c.character_id, 60),
                )
                for c in characters
            )
            self._hover.clear()
            self._hovered = -1
        self._motion.stop()
        self._index = next(
            (i for i, entry in enumerate(self._entries) if entry[0] == selected_id), 0
        )
        self._active_position = float(self._index)
        self._ensure_visible(animate=False)
        self._position_buttons()
        self._refresh_labels()
        self.update()

    def setCurrentIndex(self, index):
        if not 0 <= index < self.count() or index == self._index:
            return
        self._index = index
        self._motion.stop()
        self._motion.setStartValue(self._active_position)
        self._motion.setEndValue(float(index))
        self._motion.start()
        self._ensure_visible()
        self.setAccessibleDescription(self._tab_label(index))
        self.currentChanged.emit(index)

    def _get_active_position(self):
        return self._active_position

    def _set_active_position(self, value):
        self._active_position = float(value)
        self.update()

    activePosition = pyqtProperty(float, _get_active_position, _set_active_position)

    def _get_scroll_offset(self):
        return self._scroll_offset

    def _set_scroll_offset(self, value):
        self._scroll_offset = float(value)
        self._position_buttons()
        self.update()

    scrollOffset = pyqtProperty(float, _get_scroll_offset, _set_scroll_offset)

    def _viewport_width(self):
        total = 32 + self.count() * self.TAB_STEP
        return self.width() - 72 if total > self.width() else self.width()

    def _scroll_to(self, target, *, animate=True):
        maximum = max(0, 32 + self.count() * self.TAB_STEP - self._viewport_width())
        target = max(0.0, min(float(maximum), float(target)))
        self._scroll_motion.stop()
        if animate:
            self._scroll_motion.setStartValue(self._scroll_offset)
            self._scroll_motion.setEndValue(target)
            self._scroll_motion.start()
        else:
            self._set_scroll_offset(target)

    def _ensure_visible(self, *, animate=True):
        left = 16 + self._index * self.TAB_STEP
        right = left + self.TAB_WIDTH + 16
        target = self._scroll_offset
        if left < target + 16:
            target = left - 16
        elif right > target + self._viewport_width():
            target = right - self._viewport_width()
        self._scroll_to(target, animate=animate)

    def _position_buttons(self):
        overflow = self._viewport_width() < self.width()
        maximum = max(0, 32 + self.count() * self.TAB_STEP - self._viewport_width())
        self._previous.setVisible(overflow)
        self._next.setVisible(overflow)
        self._previous.move(self.width() - 64, 26)
        self._next.move(self.width() - 32, 26)
        self._previous.setEnabled(self._scroll_offset > 0.5)
        self._next.setEnabled(self._scroll_offset < maximum - 0.5)

    @staticmethod
    def _tab_path(x, width, top, bottom):
        radius = 16
        path = QPainterPath()
        path.moveTo(x - radius, bottom)
        path.quadTo(x, bottom, x, bottom - radius)
        path.lineTo(x, top + radius)
        path.quadTo(x, top, x + radius, top)
        path.lineTo(x + width - radius, top)
        path.quadTo(x + width, top, x + width, top + radius)
        path.lineTo(x + width, bottom - radius)
        path.quadTo(x + width, bottom, x + width + radius, bottom)
        path.closeSubpath()
        return path

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        panel_color = QColor(self._theme["sidebar_panel"])
        inactive_color = QColor(self._theme["control_bg"])
        body = QPainterPath()
        body.addRoundedRect(
            QRectF(
                1,
                self.TAB_HEIGHT,
                self.width() - 2,
                self.height() - self.TAB_HEIGHT - 1,
            ),
            18,
            18,
        )
        active_x = 16 + self._active_position * self.TAB_STEP - self._scroll_offset
        surface = body.united(
            self._tab_path(active_x, self.TAB_WIDTH, 2, self.TAB_HEIGHT + 1)
        )
        painter.save()
        painter.setClipRect(QRectF(0, 0, self._viewport_width(), self.TAB_HEIGHT))
        painter.setPen(Qt.PenStyle.NoPen)
        for i in range(self.count()):
            rect = QRectF(self.tabRect(i)).adjusted(3, 4, -3, -4)
            color = QColor(inactive_color).lighter(
                round(150 + 70 * self._hover.get(i, 0))
            )
            painter.setBrush(color)
            painter.drawRoundedRect(rect, 16, 16)
        painter.restore()
        gradient = QLinearGradient(0, 0, 0, self.height())
        gradient.setColorAt(0, panel_color.lighter(145))
        gradient.setColorAt(1, panel_color.lighter(110))
        painter.setBrush(gradient)
        border = QColor(self._theme["muted"])
        border.setAlpha(38)
        painter.setPen(QPen(border, 1))
        painter.save()
        clip = QPainterPath()
        clip.addRect(QRectF(0, self.TAB_HEIGHT, self.width(), self.height()))
        clip.addRect(QRectF(0, 0, self._viewport_width(), self.TAB_HEIGHT))
        painter.setClipPath(clip)
        painter.drawPath(surface)
        painter.restore()
        painter.save()
        painter.setClipRect(QRectF(0, 0, self._viewport_width(), self.TAB_HEIGHT))
        for i, (_cid, _name, avatar) in enumerate(self._entries):
            selection = max(0.0, 1.0 - abs(i - self._active_position))
            hover = self._hover.get(i, 0)
            size = 50 + 6 * selection + 2 * hover
            center_x = self.tabRect(i).center().x()
            rect = QRectF(center_x - size / 2, 15 - 3 * selection - hover, size, size)
            painter.setOpacity(0.82 + 0.18 * max(selection, hover))
            painter.drawPixmap(rect, avatar, QRectF(avatar.rect()))
            if selection > 0:
                accent = QColor(self._theme["accent"])
                accent.setAlpha(round(90 * selection))
                painter.setPen(QPen(accent, 1.5))
                painter.setBrush(Qt.BrushStyle.NoBrush)
                painter.drawEllipse(rect.adjusted(-3, -3, 3, 3))
        painter.restore()

    def _index_at(self, point):
        if point.x() >= self._viewport_width() or point.y() >= self.TAB_HEIGHT:
            return -1
        return next(
            (i for i in range(self.count()) if self.tabRect(i).contains(point)), -1
        )

    def mouseMoveEvent(self, event):
        index = self._index_at(event.position().toPoint())
        if index != self._hovered:
            self._hovered = index
            self._hover_timer.start()
            self.setToolTip(self._tab_label(index) if index >= 0 else "")
            self.setCursor(
                Qt.CursorShape.PointingHandCursor
                if index >= 0
                else Qt.CursorShape.ArrowCursor
            )
        super().mouseMoveEvent(event)

    def leaveEvent(self, event):
        self._hovered = -1
        self._hover_timer.start()
        super().leaveEvent(event)

    def _advance_hover(self):
        moving = False
        for i in range(self.count()):
            target = 1.0 if i == self._hovered else 0.0
            value = self._hover.get(i, 0)
            value += (target - value) * 0.24
            if abs(target - value) < 0.01:
                value = target
            else:
                moving = True
            self._hover[i] = value
        self.update()
        if not moving:
            self._hover_timer.stop()

    def mousePressEvent(self, event):
        index = self._index_at(event.position().toPoint())
        if (
            event.button() == Qt.MouseButton.LeftButton
            and index >= 0
            and self.isEnabled()
        ):
            self.setFocus(Qt.FocusReason.MouseFocusReason)
            self.setCurrentIndex(index)
            event.accept()
        else:
            super().mousePressEvent(event)

    def keyPressEvent(self, event):
        if event.key() in {
            Qt.Key.Key_Left,
            Qt.Key.Key_Right,
            Qt.Key.Key_Home,
            Qt.Key.Key_End,
        }:
            index = (
                0
                if event.key() == Qt.Key.Key_Home
                else (
                    self.count() - 1
                    if event.key() == Qt.Key.Key_End
                    else self._index + (1 if event.key() == Qt.Key.Key_Right else -1)
                )
            )
            self.setCurrentIndex(index)
            event.accept()
        else:
            super().keyPressEvent(event)

    def wheelEvent(self, event):
        if event.position().y() < self.TAB_HEIGHT:
            delta = event.angleDelta().x() or event.angleDelta().y()
            self._scroll_to(self._scroll_offset - delta / 120 * self.TAB_STEP)
            event.accept()
        else:
            super().wheelEvent(event)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._ensure_visible(animate=False)
        self._position_buttons()
