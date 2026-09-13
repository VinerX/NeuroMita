from __future__ import annotations

import asyncio
from pathlib import Path

from PyQt6.QtCore import Qt, QUrl
from PyQt6.QtGui import QDesktopServices
from PyQt6.QtWidgets import (
    QComboBox,
    QDoubleSpinBox,
    QFormLayout,
    QLabel,
    QLineEdit,
    QPushButton,
)
from core.error_utils import format_exception
from ui.gui_templates import SettingsBodyWidget

MODELS = ("s2.1-pro", "s2-pro", "s1", "s2.1-pro-free", "drama-3-preview")


class FishAudioSettings(SettingsBodyWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        from handlers.fish_audio_handler import load_config
        layout = QFormLayout(self)
        layout.setContentsMargins(0, 4, 0, 4)
        self.key = QLineEdit()
        self.key.setEchoMode(QLineEdit.EchoMode.Password)
        self.voice = QLineEdit()
        self.voice.setPlaceholderText("ID голоса или ссылка https://fish.audio/m/…")
        self.model = QComboBox()
        self.model.addItems(MODELS)
        self.speed = QDoubleSpinBox()
        self.speed.setRange(0.5, 2.0)
        self.speed.setSingleStep(0.1)
        self.sample = QLineEdit("Привет! Я Мита. Теперь ты можешь выбрать мой голос.")
        self.status = QLabel()
        self.status.setTextFormat(Qt.TextFormat.PlainText)
        self.status.setWordWrap(True)
        try:
            cfg = load_config()
        except ValueError as exc:
            cfg = {}
            self.status.setText(format_exception(exc))
        self.key.setText(str(cfg.get("api_key", "")))
        self.voice.setText(str(cfg.get("voice_id", "")))
        self.model.setCurrentText(str(cfg.get("model", "s2.1-pro")))
        self.speed.setValue(float(cfg.get("speed", 1.0)))
        layout.addRow("API-ключ Fish Audio", self.key)
        layout.addRow("ID голоса", self.voice)
        catalog = QPushButton("Открыть каталог голосов Fish Audio")
        catalog.clicked.connect(lambda: QDesktopServices.openUrl(QUrl("https://fish.audio/discovery/")))
        layout.addRow(catalog)
        layout.addRow("Модель синтеза", self.model)
        layout.addRow("Скорость", self.speed)
        layout.addRow("Пробная фраза", self.sample)
        self.test = QPushButton("Проверить и прослушать голос")
        self.test.clicked.connect(self._preview)
        layout.addRow(self.test)
        hint = QLabel("Настройки сохраняются автоматически. Доступность голоса зависит от вашего аккаунта и модели Fish Audio. Пробная фраза использует квоту API.")
        hint.setWordWrap(True)
        layout.addRow(hint)
        layout.addRow(self.status)
        self._worker = None
        self.key.editingFinished.connect(self._save)
        self.voice.editingFinished.connect(self._save)
        self.model.currentTextChanged.connect(self._save)
        self.speed.valueChanged.connect(self._save)

    def _config(self):
        return {"api_key": self.key.text().strip(), "voice_id": self.voice.text().strip(),
                "model": self.model.currentText(), "speed": self.speed.value()}

    def _save(self, *_args):
        from handlers.fish_audio_handler import save_config
        try:
            save_config(self._config())
            self.status.setText("Сохранено")
        except OSError:
            self.status.setText("Не удалось сохранить настройки Fish Audio.")

    def _preview(self):
        if self._worker is not None and self._worker.isRunning():
            return
        from handlers.fish_audio_handler import save_config, synthesize, validate_config
        from controllers.gui.task_worker import TaskWorker
        try:
            config = validate_config(self._config())
            save_config(config)
            text = self.sample.text().strip()
            if not text:
                raise ValueError("Введите пробную фразу.")
        except (ValueError, OSError) as exc:
            self.status.setText(format_exception(exc))
            return

        def work():
            async def preview():
                from handlers.audio_handler import AudioHandler
                path = await synthesize(text, config=config)
                try:
                    await AudioHandler.handle_voice_file(path, True, raise_errors=True)
                finally:
                    Path(path).unlink(missing_ok=True)
            asyncio.run(preview())

        self.test.setEnabled(False)
        self.status.setText("Генерация и воспроизведение…")
        self._worker = TaskWorker(work, task_key="fish-audio-preview", owner=self)
        self._worker.finished_signal.connect(lambda _result: self.status.setText("Голос успешно сгенерирован и воспроизведён."))
        self._worker.error_signal.connect(self.status.setText)
        self._worker.finished.connect(lambda: self.test.setEnabled(True))
        if not self._worker.start():
            self.test.setEnabled(True)
            self.status.setText("Дождитесь завершения предыдущей проверки.")
