from PyQt6.QtCore import QEvent, QObject, QSignalBlocker, QTimer
from PyQt6.QtWidgets import QApplication

from core.audio_input import ASRInputDevice
from localization import translate as _
from localization.live import register
from services.microphone_monitor import MicrophoneMonitor


class MicrophoneMonitorController(QObject):
    def __init__(self, workspace, combo, button, label, meter, monitor=None):
        super().__init__(workspace)
        self.combo, self.button, self.label, self.meter = combo, button, label, meter
        self.monitor = monitor or MicrophoneMonitor()
        self._device_available = True
        self._timer = QTimer(self)
        self._timer.setInterval(40)
        self._timer.timeout.connect(self._render)
        self.button.toggled.connect(self._toggle)
        self.combo.currentIndexChanged.connect(lambda _index: self.stop())
        workspace.installEventFilter(self)
        workspace.destroyed.connect(lambda: self.monitor.close())
        app = QApplication.instance()
        if app:
            app.aboutToQuit.connect(self.monitor.close)
        register(self, lambda w: w._render())
        self._render()

    def eventFilter(self, watched, event):
        if event.type() in {QEvent.Type.Hide, QEvent.Type.Close}:
            self.stop()
        return super().eventFilter(watched, event)

    def set_device_available(self, available):
        self._device_available = bool(available)
        if not available:
            self.stop()
        self._render()

    def _toggle(self, checked):
        if checked:
            device = self.combo.currentData()
            if (
                not self._device_available
                or not isinstance(device, ASRInputDevice)
                or not self.combo.isEnabled()
            ):
                self.stop()
                return
            if not self.monitor.start(device):
                self.stop()
                return
            self._timer.start()
        else:
            self.stop()
        self._render()

    def stop(self):
        self.monitor.stop()
        with QSignalBlocker(self.button):
            self.button.setChecked(False)
        self._timer.start()
        self._render()

    def _render(self):
        state = self.monitor.snapshot()
        active = state.phase in {"starting", "listening"}
        stopping = state.phase == "stopping"
        with QSignalBlocker(self.button):
            self.button.setChecked(active)
        self.button.setEnabled(
            not stopping
            and self._device_available
            and self.combo.isEnabled()
            and isinstance(self.combo.currentData(), ASRInputDevice)
        )
        self.button.setText(
            _("Остановить тест", "Stop test")
            if active
            else _("Проверить микрофон", "Test microphone")
        )
        if state.phase == "error":
            text = _(state.error)
        elif stopping:
            text = _("Остановка теста…", "Stopping test…")
        elif state.device:
            prefix = (
                _("Подключение", "Connecting")
                if state.phase == "starting"
                else _("Вы слушаете", "Listening to")
            )
            text = f"{prefix}: {state.device.label} · ID {state.device.index}"
        else:
            device = self.combo.currentData()
            text = (
                f'{_("Микрофон", "Microphone")}: {device.label} · ID {device.index}'
                if isinstance(device, ASRInputDevice)
                else _("Выберите микрофон для проверки", "Select a microphone to test")
            )
        self.label.setText(text)
        self.meter.set_level(state.level if active else 0)
        if state.phase in {"stopped", "error"}:
            self._timer.stop()
