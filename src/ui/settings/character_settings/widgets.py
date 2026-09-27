from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtGui import QPainter, QColor, QFont, QIcon
from PyQt6.QtWidgets import QSplitter, QWidget, QVBoxLayout, QScrollArea, QFrame, QLabel, QStyledItemDelegate, QStyle
from localization.live import register_if_tr
from styles.theme import THEME


class CharacterWorkspace(QWidget):
    def __init__(self):
        super().__init__()
        self.sections = []

    def showEvent(self, event):
        super().showEvent(event)
        for section, expanded in self.sections:
            section.expand() if expanded else section.collapse()


class CharacterListDelegate(QStyledItemDelegate):
    def paint(self, painter, option, index):
        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        rect = option.rect.adjusted(1, 1, -1, -1)
        selected = bool(option.state & QStyle.StateFlag.State_Selected)
        painter.setBrush(QColor(THEME["settings_panel_bg"]))
        border = QColor(THEME["muted"])
        if not selected:
            border.setAlpha(55)
        painter.setPen(border)
        painter.drawRoundedRect(rect, 9, 9)
        icon = index.data(Qt.ItemDataRole.DecorationRole)
        if icon is not None:
            painter.drawPixmap(rect.left() + 8, rect.center().y() - 16, icon.pixmap(32, 32, QIcon.Mode.Normal))
        name_rect = rect.adjusted(48, 6, -8, -22)
        font = QFont(option.font)
        font.setBold(True)
        painter.setFont(font)
        painter.setPen(QColor(THEME["text"]))
        name = painter.fontMetrics().elidedText(index.data(), Qt.TextElideMode.ElideRight, name_rect.width())
        painter.drawText(name_rect, Qt.AlignmentFlag.AlignVCenter, name)
        font.setBold(False)
        font.setPointSizeF(max(8, font.pointSizeF() - 1))
        painter.setFont(font)
        painter.setPen(QColor(THEME["muted"]))
        id_rect = rect.adjusted(48, 25, -8, -5)
        identifier = "id: " + str(index.data(Qt.ItemDataRole.UserRole))
        painter.drawText(id_rect, Qt.AlignmentFlag.AlignVCenter,
                         painter.fontMetrics().elidedText(identifier, Qt.TextElideMode.ElideRight, id_rect.width()))
        painter.restore()


class CharacterWorkspaceSplitter(QSplitter):
    def __init__(self):
        super().__init__(Qt.Orientation.Horizontal)
        self.setObjectName("ApiWorkspaceSplitter")
        self.setChildrenCollapsible(False)
        self.setHandleWidth(9)
        self._initialized = False

    def showEvent(self, event):
        super().showEvent(event)
        if not self._initialized:
            self._initialized = True
            QTimer.singleShot(0, self._initial_sizes)

    def _initial_sizes(self):
        width = max(1, self.width() - self.handleWidth())
        self.setSizes([width // 4, width * 3 // 4])
        self.setStretchFactor(0, 1)
        self.setStretchFactor(1, 3)


def tab_page():
    scroll = QScrollArea()
    scroll.setObjectName("ApiEditorScroll")
    scroll.setWidgetResizable(True)
    scroll.setFrameShape(QScrollArea.Shape.NoFrame)
    body = QWidget()
    body.setObjectName("ApiEditorContent")
    layout = QVBoxLayout(body)
    layout.setContentsMargins(16, 16, 16, 16)
    layout.setSpacing(12)
    layout.setAlignment(Qt.AlignmentFlag.AlignTop)
    scroll.setWidget(body)
    return scroll, layout


class CharacterSection(QFrame):
    def __init__(self, title, parent=None):
        super().__init__(parent)
        self.setObjectName("CharacterSection")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 14, 14, 14)
        layout.setSpacing(10)
        heading = QLabel(title)
        heading.setObjectName("CharacterLibraryTitle")
        register_if_tr(heading, title)
        layout.addWidget(heading)
        self.content_layout = layout

    def add_widget(self, widget):
        self.content_layout.addWidget(widget)
