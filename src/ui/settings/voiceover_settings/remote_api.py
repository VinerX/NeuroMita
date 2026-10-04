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
    VoiceCharacter,
)
from core.remote_voice import RemoteCharacterVoice
from ui.widgets.character_voice_tabs import CharacterVoiceTabs
from localization.live import tr_set
from styles.theme import get_theme


class RemoteVoiceSettingsWidget(QWidget):
    def __init__(self, view_model, parent=None):
        super().__init__(parent)
        self.setObjectName("RemoteVoiceWorkspace")
        self._icon_color = get_theme()["muted"]
        self._vm = view_model
        self._preset = None
        self._selected_voice_id = None
        self._default_voice = ""
        self._character_voices = {}
        self._default_voice_name = ""
        self._voice_names = {}
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
        self.voice.setMinimumHeight(38)
        self.voice_display_name = QLineEdit()
        self.voice_display_name.setMaxLength(80)
        tr_set(self.voice_display_name, "Например: «Кэппи · мягкий голос»", "For example: Cappie · soft voice", "setPlaceholderText")
        tr_set(self.voice, "ID голоса или ссылка на голос Fish Audio", "Voice ID or Fish Audio voice URL", "setPlaceholderText")
        voice_row = QHBoxLayout()
        voice_row.addWidget(self.voice, 1)
        self.voices_button = self._icon_button("fa5s.search", "Открыть каталог голосов", "Browse voices")
        self.voices_button.setFixedSize(44, 44)
        voice_row.addWidget(self.voices_button)
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
        voice_title = tr_set(QLabel(), "Голоса персонажей", "Character voices")
        voice_title.setObjectName("RemoteVoiceTitle")
        body.addWidget(voice_title)
        self.voice_tabs = CharacterVoiceTabs()
        voice_card_layout = self.voice_tabs.content_layout
        voice_card_layout.addWidget(tr_set(QLabel(), "Название голоса", "Voice display name"))
        voice_card_layout.addWidget(self.voice_display_name)
        voice_card_layout.addLayout(voice_row)
        self.voice_hint = QLabel()
        self.voice_hint.setObjectName("RemoteVoiceHint")
        self.voice_hint.setWordWrap(True)
        voice_card_layout.addWidget(self.voice_hint)
        body.addWidget(self.voice_tabs)
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
        self.preview_button.clicked.connect(lambda: view_model.dispatch(PreviewRemoteVoice(self._draft(), self.sample.toPlainText(), self._selected_voice_id)))
        self.voice_tabs.currentChanged.connect(self._select_character_voice)
        self.voice.textChanged.connect(self._update_voice_hint)
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
        self._capture_voice()
        return replace(self._preset, name=self.name.text(), template_id=self.provider.currentData(),
                       api_key=self.key.text(), voice_id=self._default_voice, model=self.model.currentText(), speed=self.speed.value(),
                       voice_display_name=self._default_voice_name,
                       character_voices=tuple(RemoteCharacterVoice(cid, self._character_voices.get(cid, ""), self._voice_names.get(cid, ""))
                                              for cid in dict.fromkeys((*self._character_voices, *self._voice_names))
                                              if self._character_voices.get(cid, "").strip() or self._voice_names.get(cid, "").strip()))

    def _capture_voice(self):
        if self._selected_voice_id is None:
            self._default_voice = self.voice.text()
            self._default_voice_name = self.voice_display_name.text()
        else:
            self._character_voices[self._selected_voice_id] = self.voice.text()
            self._voice_names[self._selected_voice_id] = self.voice_display_name.text()

    def _select_character_voice(self, index):
        if self._preset is None or index < 0:
            return
        self._capture_voice()
        self._selected_voice_id = self.voice_tabs.tabData(index)
        self._show_character_voice()

    def _show_character_voice(self):
        voice = self._default_voice if self._selected_voice_id is None else self._character_voices.get(self._selected_voice_id, "")
        self.voice.setText(voice)
        name = self._default_voice_name if self._selected_voice_id is None else self._voice_names.get(self._selected_voice_id, "")
        self.voice_display_name.setText(name)
        self._update_voice_hint()

    def _update_voice_hint(self):
        if self._selected_voice_id is None:
            tr_set(self.voice_hint, "Используется для персонажей без отдельного голоса.", "Used for characters without an individual voice.")
        elif self.voice.text().strip():
            tr_set(self.voice_hint, "Отдельный голос для выбранного персонажа.", "Individual voice for the selected character.")
        elif self._default_voice.strip():
            tr_set(self.voice_hint, "Пока используется общий голос. Вставьте ID, чтобы назначить отдельный.", "Using the default voice. Paste a voice ID to assign an individual voice.")
        else:
            tr_set(self.voice_hint, "Голос не назначен. Укажите его здесь или во вкладке «Общий голос».", "No voice assigned. Set it here or in the Default voice tab.")

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
        first_load = self._preset is None
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
        self._default_voice = self._preset.voice_id
        self._default_voice_name = self._preset.voice_display_name
        self._character_voices = {v.character_id: v.voice_id for v in self._preset.character_voices}
        self._voice_names = {v.character_id: v.display_name for v in self._preset.character_voices}
        characters = list(state.characters)
        known_ids = {character.character_id for character in characters}
        characters.extend(VoiceCharacter(cid, cid) for cid in self._character_voices if cid not in known_ids)
        if first_load:
            self._selected_voice_id = state.current_character_id or None
        if self._selected_voice_id not in {c.character_id for c in characters}:
            self._selected_voice_id = None
        self.voice_tabs.set_characters(tuple(characters), self._selected_voice_id)
        self._show_character_voice()
        self.model.setCurrentText(self._preset.model)
        self.speed.setValue(self._preset.speed)
        self.delete_button.setEnabled(len(config.presets) > 1)
