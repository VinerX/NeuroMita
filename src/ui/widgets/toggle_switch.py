from PyQt6.QtCore import QEasingCurve, QPropertyAnimation, QSize, Qt, pyqtProperty
from PyQt6.QtGui import QColor, QPainter, QPen
from PyQt6.QtWidgets import QCheckBox


class ToggleSwitch(QCheckBox):
    """A compact pill-style on/off switch.

    Behaves like a QCheckBox (checkable, emits `toggled`, `setChecked` works),
    but is drawn as an animated sliding knob instead of the default tick box.
    The whole widget is clickable. Off = neutral grey track, On = green track.
    """

    _OFF_TRACK = QColor(255, 255, 255, 30)
    _ON_TRACK = QColor(121, 231, 140, 235)  # #79e78c, matches the status dots
    _KNOB = QColor(255, 255, 255, 240)
    _KNOB_BORDER = QColor(15, 17, 33, 46)  # rgba(15, 17, 33, 0.18)
    _KNOB_SHADOW = QColor(15, 17, 33, 71)  # rgba(15, 17, 33, 0.28)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFixedSize(42, 22)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)

        # Knob position 0.0 (off) .. 1.0 (on), animated on toggle.
        self._pos = 1.0 if self.isChecked() else 0.0
        self._anim = QPropertyAnimation(self, b"knobPos", self)
        self._anim.setDuration(140)
        self._anim.setEasingCurve(QEasingCurve.Type.InOutCubic)
        self.toggled.connect(self._animate_to)

    def sizeHint(self) -> QSize:
        return QSize(42, 22)

    def hitButton(self, pos) -> bool:
        # Make the entire widget toggle, not just the (hidden) indicator.
        return self.rect().contains(pos)

    def _get_knob_pos(self) -> float:
        return self._pos

    def _set_knob_pos(self, value: float):
        self._pos = float(value)
        self.update()

    knobPos = pyqtProperty(float, _get_knob_pos, _set_knob_pos)

    def _animate_to(self, checked: bool):
        self._anim.stop()
        self._anim.setStartValue(self._pos)
        self._anim.setEndValue(1.0 if checked else 0.0)
        self._anim.start()

    def setChecked(self, checked: bool):
        # Drive the knob even when `toggled` is blocked (programmatic sync),
        # since the animation is otherwise triggered off the toggled signal.
        super().setChecked(checked)
        if hasattr(self, "_anim"):
            self._animate_to(bool(self.isChecked()))

    @staticmethod
    def _lerp(a: QColor, b: QColor, t: float) -> QColor:
        return QColor(
            int(a.red() + (b.red() - a.red()) * t),
            int(a.green() + (b.green() - a.green()) * t),
            int(a.blue() + (b.blue() - a.blue()) * t),
            int(a.alpha() + (b.alpha() - a.alpha()) * t),
        )

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        p.setPen(Qt.PenStyle.NoPen)

        r = self.rect().adjusted(1, 1, -1, -1)
        radius = r.height() / 2.0

        track = self._lerp(self._OFF_TRACK, self._ON_TRACK, self._pos)
        p.setBrush(track)
        p.drawRoundedRect(r, radius, radius)

        d = r.height() - 4
        travel = r.width() - d - 4
        x = r.left() + 2 + travel * self._pos
        y = r.top() + 2

        # Approximate the requested CSS shadow with a soft, slightly offset
        # ellipse behind the knob; Qt's painter has no direct box-shadow here.
        p.setBrush(self._KNOB_SHADOW)
        p.drawEllipse(int(round(x)), int(round(y + 1)), int(d), int(d))

        p.setPen(QPen(self._KNOB_BORDER, 1))
        p.setBrush(self._KNOB)
        p.drawEllipse(int(round(x)), int(round(y)), int(d), int(d))
        p.end()
