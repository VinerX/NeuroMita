from PyQt6.QtWidgets import QWidget, QVBoxLayout, QStackedWidget, QScrollArea
from PyQt6.QtCore import Qt
from managers.settings_manager import SettingsManager


class SettingsResizeHandle(QWidget):
    def __init__(self, overlay, parent=None):
        super().__init__(parent)
        self.overlay = overlay
        self._is_resizing = False
        self._drag_start_x = 0
        self._start_width = 0
        self.setObjectName("SettingsResizeHandle")
        self.setFixedWidth(6)
        self.setCursor(Qt.CursorShape.SizeHorCursor)
        self.setStyleSheet("""
            QWidget#SettingsResizeHandle {
                background-color: transparent;
                border-left: 3px solid #4f5d75;
            }
            QWidget#SettingsResizeHandle:hover {
                border-left: 3px solid #7f8fb3;
            }
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
            QWidget#SettingsOverlay {
                background-color: #1a1a1a;
            }
            QWidget#SettingsOverlay QStackedWidget,
            QWidget#SettingsOverlay QStackedWidget > QWidget,
            QWidget#SettingsOverlay QScrollArea,
            QWidget#SettingsOverlay QScrollArea > QWidget > QWidget {
                background-color: transparent;
                border: none;
            }
        """)

        lay = QVBoxLayout(self)
        lay.setContentsMargins(10, 10, 10, 10)

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
        SettingsManager.set("SETTINGS_PANEL_WIDTH", int(new_width))

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
