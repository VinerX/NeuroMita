from dataclasses import replace
from html import escape

import qtawesome as qta
from PyQt6.QtCore import QSignalBlocker, Qt
from PyQt6.QtGui import QDesktopServices
from PyQt6.QtCore import QUrl
from PyQt6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QFormLayout,
    QComboBox,
    QLineEdit,
    QPushButton,
    QLabel,
    QDoubleSpinBox,
    QPlainTextEdit,
    QAbstractSpinBox,
)
from ui.settings.voiceover_settings.remote_presentation import (
    LoadRemoteVoice,
    SaveRemoteVoice,
    SelectRemoteVoice,
    AddRemoteVoice,
    DeleteRemoteVoice,
    PreviewRemoteVoice,
    VoiceCharacter,
    remote_voice_message,
)
from core.remote_voice import RemoteCharacterVoice
from ui.character_names import character_display_name
from ui.widgets.character_voice_tabs import CharacterVoiceTabs
from localization import translate
from localization.live import tr_set, register
from styles.theme import get_theme
from ui.settings.voiceover_settings.widgets import VoiceCard, voice_label


class RemoteVoiceSettingsWidget(QWidget):
    def __init__(self, view_model, parent=None, *, detached_preview=False):
        super().__init__(parent)
        self.setObjectName("RemoteVoiceWorkspace")
        self._icon_color = get_theme()["muted"]
        self._vm = view_model
        self._preset = None
        self._selected_voice_id = None
        self._default_voice = ""
        self._character_voices = {}
        self._character_titles = {}
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
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
        self.add_button = self._icon_button(
            "fa5s.plus", "Создать профиль из шаблона", "Create profile from template"
        )
        self.delete_button = self._icon_button(
            "fa5s.trash-alt", "Удалить профиль", "Delete profile"
        )
        profile_row.addWidget(self.add_button)
        profile_row.addWidget(self.delete_button)
        form.addRow(self._label("Профиль", "Profile"), profile_row)
        self.provider = QComboBox()
        for template in view_model.templates:
            self.provider.addItem(template.name, template.id)
        if len(view_model.templates) > 1:
            form.addRow(self._label("Провайдер", "Provider"), self.provider)
        else:
            self.provider.hide()
        self.key = QLineEdit()
        self.key.setEchoMode(QLineEdit.EchoMode.Password)
        tr_set(
            self.key, "API ключ Fish Audio", "Fish Audio API key", "setPlaceholderText"
        )
        self.key.addAction(
            qta.icon("fa5s.key", color=self._icon_color),
            QLineEdit.ActionPosition.LeadingPosition,
        )
        self.eye = self.key.addAction(
            qta.icon("fa5s.eye", color=self._icon_color),
            QLineEdit.ActionPosition.TrailingPosition,
        )
        tr_set(self.eye, "Показать API ключ", "Show API key", "setToolTip")
        self.eye.triggered.connect(self._toggle_key)
        key_row = QHBoxLayout()
        key_row.addWidget(self.key, 1)
        self.keys_button = self._icon_button(
            "fa5s.external-link-alt", "Получить API ключ", "Get API key"
        )
        key_row.addWidget(self.keys_button)
        form.addRow(self._label("API ключ", "API key"), key_row)
        self.voice = QLineEdit()
        self.voice.setMinimumHeight(38)
        tr_set(
            self.voice,
            "ID голоса или ссылка на голос Fish Audio",
            "Voice ID or Fish Audio voice URL",
            "setPlaceholderText",
        )
        voice_row = QHBoxLayout()
        voice_row.addWidget(self.voice, 1)
        self.voices_button = self._icon_button(
            "fa5s.search", "Открыть каталог голосов", "Browse voices"
        )
        self.voices_button.setFixedSize(38, 38)
        voice_row.addWidget(self.voices_button)
        self.model = QComboBox()
        form.addRow(self._label("Модель", "Model"), self.model)
        self.model_hint = QLabel()
        self.model_hint.setObjectName("RemoteVoiceHint")
        self.model_hint.setWordWrap(True)
        form.addRow("", self.model_hint)
        self.model.currentTextChanged.connect(self._refresh_model_hint)
        register(self, lambda w: w._refresh_model_hint())
        self.speed = QDoubleSpinBox()
        self.speed.setRange(0.5, 2.0)
        self.speed.setSingleStep(0.1)
        self.speed.setSuffix(" ×")
        self.speed.setButtonSymbols(QAbstractSpinBox.ButtonSymbols.NoButtons)
        self.speed.setKeyboardTracking(False)
        speed_row = QHBoxLayout()
        speed_row.addWidget(self.speed, 1)
        decrease = self._icon_button(
            "fa5s.minus", "Уменьшить скорость", "Decrease speed"
        )
        increase = self._icon_button(
            "fa5s.plus", "Увеличить скорость", "Increase speed"
        )
        decrease.clicked.connect(self.speed.stepDown)
        increase.clicked.connect(self.speed.stepUp)
        speed_row.addWidget(decrease)
        speed_row.addWidget(increase)
        form.addRow(self._label("Скорость", "Speed"), speed_row)
        body.addLayout(form)
        voice_title = tr_set(QLabel(), "Голоса персонажей", "Character voices")
        voice_title.setObjectName("RemoteVoiceTitle")
        body.addWidget(voice_title)
        self.voice_tabs = CharacterVoiceTabs()
        voice_card_layout = self.voice_tabs.content_layout
        self.character_title = QLabel()
        self.character_title.setObjectName("RemoteVoiceTitle")
        voice_card_layout.addWidget(self.character_title)
        self.voice_hint = QLabel()
        self.voice_hint.setObjectName("RemoteVoiceHint")
        self.voice_hint.setWordWrap(True)
        self.voice_hint.setTextFormat(Qt.TextFormat.RichText)
        self.voice_hint.setTextInteractionFlags(
            Qt.TextInteractionFlag.LinksAccessibleByMouse
            | Qt.TextInteractionFlag.LinksAccessibleByKeyboard
        )
        self.voice_hint.linkActivated.connect(lambda _url: self._open("voices_url"))
        tr_set(
            self.voice_hint,
            "Где искать голос? Каталог Fish Audio",
            "Where can I find a voice? Fish Audio catalog",
            transform=lambda text: '<a href="voices" style="color: '
            + get_theme()["accent"]
            + ';">'
            + escape(text)
            + "</a>",
        )
        voice_card_layout.addWidget(self.voice_hint)
        voice_card_layout.addLayout(voice_row)
        body.addWidget(self.voice_tabs)
        self.save_button = tr_set(QPushButton(), "Сохранить профиль", "Save profile")
        self.save_button.setObjectName("RemoteVoiceSave")
        self.save_button.setIcon(qta.icon("fa5s.save", color=self._icon_color))
        body.addWidget(self.save_button, 0, Qt.AlignmentFlag.AlignRight)
        self.preview_panel = VoiceCard(
            "Проверка голоса",
            "Voice preview",
            "fa5s.play",
            "Прослушайте голос выбранного персонажа.",
            "Listen to the selected character voice.",
        )
        preview_layout = self.preview_panel.body
        self.preview_character = QLabel()
        self.preview_character.setObjectName("RemoteVoiceTitle")
        preview_layout.addWidget(self.preview_character)
        self.sample = QPlainTextEdit()
        self._sample_default = ""
        self._refresh_sample()
        register(self, lambda w: w._refresh_sample())
        self.sample.setFixedHeight(88)
        tr_set(
            self.sample,
            "Текст для проверки голоса",
            "Voice preview text",
            "setPlaceholderText",
        )
        preview_layout.addWidget(self.sample)
        self.preview_button = tr_set(
            QPushButton(), "Проверить и прослушать", "Test and listen"
        )
        self.preview_button.setObjectName("RemoteVoicePreview")
        self.preview_button.setIcon(qta.icon("fa5s.play", color=self._icon_color))
        preview_layout.addWidget(self.preview_button)
        self.quota = tr_set(
            QLabel(),
            "Проверка отправляет текст провайдеру. Платные модели расходуют баланс API.",
            "Preview sends text to the provider. Only paid models use your API balance.",
        )
        self.quota.setObjectName("RemoteVoiceHint")
        self.quota.setWordWrap(True)
        preview_layout.addWidget(self.quota)
        layout.addWidget(self.controls)
        self.status = QLabel()
        self.status.setWordWrap(True)
        self.status.setObjectName("VoicePreviewStatus")
        preview_layout.addWidget(self.status)
        if not detached_preview:
            layout.addWidget(self.preview_panel)
        self.profiles.currentIndexChanged.connect(self._select)
        self.provider.currentIndexChanged.connect(self._template_changed)
        self.add_button.clicked.connect(
            lambda: view_model.dispatch(
                AddRemoteVoice(self.provider.currentData(), self._draft())
            )
        )
        self.delete_button.clicked.connect(
            lambda: view_model.dispatch(DeleteRemoteVoice(self._preset.id))
        )
        self.save_button.clicked.connect(
            lambda: view_model.dispatch(SaveRemoteVoice(self._draft()))
        )
        self.preview_button.clicked.connect(
            lambda: view_model.dispatch(
                PreviewRemoteVoice(
                    self._draft(), self.sample.toPlainText(), self._selected_voice_id
                )
            )
        )
        self.voice_tabs.currentChanged.connect(self._select_character_voice)
        self.keys_button.clicked.connect(lambda: self._open("keys_url"))
        self.voices_button.clicked.connect(lambda: self._open("voices_url"))
        view_model.state_changed.connect(self._render)
        register(self, lambda w: w._refresh_dynamic_text())
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
        button.setFixedSize(38, 38)
        return button

    def _toggle_key(self):
        hidden = self.key.echoMode() == QLineEdit.EchoMode.Password
        self.key.setEchoMode(
            QLineEdit.EchoMode.Normal if hidden else QLineEdit.EchoMode.Password
        )
        self.eye.setIcon(
            qta.icon("fa5s.eye-slash" if hidden else "fa5s.eye", color=self._icon_color)
        )
        self._refresh_dynamic_text()

    def _refresh_sample(self):
        text = self.sample.toPlainText()
        translated = str(
            translate(
                "Привет! Я Мита. Давай проверим, как звучит мой голос.",
                "Hi! I'm Mita. Let's hear how my voice sounds.",
            )
        )
        if text == self._sample_default:
            self.sample.setPlainText(translated)
        self._sample_default = translated

    def _refresh_dynamic_text(self):
        hidden = self.key.echoMode() == QLineEdit.EchoMode.Password
        self.eye.setToolTip(
            translate("Показать API ключ", "Show API key")
            if hidden
            else translate("Скрыть API ключ", "Hide API key")
        )
        title = self._character_titles.get(
            self._selected_voice_id, self._selected_voice_id
        )
        self.character_title.setText(
            character_display_name(self._selected_voice_id, title)
            if self._selected_voice_id
            else translate("Общий голос", "Default voice")
        )
        self.preview_character.setText(self.character_title.text())
        state = self._vm.state
        self.status.setVisible(bool(state.busy or state.message))
        self.status.setText(
            translate("Выполняется…", "Working…")
            if state.busy
            else remote_voice_message(state.message)
        )

    def _refresh_model_hint(self):
        free = self.model.currentText() == "s2.1-pro-free"
        self.model_hint.setText(
            translate(
                "Выбрана бесплатная модель. Остальные модели платные.",
                "A free model is selected. The other models are paid.",
            )
            if free
            else translate(
                "Выбрана платная модель. Озвучка расходует баланс API.",
                "A paid model is selected. Speech synthesis uses your API balance.",
            )
        )
        color = get_theme()["muted"] if free else get_theme()["danger"]
        self.model_hint.setStyleSheet(f"color: {color};")

    def _template_changed(self):
        template = next(
            t for t in self._vm.templates if t.id == self.provider.currentData()
        )
        self.model.clear()
        self.model.addItems(template.models)
        self.model.setCurrentText(template.default_model)

    def _open(self, attribute):
        template = next(
            t for t in self._vm.templates if t.id == self.provider.currentData()
        )
        QDesktopServices.openUrl(QUrl(getattr(template, attribute)))

    def _draft(self):
        self._capture_voice()
        names = {v.character_id: v.display_name for v in self._preset.character_voices}
        return replace(
            self._preset,
            template_id=self.provider.currentData(),
            api_key=self.key.text(),
            voice_id=self._default_voice,
            model=self.model.currentText(),
            speed=self.speed.value(),
            character_voices=tuple(
                RemoteCharacterVoice(cid, voice, names.get(cid, ""))
                for cid, voice in self._character_voices.items()
                if voice.strip() or names.get(cid, "").strip()
            ),
        )

    def _capture_voice(self):
        if self._selected_voice_id is None:
            self._default_voice = self.voice.text()
        else:
            self._character_voices[self._selected_voice_id] = self.voice.text()

    def _select_character_voice(self, index):
        if self._preset is None or index < 0:
            return
        self._capture_voice()
        self._selected_voice_id = self.voice_tabs.tabData(index)
        self._show_character_voice()

    def _show_character_voice(self):
        voice = (
            self._default_voice
            if self._selected_voice_id is None
            else self._character_voices.get(self._selected_voice_id, "")
        )
        self.voice.setText(voice)
        self._refresh_dynamic_text()

    def _select(self):
        selected = self.profiles.currentData()
        if selected and self._preset and selected != self._preset.id:
            self._vm.dispatch(SelectRemoteVoice(selected, self._draft()))

    def _render(self, state):
        enabled = not state.busy and state.configuration is not None
        self.controls.setEnabled(enabled)
        self.preview_panel.setEnabled(enabled)
        self._refresh_dynamic_text()
        color = get_theme()["danger"] if state.error else get_theme()["success"]
        if state.busy:
            color = get_theme()["accent"]
        self.status.setStyleSheet(f"color: {color};")
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
        self.key.setText(self._preset.api_key)
        self.key.setEchoMode(QLineEdit.EchoMode.Password)
        self.eye.setIcon(qta.icon("fa5s.eye", color=self._icon_color))
        self._default_voice = self._preset.voice_id
        self._character_voices = {
            v.character_id: v.voice_id for v in self._preset.character_voices
        }
        characters = list(state.characters)
        known_ids = {character.character_id for character in characters}
        characters.extend(
            VoiceCharacter(cid, cid)
            for cid in self._character_voices
            if cid not in known_ids
        )
        self._character_titles = {c.character_id: c.display_name for c in characters}
        if first_load:
            self._selected_voice_id = state.current_character_id or None
        if self._selected_voice_id not in {c.character_id for c in characters}:
            self._selected_voice_id = None
        self.voice_tabs.set_characters(tuple(characters), self._selected_voice_id)
        self._show_character_voice()
        self.model.setCurrentText(self._preset.model)
        self.speed.setValue(self._preset.speed)
        self.delete_button.setEnabled(len(config.presets) > 1)
