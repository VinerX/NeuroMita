"""
MitaStatusWidget - typing/status indicator bridge.

Delegates to ChatWidget's built-in typing bar for visual display.
Keeps the same public API so window host refactors don't need widget changes.
"""

import qtawesome as qta
from PyQt6.QtCore import QTimer
from PyQt6.QtWidgets import QWidget

from main_logger import logger
from utils import _

# Страховочный таймаут "завис" для занятых состояний (думает/сжатие/озвучивает).
# Нормальный поток гасит статус по событиям успеха/ошибки, но если соединение с
# игрой оборвалось посреди запроса, эти события могут не прийти и "думает"
# висит вечно. Таймер срабатывает только на крайний случай, поэтому окно щедрое:
# не мешает долгой генерации/синтезу, но не даёт залипнуть.
_BUSY_WATCHDOG_MS = 240_000  # 4 minutes


class MitaStatusWidget(QWidget):
    """Bridge: translates show_thinking/show_error/hide_animated to ChatWidget status bar."""

    def __init__(self, chat_widget=None, parent=None):
        super().__init__(parent)
        self._chat = chat_widget
        self.current_state = "idle"
        self.is_animating = False
        self._dots_phase = 0
        self._dots_timer = None
        self._character_name = ""
        self._watchdog_timer = None
        if self._chat is not None and hasattr(self._chat, "status_dismissed"):
            self._chat.status_dismissed.connect(self._on_status_dismissed)
        self.hide()  # this widget itself is never shown

    def _get_chat(self):
        return self._chat

    @staticmethod
    def _status_icon(icon_names, *, fallback: str, color: str):
        names = icon_names if isinstance(icon_names, (list, tuple)) else [icon_names]
        for icon_name in names:
            if not icon_name:
                continue
            try:
                return qta.icon(str(icon_name), color=color).pixmap(24, 24)
            except Exception:
                continue
        return qta.icon(fallback, color=color).pixmap(24, 24)

    def show_thinking(self, payload="Мита"):
        chat = self._get_chat()
        if isinstance(payload, dict):
            # Фоновые статусы (сжатие/инструмент) НЕ должны затирать висящую
            # терминальную ошибку — её снимает только новый запрос или крестик.
            if self.current_state == "error":
                return
            text = str(payload.get("text") or "").strip()
            state = str(payload.get("state") or "status").strip() or "status"
            if not text:
                text = _("Сжатие истории...", "Compressing history...")

            self.current_state = state
            self._character_name = ""
            self._dots_phase = 0
            self._stop_dots()
            self._arm_watchdog()

            if chat:
                icon = self._status_icon(
                    payload.get("icon_names"),
                    fallback="fa6s.circle-info",
                    color="#b74b7d",
                )
                chat.show_status(text, icon)
            return

        # payload — имя персонажа: это старт НОВОГО запроса пользователя. Даже
        # если висит терминальная ошибка прошлой попытки, новый запрос её
        # снимает (show_typing прячет крестик и текст ошибки) — иначе ошибка
        # «залипает» поверх уже удачного ответа (фидбэк).
        character_name = str(payload or "Мита")
        if self.current_state == "thinking" and self._character_name == character_name:
            return
        self.current_state = "thinking"
        self._character_name = character_name
        self._dots_phase = 0
        self._arm_watchdog()

        if chat:
            from ui.chat.message_widget import _get_avatar_pixmap

            avatar = _get_avatar_pixmap(character_name, "assistant")
            chat.show_typing(
                _(f"{character_name} думает", f"{character_name} is thinking"),
                avatar,
            )
            self._start_dots()

    def show_voicing(self, payload=None):
        if self.current_state == "error":
            return
        self.current_state = "voicing"
        self._stop_dots()
        self._arm_watchdog()
        chat = self._get_chat()
        if chat:
            data = payload if isinstance(payload, dict) else {}
            character_name = str(data.get("character_name") or data.get("name") or "").strip()
            text = str(data.get("text") or "").strip()
            if not text:
                text = (
                    _("Озвучивает: {name}", "Voicing: {name}").format(name=character_name)
                    if character_name
                    else _("Озвучивает...", "Voicing...")
                )
            icon = self._status_icon(
                data.get("icon_names"),
                fallback="fa6s.volume-high",
                color="#b74b7d",
            )
            chat.show_status(text, icon)

    def hide_voicing(self):
        if self.current_state != "voicing":
            return
        self.hide_animated()

    def hide_compression(self):
        # Гасим статус сжатия только если сейчас показан именно он. Так фоновое
        # сжатие, завершившись, не собьёт реальный «думает» активного чата.
        if self.current_state not in ("compression", "status"):
            return
        self.hide_animated()

    def show_error(self, error_message=None):
        if error_message is None:
            error_message = _("Произошла ошибка", "Error occurred")
        self.current_state = "error"
        self._stop_dots()
        self._disarm_watchdog()
        chat = self._get_chat()
        if chat:
            icon = qta.icon("fa6s.triangle-exclamation", color="#b74b7d").pixmap(24, 24)
            chat.show_status(str(error_message), icon, dismissible=True)

    def show_success(self, message=None):
        if self.current_state == "error":
            return
        if message is None:
            message = _("Готово", "Done")
        self.current_state = "success"
        self._stop_dots()
        self._disarm_watchdog()
        chat = self._get_chat()
        if chat:
            icon = qta.icon("fa6s.circle-check", color="#77d188").pixmap(24, 24)
            chat.show_status(str(message), icon)
            QTimer.singleShot(2000, self.hide_animated)

    def pulse_error_animation(self):
        """Quick flash on thinking state to indicate a transient error."""
        pass

    def hide_animated(self):
        if self.current_state in ("idle", "error"):
            return
        self.current_state = "idle"
        self._stop_dots()
        self._disarm_watchdog()
        chat = self._get_chat()
        if chat:
            chat.hide_typing()

    def _on_status_dismissed(self):
        self.current_state = "idle"
        self._stop_dots()
        self._disarm_watchdog()

    def _arm_watchdog(self):
        self._disarm_watchdog()
        self._watchdog_timer = QTimer()
        self._watchdog_timer.setSingleShot(True)
        self._watchdog_timer.timeout.connect(self._on_watchdog)
        self._watchdog_timer.start(_BUSY_WATCHDOG_MS)

    def _disarm_watchdog(self):
        if self._watchdog_timer:
            self._watchdog_timer.stop()
            self._watchdog_timer = None

    def _on_watchdog(self):
        if self.current_state in ("thinking", "status", "compression", "voicing"):
            logger.warning(
                f"MitaStatusWidget: status '{self.current_state}' hung for "
                f"{_BUSY_WATCHDOG_MS // 1000}s; clearing by timeout"
            )
            self.hide_animated()

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

    def set_pulse_intensity(self, factor):
        pass

    @property
    def pulseIntensity(self):
        return 0.0

    @pulseIntensity.setter
    def pulseIntensity(self, value):
        pass

    def setGeometry(self, *args, **kwargs):
        """Ignore geometry calls - we're not a visible widget."""
        pass
