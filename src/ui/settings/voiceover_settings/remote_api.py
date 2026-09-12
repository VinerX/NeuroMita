from dataclasses import replace

import qtawesome as qta
from PyQt6.QtCore import QSignalBlocker
from PyQt6.QtGui import QDesktopServices
from PyQt6.QtCore import QUrl
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QFormLayout, QComboBox, QLineEdit,
    QPushButton, QLabel, QDoubleSpinBox, QPlainTextEdit,
)
from ui.settings.voiceover_settings.remote_presentation import (
    LoadRemoteVoice, SaveRemoteVoice, SelectRemoteVoice, AddRemoteVoice,
    DeleteRemoteVoice, PreviewRemoteVoice,
)
from localization.live import tr_set
from styles.theme import get_theme


class RemoteVoiceSettingsWidget(QWidget):
    def __init__(self, view_model, parent=None):
        super().__init__(parent)
        self.setObjectName("RemoteVoiceWorkspace")
        self._icon_color = get_theme()["muted"]
        self._vm = view_model
        self._preset = None
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 4, 0, 0)
        layout.setSpacing(10)
        self.controls = QWidget()
        body = QVBoxLayout(self.controls)
        body.setContentsMargins(0, 0, 0, 0)
        body.setSpacing(10)
        form = QFormLayout()
        form.setSpacing(10)
        form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow)
        self.profiles = QComboBox()
        profile_row = QHBoxLayout()
        profile_row.addWidget(self.profiles, 1)
        self.add_button = self._icon_button("fa5s.plus", "Создать профиль из шаблона", "Create profile from template")
        self.delete_button = self._icon_button("fa5s.trash-alt", "Удалить профиль", "Delete profile")
        profile_row.addWidget(self.add_button)
        profile_row.addWidget(self.delete_button)
        form.addRow(self._label("Профиль", "Profile"), profile_row)
        self.provider = QComboBox()
        for template in view_model.templates:
            self.provider.addItem(template.name, template.id)
        form.addRow(self._label("Провайдер", "Provider"), self.provider)
        self.name = QLineEdit()
        self.name.setMaxLength(80)
        form.addRow(self._label("Название", "Name"), self.name)
        self.key = QLineEdit()
        self.key.setEchoMode(QLineEdit.EchoMode.Password)
        tr_set(self.key, "API ключ Fish Audio", "Fish Audio API key", "setPlaceholderText")
        self.key.addAction(qta.icon("fa5s.key", color=self._icon_color), QLineEdit.ActionPosition.LeadingPosition)
        self.eye = self.key.addAction(qta.icon("fa5s.eye", color=self._icon_color), QLineEdit.ActionPosition.TrailingPosition)
        tr_set(self.eye, "Показать API ключ", "Show API key", "setToolTip")
        self.eye.triggered.connect(self._toggle_key)
        key_row = QHBoxLayout()
        key_row.addWidget(self.key, 1)
        self.keys_button = self._icon_button("fa5s.external-link-alt", "Получить API ключ", "Get API key")
        key_row.addWidget(self.keys_button)
        form.addRow(self._label("API ключ", "API key"), key_row)
        self.voice = QLineEdit()
        tr_set(self.voice, "ID голоса или ссылка на голос Fish Audio", "Voice ID or Fish Audio voice URL", "setPlaceholderText")
        voice_row = QHBoxLayout()
        voice_row.addWidget(self.voice, 1)
        self.voices_button = self._icon_button("fa5s.search", "Открыть каталог голосов", "Browse voices")
        voice_row.addWidget(self.voices_button)
        form.addRow(self._label("Голос", "Voice"), voice_row)
        self.model = QComboBox()
        form.addRow(self._label("Модель", "Model"), self.model)
        self.speed = QDoubleSpinBox()
        self.speed.setRange(0.5, 2.0)
        self.speed.setSingleStep(0.1)
        self.speed.setSuffix(" ×")
        form.addRow(self._label("Скорость", "Speed"), self.speed)
        body.addLayout(form)
        hint = tr_set(QLabel(), "Адрес API задан шаблоном. Ключи не попадают в логи.", "The template supplies the API URL. Keys are omitted from logs.")
        hint.setObjectName("RemoteVoiceHint")
        hint.setWordWrap(True)
        body.addWidget(hint)
        self.sample = QPlainTextEdit("Привет! Я Мита. Давай проверим, как звучит мой голос.")
        self.sample.setMaximumHeight(80)
        tr_set(self.sample, "Текст для проверки голоса", "Voice preview text", "setPlaceholderText")
        body.addWidget(self.sample)
        buttons = QHBoxLayout()
        self.save_button = tr_set(QPushButton(), "Сохранить", "Save")
        self.save_button.setObjectName("RemoteVoiceSave")
        self.save_button.setIcon(qta.icon("fa5s.save", color=self._icon_color))
        self.preview_button = tr_set(QPushButton(), "Проверить и прослушать", "Test and listen")
        self.preview_button.setObjectName("RemoteVoicePreview")
        self.preview_button.setIcon(qta.icon("fa5s.play", color=self._icon_color))
        buttons.addWidget(self.save_button)
        buttons.addWidget(self.preview_button)
        body.addLayout(buttons)
        quota = tr_set(QLabel(), "Проверка отправляет текст провайдеру и расходует баланс API.", "Preview sends text to the provider and uses your API balance.")
        quota.setObjectName("RemoteVoiceHint")
        quota.setWordWrap(True)
        body.addWidget(quota)
        layout.addWidget(self.controls)
        self.status = QLabel()
        self.status.setWordWrap(True)
        layout.addWidget(self.status)
        self.profiles.currentIndexChanged.connect(self._select)
        self.provider.currentIndexChanged.connect(self._template_changed)
        self.add_button.clicked.connect(lambda: view_model.dispatch(AddRemoteVoice(self.provider.currentData(), self._draft())))
        self.delete_button.clicked.connect(lambda: view_model.dispatch(DeleteRemoteVoice(self._preset.id)))
        self.save_button.clicked.connect(lambda: view_model.dispatch(SaveRemoteVoice(self._draft())))
        self.preview_button.clicked.connect(lambda: view_model.dispatch(PreviewRemoteVoice(self._draft(), self.sample.toPlainText())))
        self.keys_button.clicked.connect(lambda: self._open("keys_url"))
        self.voices_button.clicked.connect(lambda: self._open("voices_url"))
        view_model.state_changed.connect(self._render)
        self._render(view_model.state)
        view_model.dispatch(LoadRemoteVoice())

    def _label(self, ru, en):
        label = tr_set(QLabel(), ru, en)
        label.setFixedWidth(140)
        return label

    def _icon_button(self, icon, tooltip, english_tooltip):
        button = QPushButton()
        button.setObjectName("RemoteVoiceIconButton")
        button.setIcon(qta.icon(icon, color=self._icon_color))
        tr_set(button, tooltip, english_tooltip, "setToolTip")
        button.setFixedSize(32, 32)
        return button

    def _toggle_key(self):
        hidden = self.key.echoMode() == QLineEdit.EchoMode.Password
        self.key.setEchoMode(QLineEdit.EchoMode.Normal if hidden else QLineEdit.EchoMode.Password)
        self.eye.setIcon(qta.icon("fa5s.eye-slash" if hidden else "fa5s.eye", color=self._icon_color))
        tr_set(self.eye, "Скрыть API ключ" if hidden else "Показать API ключ", "Hide API key" if hidden else "Show API key", "setToolTip")

    def _template_changed(self):
        template = next(t for t in self._vm.templates if t.id == self.provider.currentData())
        self.model.clear()
        self.model.addItems(template.models)
        self.model.setCurrentText(template.default_model)

    def _open(self, attribute):
        template = next(t for t in self._vm.templates if t.id == self.provider.currentData())
        QDesktopServices.openUrl(QUrl(getattr(template, attribute)))

    def _draft(self):
        return replace(self._preset, name=self.name.text(), template_id=self.provider.currentData(),
                       api_key=self.key.text(), voice_id=self.voice.text(), model=self.model.currentText(), speed=self.speed.value())

    def _select(self):
        selected = self.profiles.currentData()
        if selected and self._preset and selected != self._preset.id:
            self._vm.dispatch(SelectRemoteVoice(selected, self._draft()))

    def _render(self, state):
        self.controls.setEnabled(not state.busy and state.configuration is not None)
        self.status.setText("Выполняется…" if state.busy else state.message)
        self.status.setStyleSheet("color: #ef9292;" if state.error else "")
        if state.error and self._preset is not None:
            blocker = QSignalBlocker(self.profiles)
            self.profiles.setCurrentIndex(self.profiles.findData(self._preset.id))
            del blocker
        if state.configuration is None or state.busy or state.error:
            return
        config = state.configuration
        self._preset = config.active
        blocker = QSignalBlocker(self.profiles)
        self.profiles.clear()
        for preset in config.presets:
            self.profiles.addItem(preset.name, preset.id)
        self.profiles.setCurrentIndex(self.profiles.findData(config.active_id))
        del blocker
        self.provider.setCurrentIndex(self.provider.findData(self._preset.template_id))
        self._template_changed()
        self.name.setText(self._preset.name)
        self.key.setText(self._preset.api_key)
        self.key.setEchoMode(QLineEdit.EchoMode.Password)
        self.eye.setIcon(qta.icon("fa5s.eye", color=self._icon_color))
        tr_set(self.eye, "Показать API ключ", "Show API key", "setToolTip")
        self.voice.setText(self._preset.voice_id)
        self.model.setCurrentText(self._preset.model)
        self.speed.setValue(self._preset.speed)
        self.delete_button.setEnabled(len(config.presets) > 1)
