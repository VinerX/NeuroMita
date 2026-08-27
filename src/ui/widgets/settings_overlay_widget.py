from PyQt6.QtWidgets import QWidget, QVBoxLayout, QStackedWidget, QScrollArea
from PyQt6.QtCore import Qt, QRectF
from PyQt6.QtGui import QColor, QLinearGradient, QPainter, QPainterPath, QPen
from styles.theme import get_theme
from ui.settings.settings_access import set_setting


class SettingsResizeHandle(QWidget):
    def __init__(self, overlay, parent=None):
        super().__init__(parent)
        self.overlay = overlay
        theme = get_theme()
        self._is_resizing = False
        self._drag_start_x = 0
        self._start_width = 0
        self.setObjectName("SettingsResizeHandle")
        self.setFixedWidth(6)
        self.setCursor(Qt.CursorShape.SizeHorCursor)
        self.setStyleSheet(f"""
            QWidget#SettingsResizeHandle {{
                background-color: transparent;
                border-left: 3px solid rgba({theme['accent_rgb']}, 0.26);
            }}
            QWidget#SettingsResizeHandle:hover {{
                border-left: 3px solid rgba({theme['accent_rgb']}, 0.72);
            }}
        """)

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self._is_resizing = True
            self._drag_start_x = int(event.globalPosition().x())
            self._start_width = int(self.overlay.width())
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if self._is_resizing:
            delta = int(event.globalPosition().x()) - self._drag_start_x
            self.overlay.set_resized_width(self._start_width - delta)
            event.accept()
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton and self._is_resizing:
            self._is_resizing = False
            self.overlay.finish_resizing()
            event.accept()
            return
        super().mouseReleaseEvent(event)

class SettingsOverlay(QWidget):
    def __init__(self, parent):
        super().__init__(parent)
        self._theme = get_theme()
        self._resize_edge = 14
        self._is_resizing = False
        self._drag_start_x = 0
        self._start_width = 0
        self._min_width = 280
        self._max_width = 1800
        self.setObjectName("SettingsOverlay")
        self.setMouseTracking(True)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setStyleSheet("""
            QWidget#SettingsOverlay QStackedWidget,
            QWidget#SettingsOverlay QStackedWidget > QWidget,
            QWidget#SettingsOverlay QScrollArea,
            QWidget#SettingsOverlay QScrollArea > QWidget > QWidget {
                background-color: transparent;
                border: none;
            }
        """)

        lay = QVBoxLayout(self)
        lay.setContentsMargins(18, 18, 18, 18)

        self.stack = QStackedWidget()
        lay.addWidget(self.stack)

    def add_container(self, container):
        self.stack.addWidget(container)

    def show_category(self, container):
        self.stack.setCurrentWidget(container)
        self.show()
        if isinstance(container, QScrollArea):
            container.verticalScrollBar().setValue(0)

    def _effective_max_width(self) -> int:
        parent = self.parentWidget()
        if parent is None:
            return self._max_width

        sidebar_width = int(getattr(parent, "SETTINGS_SIDEBAR_WIDTH", 50) or 50)
        min_chat_width = 260
        handle_width = int(getattr(parent, "SETTINGS_RESIZE_HANDLE_WIDTH", 6) or 6)
        available = max(self._min_width, parent.width() - sidebar_width - handle_width - min_chat_width)
        return max(self._min_width, min(self._max_width, available))

    def set_resized_width(self, target_width: int):
        new_width = max(self._min_width, min(self._effective_max_width(), int(target_width)))
        self.setMaximumWidth(new_width)
        parent = self.parentWidget()
        if parent is not None and hasattr(parent, "SETTINGS_PANEL_WIDTH"):
            parent.SETTINGS_PANEL_WIDTH = int(new_width)
        parent = self.parentWidget()
        if parent is None:
            raise RuntimeError("SettingsOverlay requires an owning settings view")
        set_setting(parent, "SETTINGS_PANEL_WIDTH", int(new_width))

    def finish_resizing(self):
        self.setMinimumWidth(0)
        self.setMaximumWidth(max(self.width(), self._effective_max_width()))

    def _near_left_edge(self, pos) -> bool:
        return pos.x() <= self._resize_edge

    def mousePressEvent(self, event):
        if (
            event.button() == Qt.MouseButton.LeftButton
            and self._near_left_edge(event.position())
        ):
            self._is_resizing = True
            self._drag_start_x = int(event.globalPosition().x())
            self._start_width = int(self.width())
            self.setCursor(Qt.CursorShape.SizeHorCursor)
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if self._is_resizing:
            delta = int(event.globalPosition().x()) - self._drag_start_x
            target = self._start_width - delta
            self.set_resized_width(target)
            event.accept()
            return
        if self._near_left_edge(event.position()):
            self.setCursor(Qt.CursorShape.SizeHorCursor)
        else:
            self.unsetCursor()
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton and self._is_resizing:
            self._is_resizing = False
            self.finish_resizing()
            self.unsetCursor()
            event.accept()
            return
        super().mouseReleaseEvent(event)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)

        rect = QRectF(self.rect().adjusted(1, 1, -1, -1))
        radius = 26

        panel_path = QPainterPath()
        panel_path.addRoundedRect(rect, radius, radius)

        gradient = QLinearGradient(rect.topLeft(), rect.bottomRight())
        gradient.setColorAt(0.0, QColor(16, 13, 25, 244))
        gradient.setColorAt(0.55, QColor(12, 9, 21, 248))
        gradient.setColorAt(1.0, QColor(8, 8, 18, 250))
        painter.fillPath(panel_path, gradient)

        painter.save()
        painter.setClipPath(panel_path)
        painter.setPen(QPen(QColor(183, 75, 125, 18), 1))
        step = 26
        rl, rt, rr, rb, rh = int(rect.left()), int(rect.top()), int(rect.right()), int(rect.bottom()), int(rect.height())
        for x in range(rl - rh, rr + rh, step):
            painter.drawLine(x, rt, x + rh, rb)
        painter.setPen(QPen(QColor(183, 75, 125, 10), 1))
        for y in range(rt, rb, step):
            painter.drawLine(rl, y, rr, y)
        painter.restore()

        painter.setPen(QPen(QColor(183, 75, 125, 88), 1.2))
        painter.drawPath(panel_path)

        inner = rect.adjusted(10, 10, -10, -10)
        painter.setPen(QPen(QColor(255, 255, 255, 14), 1))
        painter.drawRoundedRect(inner, radius - 8, radius - 8)
