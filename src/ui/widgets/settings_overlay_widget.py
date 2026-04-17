from PyQt6.QtWidgets import QWidget, QVBoxLayout, QStackedWidget, QScrollArea
from PyQt6.QtCore import Qt
from managers.settings_manager import SettingsManager

class SettingsOverlay(QWidget):
    def __init__(self, parent):
        super().__init__(parent)
        self._resize_edge = 8
        self._is_resizing = False
        self._drag_start_x = 0
        self._start_width = 0
        self._min_width = 360
        self._max_width = 900
        self.setObjectName("SettingsOverlay")
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setStyleSheet("""
            QWidget#SettingsOverlay {
                background-color: #1a1a1a;
                border-left: 2px solid #4f5d75;
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
            new_width = max(self._min_width, min(self._max_width, target))
            self.setMaximumWidth(new_width)
            parent = self.parentWidget()
            if parent is not None and hasattr(parent, "SETTINGS_PANEL_WIDTH"):
                parent.SETTINGS_PANEL_WIDTH = int(new_width)
            SettingsManager.set("SETTINGS_PANEL_WIDTH", int(new_width))
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
            self.setMinimumWidth(0)
            self.setMaximumWidth(self._max_width)
            self.unsetCursor()
            event.accept()
            return
        super().mouseReleaseEvent(event)
