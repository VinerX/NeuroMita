# src/ui/settings/microphone_settings/nanogpt_asr.py
from __future__ import annotations

import io
import json
import os
import wave
from pathlib import Path

from PyQt6.QtCore import Qt, QUrl
from PyQt6.QtGui import QDesktopServices
from PyQt6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QFormLayout,
    QLabel,
    QLineEdit,
    QComboBox,
    QPushButton,
)

from core.error_utils import format_exception
from ui.gui_templates import SettingsBodyWidget
from utils import getTranslationVariant as _

try:
    import qtawesome as qta
except Exception:
    qta = None

KNOWN_MODELS = (
    "Whisper-Large-V3",
    "gpt-4o-mini-transcribe",
    "xai/speech-to-text/v1",
    "whisper-1",
    "Wizper",
    "fun-asr-flash-2026-06-15",
)

LANGUAGES = (
    ("ru", "Русский (ru)"),
    ("en", "English (en)"),
    ("auto", "Автоопределение (auto)"),
)


from handlers.asr_models.nanogpt_recognizer import (
    find_nanogpt_key_in_api_presets,
    load_nanogpt_asr_config,
    save_nanogpt_asr_config,
)


class NanoGPTAsrSettings(SettingsBodyWidget):
    """
    Панель настроек распознавания речи через NanoGPT (Whisper Large V3).
    Позволяет ввести ключ, выбрать модель, протестировать подключение и
    скопировать ключ из общих настроек API в один клик.
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self._worker = None

        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 6, 4, 6)
        layout.setSpacing(6)

        header_lbl = QLabel(_("Параметры NanoGPT (Облачный Whisper)", "NanoGPT Settings (Cloud Whisper)"))
        header_lbl.setStyleSheet("font-weight: bold; color: #f2b6d8; font-size: 10.5pt;")
        layout.addWidget(header_lbl)

        form = QFormLayout()
        form.setContentsMargins(0, 2, 0, 2)
        form.setSpacing(6)

        # 1. Поле API ключа с кнопкой показа пароля
        key_widget = QWidget()
        key_layout = QHBoxLayout(key_widget)
        key_layout.setContentsMargins(0, 0, 0, 0)
        key_layout.setSpacing(4)

        self.key_input = QLineEdit()
        self.key_input.setEchoMode(QLineEdit.EchoMode.Password)
        self.key_input.setPlaceholderText("sk-nano-...")
        key_layout.addWidget(self.key_input, 1)

        self.toggle_eye_btn = QPushButton()
        self.toggle_eye_btn.setObjectName("SecondaryButton")
        self.toggle_eye_btn.setFixedSize(28, 26)
        self.toggle_eye_btn.setToolTip(_("Показать/скрыть ключ", "Show/hide key"))
        if qta:
            try:
                self.toggle_eye_btn.setIcon(qta.icon("fa5s.eye", color="#ffffff"))
            except Exception:
                self.toggle_eye_btn.setText("👁")
        else:
            self.toggle_eye_btn.setText("👁")
        self.toggle_eye_btn.clicked.connect(self._toggle_password_visibility)
        key_layout.addWidget(self.toggle_eye_btn, 0)

        form.addRow(_("API-ключ NanoGPT", "NanoGPT API Key"), key_widget)

        # 2. Кнопки быстрого получения / импорта ключа
        actions_widget = QWidget()
        actions_layout = QHBoxLayout(actions_widget)
        actions_layout.setContentsMargins(0, 0, 0, 0)
        actions_layout.setSpacing(6)

        self.get_key_btn = QPushButton(_("Получить ключ на сайте", "Get key at website"))
        self.get_key_btn.setObjectName("SecondaryButton")
        if qta:
            try:
                self.get_key_btn.setIcon(qta.icon("fa5s.external-link-alt", color="#ffffff"))
            except Exception:
                pass
        self.get_key_btn.clicked.connect(lambda: QDesktopServices.openUrl(QUrl("https://nano-gpt.com/api")))
        actions_layout.addWidget(self.get_key_btn, 1)

        self.copy_key_btn = QPushButton(_("Взять ключ из настроек API", "Copy from API settings"))
        self.copy_key_btn.setObjectName("SecondaryButton")
        if qta:
            try:
                self.copy_key_btn.setIcon(qta.icon("fa5s.copy", color="#ffffff"))
            except Exception:
                pass
        self.copy_key_btn.clicked.connect(self._copy_key_from_api_presets)
        actions_layout.addWidget(self.copy_key_btn, 1)

        form.addRow("", actions_widget)

        # 3. Модель распознавания
        self.model_combo = QComboBox()
        self.model_combo.setEditable(True)
        self.model_combo.addItems(KNOWN_MODELS)
        self.model_combo.setToolTip(_(
            "Рекомендуется Whisper-Large-V3 для наилучшей точности и скорости.",
            "Whisper-Large-V3 is recommended for best accuracy and speed."
        ))
        form.addRow(_("Модель Whisper", "Whisper model"), self.model_combo)

        # 4. Язык
        self.lang_combo = QComboBox()
        for code, label in LANGUAGES:
            self.lang_combo.addItem(label, code)
        form.addRow(_("Язык речи", "Speech language"), self.lang_combo)

        layout.addLayout(form)

        # 5. Кнопка проверки подключения
        self.test_btn = QPushButton(_("Проверить ключ и подключение", "Test key & connection"))
        self.test_btn.setObjectName("SecondaryButton")
        if qta:
            try:
                self.test_btn.setIcon(qta.icon("fa5s.plug", color="#ffffff"))
            except Exception:
                pass
        self.test_btn.clicked.connect(self._test_connection)
        layout.addWidget(self.test_btn)

        # 6. Статус и подсказка
        self.status_label = QLabel()
        self.status_label.setWordWrap(True)
        layout.addWidget(self.status_label)

        hint = QLabel(_(
            "Настройки сохраняются автоматически. Ключ хранится локально на вашем ПК.",
            "Settings are saved automatically. Key is stored locally on your PC."
        ))
        hint.setObjectName("SeparatorLabel")
        hint.setWordWrap(True)
        hint.setStyleSheet("font-size: 8pt; color: #888888;")
        layout.addWidget(hint)

        # Загрузка текущих значений
        cfg = load_nanogpt_asr_config()
        self.key_input.setText(cfg.get("api_key", ""))
        self.model_combo.setCurrentText(cfg.get("model", "Whisper-Large-V3"))
        lang = cfg.get("language", "ru")
        idx = self.lang_combo.findData(lang)
        if idx >= 0:
            self.lang_combo.setCurrentIndex(idx)

        # Автосохранение при изменении
        self.key_input.editingFinished.connect(self._save)
        self.model_combo.currentTextChanged.connect(self._save)
        self.lang_combo.currentIndexChanged.connect(self._save)

    def _toggle_password_visibility(self):
        if self.key_input.echoMode() == QLineEdit.EchoMode.Password:
            self.key_input.setEchoMode(QLineEdit.EchoMode.Normal)
            if qta:
                try:
                    self.toggle_eye_btn.setIcon(qta.icon("fa5s.eye-slash", color="#ffffff"))
                except Exception:
                    pass
        else:
            self.key_input.setEchoMode(QLineEdit.EchoMode.Password)
            if qta:
                try:
                    self.toggle_eye_btn.setIcon(qta.icon("fa5s.eye", color="#ffffff"))
                except Exception:
                    pass

    def _copy_key_from_api_presets(self):
        found_key = find_nanogpt_key_in_api_presets()
        if found_key:
            self.key_input.setText(found_key)
            self._save()
            self.status_label.setStyleSheet("color: #4caf50;")
            self.status_label.setText(_(
                "✓ Ключ NanoGPT успешно скопирован из настроек API и сохранён.",
                "✓ NanoGPT key successfully copied from API settings and saved."
            ))
        else:
            self.status_label.setStyleSheet("color: #e57373;")
            self.status_label.setText(_(
                "В настройках API не найден ключ NanoGPT. Введите ключ вручную или нажмите 'Получить ключ'.",
                "No NanoGPT key found in API settings. Enter it manually or click 'Get key'."
            ))

    def _get_config(self) -> dict[str, str]:
        lang = self.lang_combo.currentData()
        if not lang:
            lang = "ru"
        return {
            "api_key": self.key_input.text().strip(),
            "model": self.model_combo.currentText().strip() or "Whisper-Large-V3",
            "language": str(lang),
        }

    def _save(self, *_args):
        cfg = self._get_config()
        save_nanogpt_asr_config(cfg)
        self.status_label.setStyleSheet("color: #999999;")
        self.status_label.setText(_("Сохранено", "Saved"))

    def _test_connection(self):
        if self._worker is not None and self._worker.isRunning():
            return

        cfg = self._get_config()
        key = cfg["api_key"]
        if not key:
            self.status_label.setStyleSheet("color: #e57373;")
            self.status_label.setText(_("Укажите API-ключ перед проверкой.", "Specify API key before testing."))
            return

        save_nanogpt_asr_config(cfg)

        model = cfg["model"]
        self.test_btn.setEnabled(False)
        self.status_label.setStyleSheet("color: #64b5f6;")
        self.status_label.setText(_("Проверка подключения к NanoGPT...", "Testing connection to NanoGPT..."))

        def work():
            import requests
            buf = io.BytesIO()
            with wave.open(buf, "wb") as wf:
                wf.setnchannels(1)
                wf.setsampwidth(2)
                wf.setframerate(16000)
                wf.writeframes(b"\x00\x00" * 16000)  # 1.0s silence
            buf.seek(0)

            res = requests.post(
                "https://nano-gpt.com/api/transcribe",
                headers={"x-api-key": key},
                files={"file": ("test.wav", buf.read(), "audio/wav")},
                data={"model": model, "language": cfg["language"]},
                timeout=12,
            )
            return res.status_code, res.text

        from controllers.gui.task_worker import TaskWorker
        self._worker = TaskWorker(work, task_key="nanogpt-asr-test", owner=self)

        def on_finished(result):
            status_code, text = result
            if status_code == 200:
                self.status_label.setStyleSheet("color: #81c784; font-weight: bold;")
                self.status_label.setText(_(
                    "✓ Подключение успешно! Ключ и модель работают корректно.",
                    "✓ Connection successful! Key and model are working properly."
                ))
            elif status_code in (401, 403):
                self.status_label.setStyleSheet("color: #e57373;")
                self.status_label.setText(_(
                    "✗ Ошибка авторизации (401/403): неверный API-ключ или нет доступа.",
                    "✗ Auth error (401/403): invalid API key or access denied."
                ))
            else:
                self.status_label.setStyleSheet("color: #e57373;")
                self.status_label.setText(_(
                    f"✗ Ошибка сервера (HTTP {status_code}): {text[:100]}",
                    f"✗ Server error (HTTP {status_code}): {text[:100]}"
                ))

        def on_error(err_str):
            self.status_label.setStyleSheet("color: #e57373;")
            self.status_label.setText(_(f"✗ Ошибка сети: {err_str}", f"✗ Network error: {err_str}"))

        self._worker.finished_signal.connect(on_finished)
        self._worker.error_signal.connect(on_error)
        self._worker.finished.connect(lambda: self.test_btn.setEnabled(True))

        if not self._worker.start():
            self.test_btn.setEnabled(True)
            self.status_label.setText(_("Дождитесь завершения проверки.", "Wait for the test to complete."))
