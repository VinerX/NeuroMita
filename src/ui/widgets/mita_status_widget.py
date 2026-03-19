"""
MitaStatusWidget — Telegram-style typing indicator.

Shows as a subtle inline bar at the bottom of the chat area:
  ● ● ●  Мита думает...

Supports states: idle, thinking, error, success.
"""

import qtawesome as qta
from PyQt6.QtCore import Qt, QTimer, QPropertyAnimation, QEasingCurve, QSize
from PyQt6.QtWidgets import QWidget, QHBoxLayout, QLabel, QGraphicsOpacityEffect
from PyQt6.QtGui import QPainter, QColor, QPen, QBrush
from utils import _


class AnimatedDots(QWidget):
    """Three bouncing dots like Telegram typing indicator."""

    def __init__(self, color: str = "#8a8a9a", parent=None):
        super().__init__(parent)
        self.setFixedSize(28, 16)
        self._color = QColor(color)
        self._dim_color = QColor(color)
        self._dim_color.setAlpha(80)
        self.dot_count = 3
        self.dot_size = 3
        self.dot_spacing = 4
        self.current_dot = 0
        self.animation_step = 0

        self.animation_timer = QTimer()
        self.animation_timer.timeout.connect(self._animate_dots)
        self.smooth_timer = QTimer()
        self.smooth_timer.timeout.connect(self._smooth_animation)

    def _animate_dots(self):
        self.current_dot = (self.current_dot + 1) % self.dot_count
        self.animation_step = 0
        self.update()

    def _smooth_animation(self):
        self.animation_step += 1
        self.update()
        if self.animation_step >= 10:
            self.animation_step = 0

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        total_width = self.dot_count * self.dot_size + (self.dot_count - 1) * self.dot_spacing
        start_x = (self.width() - total_width) // 2
        y = self.height() // 2

        for i in range(self.dot_count):
            x = start_x + i * (self.dot_size + self.dot_spacing)
            if i == self.current_dot:
                scale = 1.0 + 0.4 * abs(5 - self.animation_step) / 5.0
                size = int(self.dot_size * scale)
                painter.setBrush(QBrush(self._color))
                painter.setPen(Qt.PenStyle.NoPen)
                painter.drawEllipse(
                    x - size // 2 + self.dot_size // 2,
                    y - size // 2, size, size
                )
            else:
                painter.setBrush(QBrush(self._dim_color))
                painter.setPen(Qt.PenStyle.NoPen)
                painter.drawEllipse(x, y - self.dot_size // 2,
                                   self.dot_size, self.dot_size)

    def stop_animation(self):
        self.animation_timer.stop()
        self.smooth_timer.stop()

    def start_animation(self):
        self.animation_timer.start(500)
        self.smooth_timer.start(50)


