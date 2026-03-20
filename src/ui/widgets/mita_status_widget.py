"""
MitaStatusWidget — typing/status indicator bridge.

Delegates to ChatWidget's built-in typing bar for visual display.
Keeps the same public API so main_view.py doesn't need changes.
"""

from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtWidgets import QWidget
from utils import _


class MitaStatusWidget(QWidget):
    """Bridge: translates show_thinking/show_error/hide_animated to ChatWidget typing bar."""

    def __init__(self, chat_widget=None, parent=None):
        super().__init__(parent)
        self._chat = chat_widget
        self.current_state = "idle"
        self.is_animating = False
        self._dots_phase = 0
        self._dots_timer = None
        self._character_name = ""
        self.hide()  # this widget itself is never shown

    def _get_chat(self):
        return self._chat

    def show_thinking(self, character_name="Мита"):
        if self.current_state == "thinking":
            return
        self.current_state = "thinking"
        self._character_name = character_name
        self._dots_phase = 0

        chat = self._get_chat()
        if chat:
            # Get avatar for the character
            from ui.chat.message_widget import _get_avatar_pixmap
            avatar = _get_avatar_pixmap(character_name, "assistant")
            chat.show_typing(
                _(f"{character_name} думает", f"{character_name} is thinking"),
                avatar
            )
            # Start dot animation
            self._start_dots()

    def show_error(self, error_message=None):
        if error_message is None:
            error_message = _("Произошла ошибка", "Error occurred")
        self.current_state = "error"
        self._stop_dots()
        chat = self._get_chat()
        if chat:
            chat.show_typing(f"⚠ {error_message}")
            QTimer.singleShot(5000, self.hide_animated)

    def show_success(self, message=None):
        if message is None:
            message = _("Готово", "Done")
        self.current_state = "success"
        self._stop_dots()
        chat = self._get_chat()
        if chat:
            chat.show_typing(f"✓ {message}")
            QTimer.singleShot(2000, self.hide_animated)

    def pulse_error_animation(self):
        """Quick flash on thinking state to indicate a transient error."""
        pass

    def hide_animated(self):
        if self.current_state == "idle":
            return
        self.current_state = "idle"
        self._stop_dots()
        chat = self._get_chat()
        if chat:
            chat.hide_typing()

    # ── Dot animation ────────────────────────────────────────────────────────

    def _start_dots(self):
        self._stop_dots()
        self._dots_timer = QTimer()
        self._dots_timer.timeout.connect(self._tick_dots)
        self._dots_timer.start(500)

    def _stop_dots(self):
        if self._dots_timer:
            self._dots_timer.stop()
            self._dots_timer = None

    def _tick_dots(self):
        phases = [".", "..", "..."]
        self._dots_phase = (self._dots_phase + 1) % 3
        dots = phases[self._dots_phase]
        chat = self._get_chat()
        if chat and self.current_state == "thinking":
            name = self._character_name
            chat._typing_label.setText(
                _(f"{name} думает{dots}", f"{name} is thinking{dots}")
            )

    # ── Compat stubs ─────────────────────────────────────────────────────────

    def set_pulse_intensity(self, factor):
        pass

    @property
    def pulseIntensity(self):
        return 0.0

    @pulseIntensity.setter
    def pulseIntensity(self, value):
        pass

    def setGeometry(self, *args, **kwargs):
        """Ignore geometry calls — we're not a visible widget."""
        pass
