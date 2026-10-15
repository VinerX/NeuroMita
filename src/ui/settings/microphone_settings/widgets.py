from ui.widgets.toggle_switch import SettingsSwitch as MicrophoneSwitch
from PyQt6.QtCore import QRectF, QSize, Qt, QTimer, QVariantAnimation, QEasingCurve
from PyQt6.QtGui import QColor, QPainter, QFontMetrics
from PyQt6.QtWidgets import (
    QComboBox,
    QStyledItemDelegate,
    QStyle,
    QStyleOptionComboBox,
    QStylePainter,
    QWidget,
    QGridLayout,
    QSizePolicy,
    QCheckBox,
)

from domain.audio_input import ASRInputDevice
from styles.theme import get_theme
from PyQt6.QtWidgets import QFrame, QLabel, QHBoxLayout
import qtawesome as qta
import math
from utils import _


class AudioBackendComboBox(QComboBox):
    def wheelEvent(self, event):
        event.ignore()


class RecognitionStatusLabel(QLabel):
    def set_status(self, text, kind):
        self.parentWidget().set_state(text, kind)


class StatusDot(QWidget):
    def __init__(self, parent):
        super().__init__(parent)
        self.setFixedSize(10, 10)
        self.color = QColor(get_theme()["muted"])
        self._phase = 0.0
        self._timer = QTimer(self)
        self._timer.setInterval(40)
        self._timer.timeout.connect(self._pulse)

    def set_state(self, color, pulsing):
        self.color = QColor(color)
        if pulsing:
            self._timer.start()
        else:
            self._timer.stop()
            self._phase = 0.0
        self.update()

    def _pulse(self):
        self._phase += 0.15
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        color = QColor(self.color)
        if self._timer.isActive():
            color.setAlphaF(0.6 + 0.4 * math.sin(self._phase))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(color)
        painter.drawEllipse(QRectF(1, 1, 8, 8))


class RecognitionStatusBadge(QFrame):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("ASRStatusBadge")
        self.setFixedHeight(38)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(12, 0, 12, 0)
        layout.setSpacing(8)
        self.dot = StatusDot(self)
        layout.addWidget(self.dot)
        self.label = RecognitionStatusLabel("—", self)
        self.label.setObjectName("ASRStatusText")
        layout.addWidget(self.label)
        self.set_state("—", "info")

    def set_state(self, text, kind):
        theme = get_theme()
        color = theme[
            {"ok": "success", "warn": "danger", "progress": "accent"}.get(kind, "muted")
        ]
        rgb = QColor(color)
        channels = f"{rgb.red()}, {rgb.green()}, {rgb.blue()}"
        self.setStyleSheet(
            f"QFrame#ASRStatusBadge {{ background: rgba({channels}, 0.10); border: 1px solid rgba({channels}, 0.35); border-radius: 9px; }}"
            f"QLabel#ASRStatusText {{ color: {color}; background: transparent; border: none; font-size: 12px; font-weight: 600; padding: 0px; }}"
        )
        self.label.setText(text)
        self.dot.set_state(color, kind == "progress")


class MicrophoneCheckBox(QCheckBox):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedSize(24, 24)
        self.setCursor(Qt.CursorShape.PointingHandCursor)

    def hitButton(self, point):
        return self.rect().contains(point)

    def paintEvent(self, event):
        import qtawesome as qta

        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        theme = get_theme()
        painter.setPen(
            QColor(
                theme["accent"]
                if self.isChecked() or self.hasFocus()
                else theme["muted"]
            )
        )
        painter.setBrush(
            QColor(theme["accent"] if self.isChecked() else theme["control_bg"])
        )
        painter.drawRoundedRect(QRectF(2, 2, 20, 20), 5, 5)
        if self.isChecked():
            painter.drawPixmap(
                5, 5, qta.icon("fa5s.check", color=theme["text"]).pixmap(14, 14)
            )


