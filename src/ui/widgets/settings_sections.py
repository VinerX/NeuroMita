from __future__ import annotations

try:
    import qtawesome as qta
except Exception:
    qta = None

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QPixmap
from PyQt6.QtWidgets import QApplication, QHBoxLayout, QLabel, QStyle, QVBoxLayout, QWidget


def _angle_icon(kind: str, size: int = 10):
    if qta is not None:
        name = "fa6s.chevron-right" if kind == "right" else "fa6s.chevron-down"
        try:
            return qta.icon(name, color="#ff9ed3").pixmap(size, size)
        except Exception:
            pass

    app = QApplication.instance()
    if app is not None:
        style = app.style()
        if style is not None:
            standard_pix = (
                QStyle.StandardPixmap.SP_ArrowRight
                if kind == "right"
                else QStyle.StandardPixmap.SP_ArrowDown
            )
            try:
                return style.standardIcon(standard_pix).pixmap(size, size)
            except Exception:
                pass

    return QPixmap(size, size)


class CollapsibleSection(QWidget):
    def __init__(self, title, parent=None, *, icon_name=None, subtitle=None):
        super().__init__(parent)
        self.setObjectName("CollapsibleSection")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.is_collapsed = True

        root_layout = QVBoxLayout(self)
        root_layout.setContentsMargins(0, 0, 0, 0)
        root_layout.setSpacing(0)

        self.header = QWidget(self, objectName="CollapsibleHeader")
        header_layout = QHBoxLayout(self.header)
        header_layout.setContentsMargins(16, 12, 16, 12)
        header_layout.setSpacing(10)

        self.arrow_label = QLabel(self.header)
        self.arrow_label.setObjectName("CollapsibleArrow")
        self.arrow_pix_right = _angle_icon("right", 13)
        self.arrow_pix_down = _angle_icon("down", 13)
        self.arrow_label.setPixmap(self.arrow_pix_right)
        self.arrow_label.setFixedWidth(18)
        self.arrow_label.setAlignment(Qt.AlignmentFlag.AlignCenter)

        self.icon_label = self._make_icon(icon_name) if icon_name else None

        title_layout = QVBoxLayout()
        title_layout.setContentsMargins(0, 0, 0, 0)
        title_layout.setSpacing(2)

        self.title_label = QLabel(title, self.header, objectName="CollapsibleTitle")
        title_layout.addWidget(self.title_label)
        try:
            from localization.live import register_if_tr

            register_if_tr(self.title_label, title)
        except Exception:
            pass

        self.subtitle_label = None
        subtitle_text = str(subtitle or "").strip()
        if subtitle_text:
            self.subtitle_label = QLabel(
                subtitle_text,
                self.header,
                objectName="CollapsibleSubtitle",
            )
            self.subtitle_label.setWordWrap(True)
            title_layout.addWidget(self.subtitle_label)
            try:
                from localization.live import register_if_tr

                register_if_tr(self.subtitle_label, subtitle)
            except Exception:
                pass

        if self.icon_label is not None:
            header_layout.addWidget(self.icon_label)
        header_layout.addLayout(title_layout, 1)
        header_layout.addStretch()
        header_layout.addWidget(self.arrow_label)

        self.header.setCursor(Qt.CursorShape.PointingHandCursor)
        self.header.mousePressEvent = self.toggle

        self.content_frame = QWidget(self, objectName="CollapsibleContent")
        self.content_layout = QVBoxLayout(self.content_frame)
        self.content_layout.setContentsMargins(20, 8, 20, 16)
        self.content = self.content_frame

        root_layout.addWidget(self.header)
        root_layout.addWidget(self.content_frame)
        self.content_frame.hide()
        self._apply_state_properties()

    def _make_icon(self, name):
        label = QLabel(self.header)
        label.setObjectName("CollapsibleIcon")
        pixmap = qta.icon(name, color="#ffd2ec").pixmap(14, 14) if qta is not None else QPixmap(14, 14)
        label.setPixmap(pixmap)
        label.setFixedSize(26, 26)
        label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        return label

    def set_header_pixmap(self, pixmap, size: int = 22):
        if pixmap is None or pixmap.isNull():
            return
        if self.icon_label is None:
            self.icon_label = QLabel(self.header)
            self.icon_label.setObjectName("CollapsibleIcon")
            self.icon_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            self.header.layout().insertWidget(0, self.icon_label)
        self.icon_label.setFixedSize(size + 4, size + 4)
        self.icon_label.setPixmap(
            pixmap.scaled(
                size,
                size,
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
        )

    def toggle(self, _=None):
        self.is_collapsed = not self.is_collapsed
        self.content_frame.setVisible(not self.is_collapsed)
        self.arrow_label.setPixmap(
            self.arrow_pix_right if self.is_collapsed else self.arrow_pix_down
        )
        self._apply_state_properties()

    def _apply_state_properties(self):
        expanded = not self.is_collapsed
        for widget in (self, self.header, self.content_frame):
            try:
                widget.setProperty("expanded", expanded)
                style = widget.style()
                if style is not None:
                    style.unpolish(widget)
                    style.polish(widget)
                widget.update()
            except Exception:
                pass

    def collapse(self):
        if not self.is_collapsed:
            self.toggle()

    def expand(self):
        if self.is_collapsed:
            self.toggle()

    def add_widget(self, widget):
        self.content_layout.addWidget(widget)
        if self.is_collapsed:
            self.content_frame.hide()


class InnerCollapsibleSection(CollapsibleSection):
    def __init__(self, title, parent=None):
        super().__init__(title, parent)
        self.setProperty("inner", "true")
        self.is_collapsed = True
        self.header.setObjectName("InnerCollapsibleHeader")
        self.header.setProperty("inner", "true")
        self.content_frame.setProperty("inner", "true")
        self.header.setStyleSheet("background: transparent;")
        self.arrow_pix_right = _angle_icon("right", 8)
        self.arrow_pix_down = _angle_icon("down", 8)
        self.arrow_label.setPixmap(self.arrow_pix_right)
        self.header.layout().setContentsMargins(4, 6, 4, 6)
        self.header.layout().setSpacing(4)
        self.arrow_label.setFixedWidth(12)
        self.title_label.setStyleSheet("font-size:9pt;")
        self.content_layout.setContentsMargins(28, 5, 12, 5)
