from PyQt6.QtWidgets import QPushButton, QApplication, QLabel
from PyQt6.QtCore import QSize, Qt, QVariantAnimation
from PyQt6.QtGui import QPainter, QColor, QLinearGradient
import qtawesome as qta


class SettingsIconButton(QPushButton):
    def __init__(self, icon_name, tooltip_text, parent=None):
        super().__init__(parent)

        self._base_tooltip = str(tooltip_text or "")
        self._indicator_tooltip = ""
        self._indicator_state: str | None = None

        self.setIcon(qta.icon(icon_name, color='#dcdcdc'))
        icon_size = QApplication.style().pixelMetric(QApplication.style().PixelMetric.PM_SmallIconSize)
        self.setIconSize(QSize(icon_size, icon_size))
        self.setToolTip(self._base_tooltip)
        self.setFixedSize(40, 40)

        self.is_active = False

        self._badge = QLabel(self)
        self._badge.setFixedSize(10, 10)
        self._badge.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self._badge.hide()

        self._loading_phase = 0.0
        self._loading_anim = QVariantAnimation(self)
        self._loading_anim.setStartValue(0.0)
        self._loading_anim.setEndValue(1.0)
        self._loading_anim.setDuration(1200)
        self._loading_anim.setLoopCount(-1)
        self._loading_anim.valueChanged.connect(self._on_loading_value_changed)

        self.update_style()
        self._reposition_badge()

    def set_active(self, active):
        self.is_active = active
        self.update_style()

    def set_indicator_state(self, state: str | None, tooltip_text: str | None = None):
        st = (str(state).strip().lower() if state is not None else None)
        if st not in (None, "red", "green", "loading"):
            st = None

        self._indicator_state = st
        self._indicator_tooltip = str(tooltip_text or "").strip()

        self._sync_tooltip()
        self._sync_badge()
        self._sync_loading_animation()
        self.update()

    def indicator_state(self) -> str | None:
        return self._indicator_state

    def _sync_tooltip(self):
        if self._indicator_tooltip and self._base_tooltip:
            self.setToolTip(f"{self._base_tooltip}\n{self._indicator_tooltip}")
        elif self._indicator_tooltip:
            self.setToolTip(self._indicator_tooltip)
        else:
            self.setToolTip(self._base_tooltip)

    def _badge_stylesheet(self, color_hex: str) -> str:
        return (
            "QLabel {"
            f"background-color: {color_hex};"
            "border: 2px solid rgba(20, 20, 20, 220);"
            "border-radius: 5px;"
            "}"
        )

    def _sync_badge(self):
        st = self._indicator_state
        if st is None:
            self._badge.hide()
            return

        if st == "red":
            self._badge.setStyleSheet(self._badge_stylesheet("#ff3b30"))
            self._badge.show()
        elif st == "green":
            self._badge.setStyleSheet(self._badge_stylesheet("#b7ff3c"))
            self._badge.show()
        elif st == "loading":
            self._badge.setStyleSheet(self._badge_stylesheet("#ffd60a"))
            self._badge.show()

        self._reposition_badge()

    def _sync_loading_animation(self):
        if self._indicator_state == "loading":
            if self._loading_anim.state() != QVariantAnimation.State.Running:
                self._loading_anim.start()
        else:
            if self._loading_anim.state() == QVariantAnimation.State.Running:
                self._loading_anim.stop()
            self._loading_phase = 0.0

    def _on_loading_value_changed(self, v):
        try:
            self._loading_phase = float(v)
        except Exception:
            self._loading_phase = 0.0
        self.update()

    def _reposition_badge(self):
        m = 4
        x = self.width() - self._badge.width() - m
        y = m
        self._badge.move(max(0, x), max(0, y))

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._reposition_badge()

    def paintEvent(self, event):
        super().paintEvent(event)

        if self._indicator_state != "loading":
            return

        r = self.rect().adjusted(2, 2, -2, -2)
        if r.width() <= 0 or r.height() <= 0:
            return

        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)

        base = QColor(255, 214, 10, 18)
        p.fillRect(r, base)

        w = float(r.width())
        phase = float(self._loading_phase)

        x0 = -w + (2.0 * w) * phase
        grad = QLinearGradient(x0, 0.0, x0 + w, 0.0)
        grad.setColorAt(0.0, QColor(255, 214, 10, 0))
        grad.setColorAt(0.5, QColor(255, 214, 10, 85))
        grad.setColorAt(1.0, QColor(255, 214, 10, 0))

        p.fillRect(r, grad)
        p.end()

    def update_style(self):
        if self.is_active:
            self.setStyleSheet("""
                QPushButton {
                    background-color: #8a2be2;
                    border: none;
                    padding: 8px;
                    border-radius: 4px;
                }
                QPushButton:hover {
                    background-color: #9932cc;
                }
                QPushButton:pressed {
                    background-color: #7b1fa2;
                }
            """)
        else:
            self.setStyleSheet("""
                QPushButton {
                    background-color: transparent;
                    border: none;
                    padding: 8px;
                    border-radius: 4px;
                }
                QPushButton:hover {
                    background-color: rgba(138, 43, 226, 0.3);
                }
                QPushButton:pressed {
                    background-color: rgba(138, 43, 226, 0.5);
                }
            """)