class MicrophoneDeviceDelegate(QStyledItemDelegate):
    def paint(self, painter, option, index):
        device = index.data(Qt.ItemDataRole.UserRole)
        if not isinstance(device, ASRInputDevice):
            return super().paint(painter, option, index)
        theme = get_theme()
        painter.save()
        painter.setClipRect(option.rect)
        if option.state & QStyle.StateFlag.State_Selected:
            painter.fillRect(option.rect, QColor(theme["accent"]))
        painter.setFont(option.font)
        painter.setPen(QColor(theme["text"]))
        rect = option.rect.adjusted(12, 8, -12, -8)
        detail_height = QFontMetrics(option.font).height() + 4
        painter.drawText(
            rect.adjusted(0, 0, 0, -detail_height),
            Qt.TextFlag.TextWordWrap,
            device.label,
        )
        painter.setPen(
            QColor(
                theme["text"]
                if option.state & QStyle.StateFlag.State_Selected
                else theme["muted"]
            )
        )
        painter.drawText(
            rect.adjusted(0, rect.height() - detail_height, 0, 0),
            Qt.AlignmentFlag.AlignVCenter,
            f"{device.host_api} · PortAudio {device.index}"
            + (
                " · " + _("Совместимый режим", "Compatibility mode")
                if not device.uid
                else ""
            ),
        )
        painter.restore()

    def sizeHint(self, option, index):
        device = index.data(Qt.ItemDataRole.UserRole)
        if not isinstance(device, ASRInputDevice):
            return super().sizeHint(option, index)
        width = max(220, self.parent().view().width() - 32)
        metrics = QFontMetrics(option.font)
        height = metrics.boundingRect(
            0, 0, width, 1000, Qt.TextFlag.TextWordWrap, device.label
        ).height()
        return QSize(width, height + metrics.height() + 24)


class MicrophoneDeviceComboBox(QComboBox):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setItemDelegate(MicrophoneDeviceDelegate(self))
        self.setSizeAdjustPolicy(
            QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon
        )
        self.setMinimumContentsLength(12)
        self.setMinimumWidth(0)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)

    def wheelEvent(self, event):
        event.ignore()

    def paintEvent(self, event):
        painter = QStylePainter(self)
        option = QStyleOptionComboBox()
        self.initStyleOption(option)
        text = option.currentText
        option.currentText = ""
        painter.drawComplexControl(QStyle.ComplexControl.CC_ComboBox, option)
        rect = self.style().subControlRect(
            QStyle.ComplexControl.CC_ComboBox,
            option,
            QStyle.SubControl.SC_ComboBoxEditField,
            self,
        )
        painter.setClipRect(rect)
        painter.setPen(self.palette().text().color())
        painter.drawText(
            rect, Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft, text
        )

    def showPopup(self):
        screen = self.screen()
        available = screen.availableGeometry().width() - 48 if screen else 600
        self.view().setMinimumWidth(min(max(self.width(), 480), available))
        super().showPopup()


class ResponsiveColumns(QWidget):
    def __init__(
        self, widgets, breakpoint=900, compact_columns=1, weights=None, parent=None
    ):
        super().__init__(parent)
        self._widgets = widgets
        self._breakpoint = breakpoint
        self._compact_columns = compact_columns
        self._weights = weights or [1] * len(widgets)
        self._columns = 0
        self.grid = QGridLayout(self)
        self.grid.setContentsMargins(0, 0, 0, 0)
        self.grid.setSpacing(14)
        self._arrange(compact_columns)

    def _arrange(self, columns):
        if columns == self._columns:
            return
        self._columns = columns
        for i, widget in enumerate(self._widgets):
            self.grid.addWidget(widget, i // columns, i % columns)
        for i in range(len(self._widgets)):
            self.grid.setColumnStretch(
                i,
                (
                    self._weights[i]
                    if columns == len(self._widgets)
                    else 1 if i < columns else 0
                ),
            )

    def resizeEvent(self, event):
        self._arrange(
            len(self._widgets)
            if self.width() >= self._breakpoint
            else self._compact_columns
        )
        super().resizeEvent(event)


class MicrophoneLevelMeter(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumHeight(30)
        self.setMinimumWidth(100)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self._level = 0.0
        self._target = 0.0
        self._timer = QTimer(self)
        self._timer.setInterval(25)
        self._timer.timeout.connect(self._animate)

    def set_level(self, value):
        self._target = max(0.0, min(1.0, float(value)))
        if not self._timer.isActive():
            self._timer.start()

    def _animate(self):
        self._level += (self._target - self._level) * (
            0.55 if self._target > self._level else 0.18
        )
        if abs(self._target - self._level) < 0.002:
            self._level = self._target
            self._timer.stop()
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        theme = get_theme()
        painter.setPen(Qt.PenStyle.NoPen)
        count = max(12, self.width() // 9)
        step = self.width() / count
        for i in range(count):
            color = QColor(
                theme["accent"] if (i + 1) / count <= self._level else theme["muted"]
            )
            if (i + 1) / count > self._level:
                color.setAlphaF(0.16)
            painter.setBrush(color)
            painter.drawRoundedRect(
                QRectF(i * step + 1, 6, max(2, step - 3), self.height() - 12), 2.5, 2.5
            )