class MitaStatusWidget(QWidget):
    """Telegram-style typing/status indicator at the bottom of chat."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.current_state = "idle"
        self.is_animating = False
        self.setup_ui()
        self.hide()

    def setup_ui(self):
        self.setObjectName("MitaStatusWidget")
        self.setFixedHeight(28)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, False)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(12, 4, 12, 4)
        layout.setSpacing(6)

        self.dots_widget = AnimatedDots()
        layout.addWidget(self.dots_widget)

        self.icon_label = QLabel()
        self.icon_label.hide()
        layout.addWidget(self.icon_label)

        self.status_label = QLabel()
        layout.addWidget(self.status_label)

        layout.addStretch()

        self.opacity_effect = QGraphicsOpacityEffect()
        self.setGraphicsEffect(self.opacity_effect)
        self.opacity_effect.setOpacity(0.0)

        self.fade_animation = QPropertyAnimation(self.opacity_effect, b"opacity")
        self.fade_animation.setDuration(300)
        self.fade_animation.setEasingCurve(QEasingCurve.Type.InOutQuad)

        self._apply_style("normal")

    def _apply_style(self, variant: str = "normal"):
        styles = {
            "normal": (
                "rgba(30, 30, 36, 0.85)",
                "rgba(255,255,255,0.06)",
                "rgba(180, 180, 195, 0.6)",
            ),
            "error": (
                "rgba(60, 30, 30, 0.90)",
                "rgba(255,100,100,0.15)",
                "rgba(255, 120, 120, 0.8)",
            ),
            "success": (
                "rgba(30, 45, 30, 0.90)",
                "rgba(100,200,100,0.12)",
                "rgba(100, 200, 100, 0.8)",
            ),
        }
        bg, border, text_color = styles.get(variant, styles["normal"])
        self.setStyleSheet(f"""
            #MitaStatusWidget {{
                background-color: {bg};
                border: 1px solid {border};
                border-radius: 6px;
            }}
        """)
        self.status_label.setStyleSheet(f"""
            QLabel {{
                color: {text_color};
                font-size: 9pt;
                background: transparent;
                border: none;
            }}
        """)

    def _fade_in(self):
        self.show()
        self.raise_()
        self.fade_animation.stop()
        self._disconnect_fade_signal()
        self.opacity_effect.setOpacity(0.0)
        self.fade_animation.setStartValue(0.0)
        self.fade_animation.setEndValue(1.0)
        self.fade_animation.start()

    def _disconnect_fade_signal(self):
        try:
            self.fade_animation.finished.disconnect()
        except TypeError:
            pass

    # ── Public API (same signatures as before) ───────────────────────────────

    def show_thinking(self, character_name="Мита"):
        if self.current_state == "thinking" and self.isVisible() and self.opacity_effect.opacity() > 0.5:
            return

        self.current_state = "thinking"
        self.is_animating = False
        self._apply_style("normal")
        self.icon_label.hide()
        self.status_label.setText(
            _(f"{character_name} думает...", f"{character_name} is thinking...")
        )
        self.dots_widget.show()
        self.dots_widget.start_animation()
        self._fade_in()

    def show_error(self, error_message=_("Произошла ошибка", "Error occurred")):
        self.current_state = "error"
        self.is_animating = False
        self._apply_style("error")

        error_icon = qta.icon('fa5s.exclamation-triangle', color='#ff6b6b')
        self.icon_label.setPixmap(error_icon.pixmap(14, 14))
        self.icon_label.show()

        self.status_label.setText(error_message)
        self.dots_widget.hide()
        self.dots_widget.stop_animation()
        self._fade_in()
        QTimer.singleShot(5000, self.hide_animated)

    def show_success(self, message=_("Готово", "success")):
        self.current_state = "success"
        self.is_animating = False
        self._apply_style("success")

        success_icon = qta.icon('fa5s.check-circle', color='#4caf50')
        self.icon_label.setPixmap(success_icon.pixmap(14, 14))
        self.icon_label.show()

        self.status_label.setText(message)
        self.dots_widget.hide()
        self.dots_widget.stop_animation()
        self._fade_in()
        QTimer.singleShot(2000, self.hide_animated)

    def pulse_error_animation(self):
        """Quick red flash on thinking state to indicate a transient error."""
        if self.current_state != "thinking" or not self.isVisible():
            return
        self._apply_style("error")
        QTimer.singleShot(600, lambda: self._apply_style("normal") if self.current_state == "thinking" else None)

    def hide_animated(self):
        if self.current_state == "idle" or self.is_animating:
            return
        self.current_state = "idle"
        self.is_animating = True
        self.dots_widget.stop_animation()

        self.fade_animation.stop()
        self._disconnect_fade_signal()
        self.fade_animation.setStartValue(self.opacity_effect.opacity())
        self.fade_animation.setEndValue(0.0)
        self.fade_animation.finished.connect(self._on_hide_finished)
        self.fade_animation.start()

    def _on_hide_finished(self):
        self.hide()
        self.is_animating = False
        self._disconnect_fade_signal()

    # ── Compat stubs (old API used pyqtProperty for pulse) ───────────────────
    def set_pulse_intensity(self, factor):
        pass

    @property
    def pulseIntensity(self):
        return 0.0

    @pulseIntensity.setter
    def pulseIntensity(self, value):
        pass
