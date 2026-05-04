from PyQt6.QtCore import QTimer, Qt
from PyQt6.QtWidgets import (
    QComboBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from core.events import Events
from main_logger import logger
from ui.pages.settings.settings_page_widget import get_mode_label
from ui.widgets.chat_panel import ChatPanel
from ui.widgets.status_indicators_widget import create_status_indicators
from utils import _

_MODEL_CONFIGURE_SENTINEL = "__configure_models__"
_TTS_CONFIGURE_SENTINEL = "__configure_tts__"
_ASR_CONFIGURE_SENTINEL = "__configure_asr__"


class SandboxPage(QWidget):
    def __init__(self, gui):
        super().__init__(gui)
        self.gui = gui
        self.setObjectName("SandboxPage")

        self._memory_limit_values = {}
        self._debug_summary_values = {}
        self._chat_panel = None

        self._build_ui()
        self._sync_host_exports()
        self.on_activated()

    def _sync_host_exports(self):
        self.gui.sandbox_page = self

    def _sync_combobox_text(self, combo, value: str):
        if combo is None:
            return

        index = combo.findText(value, Qt.MatchFlag.MatchFixedString)
        if index < 0 or combo.currentIndex() == index:
            return

        combo.blockSignals(True)
        try:
            combo.setCurrentIndex(index)
        finally:
            combo.blockSignals(False)

    def _get_current_character_id(self) -> str:
        try:
            result = self.gui.event_bus.emit_and_wait(Events.Character.GET_CURRENT_PROFILE, timeout=0.5)
            profile = result[0] if result else {}
        except Exception:
            profile = {}
        return str((profile or {}).get("character_id") or "")

    def _jump_to_settings(self, category: str):
        self.gui.switch_main_page("settings")
        self.gui.show_settings_category(category)

    def _populate_model_combobox(self):
        combo = getattr(self.gui, "chat_model_combobox", None)
        if combo is None:
            return

        try:
            result = self.gui.event_bus.emit_and_wait(Events.ApiPresets.GET_PRESET_LIST, timeout=1.0)
            meta = result[0] if result else {}
        except Exception:
            meta = {}

        customs = list((meta or {}).get("custom", []))

        combo.blockSignals(True)
        try:
            combo.clear()

            if customs:
                for preset in customs:
                    preset_id = getattr(preset, "id", None)
                    name = getattr(preset, "name", "")
                    if preset_id is None:
                        continue
                    combo.addItem(str(name), int(preset_id))
                combo.insertSeparator(combo.count())
            else:
                combo.addItem(_("Нет настроенных моделей", "No configured models"), None)
                combo.insertSeparator(combo.count())

            combo.addItem(_("Настроить…", "Configure…"), _MODEL_CONFIGURE_SENTINEL)

            try:
                current_res = self.gui.event_bus.emit_and_wait(Events.ApiPresets.GET_CURRENT_PRESET_ID, timeout=0.5)
                current_id = current_res[0] if current_res else None
            except Exception:
                current_id = None

            if current_id is not None:
                for index in range(combo.count()):
                    if combo.itemData(index) == int(current_id):
                        combo.setCurrentIndex(index)
                        break
        finally:
            combo.blockSignals(False)

    def _on_chat_model_changed(self, index: int):
        combo = getattr(self.gui, "chat_model_combobox", None)
        if combo is None or index < 0:
            return

        data = combo.itemData(index)
        if data == _MODEL_CONFIGURE_SENTINEL:
            QTimer.singleShot(0, self._populate_model_combobox)
            self._jump_to_settings("api")
            return

        if data is None:
            return

        try:
            self.gui.event_bus.emit(Events.ApiPresets.SET_CURRENT_PRESET_ID, {"id": int(data)})
        except Exception as exc:
            logger.error(f"Failed to switch preset: {exc}")

    def _populate_tts_combobox(self):
        combo = getattr(self.gui, "chat_tts_combobox", None)
        if combo is None:
            return

        installed_local: set[str] = set()
        try:
            result = self.gui.event_bus.emit_and_wait(Events.VoiceModel.GET_INSTALLED_MODELS, timeout=0.5)
            models = result[0] if result else None
            if isinstance(models, (set, list, tuple)):
                installed_local = {str(item) for item in models}
        except Exception:
            installed_local = set()

        try:
            from ui.settings.voiceover_settings import LOCAL_VOICE_MODELS
        except Exception:
            LOCAL_VOICE_MODELS = []

        method = str(self.gui._get_setting("VOICEOVER_METHOD", "TG") or "TG")
        selected_local_id = str(self.gui._get_setting("LOCAL_VOICE_MODEL_ID", "") or "")

        combo.blockSignals(True)
        try:
            combo.clear()
            combo.addItem("Telegram (TG)", ("TG", None))

            for model in LOCAL_VOICE_MODELS:
                model_id = str(model.get("id") or "")
                name = str(model.get("name") or model_id)
                if model_id in installed_local:
                    combo.addItem(name, ("Local", model_id))

            combo.insertSeparator(combo.count())
            combo.addItem(_("Настроить…", "Configure…"), (_TTS_CONFIGURE_SENTINEL, None))

            active_index = 0
            for index in range(combo.count()):
                data = combo.itemData(index)
                if not isinstance(data, tuple):
                    continue
                kind, model_id = data
                if method == "TG" and kind == "TG":
                    active_index = index
                    break
                if method == "Local" and kind == "Local" and model_id == selected_local_id:
                    active_index = index
                    break
            combo.setCurrentIndex(active_index)
        finally:
            combo.blockSignals(False)

    def _on_chat_voice_changed(self, index: int):
        combo = getattr(self.gui, "chat_tts_combobox", None)
        if combo is None or index < 0:
            return

        data = combo.itemData(index)
        if not isinstance(data, tuple):
            return

        kind, model_id = data
        if kind == _TTS_CONFIGURE_SENTINEL:
            QTimer.singleShot(0, self._populate_tts_combobox)
            self._jump_to_settings("voice")
            return

        try:
            self.gui.settings.set("VOICEOVER_METHOD", kind)
            if kind == "Local" and model_id:
                self.gui.settings.set("LOCAL_VOICE_MODEL_ID", model_id)
                try:
                    self.gui.event_bus.emit(Events.GUI.VOICEOVER_MODEL_SELECTED, {"model_id": model_id})
                except Exception:
                    pass
        except Exception:
            try:
                self.gui.settings["VOICEOVER_METHOD"] = kind
            except Exception:
                pass

        self._refresh_debug_summary()

    def _populate_asr_combobox(self):
        combo = getattr(self.gui, "chat_asr_combobox", None)
        if combo is None:
            return

        combo.blockSignals(True)
        combo.clear()
        combo.addItem(_("Загрузка…", "Loading…"), None)
        combo.setEnabled(False)
        combo.blockSignals(False)

        def _apply(items):
            combo.blockSignals(True)
            try:
                combo.clear()
                engines = []
                for item in items or []:
                    try:
                        if item.get("installed", False) and item.get("id"):
                            engines.append(str(item["id"]))
                    except Exception:
                        pass

                if engines:
                    for engine in engines:
                        combo.addItem(engine, engine)
                    combo.insertSeparator(combo.count())
                combo.setEnabled(True)

                combo.addItem(_("Настроить…", "Configure…"), _ASR_CONFIGURE_SENTINEL)
                current = str(self.gui._get_setting("RECOGNIZER_TYPE", "") or "")
                for index in range(combo.count()):
                    if combo.itemData(index) == current:
                        combo.setCurrentIndex(index)
                        break
            finally:
                combo.blockSignals(False)

        def callback(result, error=None):
            QTimer.singleShot(0, lambda r=result: _apply(r if isinstance(r, list) else []))

        try:
            self.gui.event_bus.emit(Events.Speech.GET_ASR_MODELS_GLOSSARY, {"callback": callback})
        except Exception:
            _apply([])

    def _on_chat_asr_changed(self, index: int):
        combo = getattr(self.gui, "chat_asr_combobox", None)
        if combo is None or index < 0:
            return

        data = combo.itemData(index)
        if data == _ASR_CONFIGURE_SENTINEL:
            QTimer.singleShot(0, self._populate_asr_combobox)
            self._jump_to_settings("microphone")
            return

        if not data:
            return

        try:
            self.gui.settings.set("RECOGNIZER_TYPE", str(data))
        except Exception:
            try:
                self.gui.settings["RECOGNIZER_TYPE"] = str(data)
            except Exception:
                pass

    def _on_chat_mode_changed(self, value: str):
        value = (value or "").strip()
        if not value:
            return

        try:
            self.gui.settings.set("INTERFACE_MODE", value)
        except Exception:
            try:
                self.gui.settings["INTERFACE_MODE"] = value
            except Exception:
                pass

        try:
            from ui.widgets.settings_panel import apply_interface_mode

            apply_interface_mode(self.gui, value)
        except Exception as exc:
            logger.info(f"apply_interface_mode failed: {exc}")

        self._refresh_debug_summary()

    def _populate_chat_character_combobox(self):
        combo = getattr(self.gui, "chat_character_combobox", None)
        if combo is None:
            return

        all_characters = self.gui.event_bus.emit_and_wait(Events.Character.GET_ALL, timeout=1.0)
        character_list = all_characters[0] if all_characters else ["Crazy"]
        if not character_list:
            character_list = ["Crazy"]

        current_char_id = self._get_current_character_id() or character_list[0]

        combo.blockSignals(True)
        try:
            combo.clear()
            combo.addItems(character_list)
            index = combo.findText(str(current_char_id), Qt.MatchFlag.MatchFixedString)
            if index >= 0:
                combo.setCurrentIndex(index)
        finally:
            combo.blockSignals(False)

    def _on_chat_character_changed(self, character_id):
        character_id = str(character_id or "").strip()
        if not character_id:
            return

        settings_combo = getattr(self.gui, "character_combobox", None)
        if settings_combo is not None and settings_combo.currentText() != character_id:
            index = settings_combo.findText(character_id, Qt.MatchFlag.MatchFixedString)
            if index >= 0:
                settings_combo.setCurrentIndex(index)
                if self._chat_panel is not None:
                    self._chat_panel.on_activated()
                return

        self.gui.event_bus.emit(Events.Character.SET_CURRENT, {"character_id": character_id})
        self.gui.event_bus.emit(Events.Character.RELOAD_DATA)
        if self._chat_panel is not None:
            self._chat_panel.on_activated()

    def _open_selected_character_history(self):
        combo = getattr(self.gui, "chat_character_combobox", None)
        character_id = combo.currentText().strip() if combo is not None else ""
        if character_id:
            self.gui.event_bus.emit(Events.Character.SET_CURRENT, {"character_id": character_id})

        try:
            from ui.settings.character_settings.logic import open_db_viewer

            open_db_viewer(self.gui)
        except Exception as exc:
            logger.error(f"Failed to open character history: {exc}", exc_info=True)

    def _refresh_memory_profile_combo(self):
        combo = getattr(self.gui, "sandbox_memory_profile_combo", None)
        if combo is None:
            return

        try:
            from ui.settings.memory_profile import KEY_TO_LABEL_EN, KEY_TO_LABEL_RU, detect_memory_profile

            lang = str(self.gui._get_setting("LANGUAGE", "RU") or "RU").upper()
            key_to_label = KEY_TO_LABEL_EN if lang == "EN" else KEY_TO_LABEL_RU
            current_label = key_to_label.get(detect_memory_profile(self.gui))
        except Exception:
            current_label = None

        if current_label:
            self._sync_combobox_text(combo, current_label)

    def _refresh_memory_summary(self):
        for key, fallback in (
            ("MODEL_MESSAGE_LIMIT", 35),
            ("MEMORY_CAPACITY", 50),
            ("RAG_MAX_RESULTS", 50),
        ):
            value_label = self._memory_limit_values.get(key)
            if value_label is not None:
                value_label.setText(str(self.gui._get_setting(key, fallback)))

    def _refresh_debug_summary(self):
        values = {
            "voice": str(self.gui._get_setting("VOICEOVER_METHOD", "TG")),
            "screen": _("Включён", "Enabled") if self.gui._get_setting("ENABLE_SCREEN_ANALYSIS", False) else _("Выключен", "Disabled"),
            "camera": _("Включена", "Enabled") if self.gui._get_setting("ENABLE_CAMERA_CAPTURE", False) else _("Выключена", "Disabled"),
            "mode": get_mode_label(self.gui._get_setting("INTERFACE_MODE", _("Базовый", "Basic"))),
        }
        for key, text in values.items():
            label = self._debug_summary_values.get(key)
            if label is not None:
                label.setText(text)

    def _on_memory_profile_changed(self, label: str):
        try:
            from ui.settings.memory_profile import apply_memory_profile
        except Exception:
            apply_memory_profile = None

        if apply_memory_profile is not None:
            apply_memory_profile(self.gui, label)

        try:
            self.gui.settings.set("MEMORY_PROFILE", label)
        except Exception:
            try:
                self.gui.settings["MEMORY_PROFILE"] = label
            except Exception:
                pass

        self._refresh_memory_summary()

    def on_activated(self):
        self._populate_chat_character_combobox()
        self._populate_model_combobox()
        self._populate_tts_combobox()
        self._populate_asr_combobox()
        self._sync_combobox_text(
            getattr(self.gui, "chat_mode_combobox", None),
            get_mode_label(self.gui._get_setting("INTERFACE_MODE", _("Базовый", "Basic"))),
        )
        self._refresh_memory_profile_combo()
        self._refresh_memory_summary()
        self._refresh_debug_summary()
        if self._chat_panel is not None:
            self._chat_panel.on_activated()

    def _make_selector_card(self, title: str) -> tuple[QFrame, QVBoxLayout]:
        card = QFrame()
        card.setObjectName("SandboxSelectorCard")
        layout = QVBoxLayout(card)
        layout.setContentsMargins(14, 12, 14, 12)
        layout.setSpacing(6)

        label = QLabel(title)
        label.setObjectName("SandboxSelectorLabel")
        layout.addWidget(label)
        return card, layout

    def _make_tab_page(self) -> tuple[QWidget, QVBoxLayout]:
        page = QWidget()
        page.setObjectName("SandboxInspectorTabPage")
        layout = QVBoxLayout(page)
        layout.setContentsMargins(2, 12, 2, 4)
        layout.setSpacing(12)
        return page, layout

    def _make_inspector_card(self, title_text: str | None = None) -> tuple[QFrame, QVBoxLayout]:
        card = QFrame()
        card.setObjectName("SandboxInspectorCard")
        layout = QVBoxLayout(card)
        layout.setContentsMargins(14, 14, 14, 14)
        layout.setSpacing(8)
        if title_text:
            title = QLabel(title_text)
            title.setObjectName("SandboxInspectorTitle")
            layout.addWidget(title)
        return card, layout

    def _build_header(self) -> QFrame:
        hero_card = QFrame()
        hero_card.setObjectName("ChatToolbarCard")
        hero_layout = QVBoxLayout(hero_card)
        hero_layout.setContentsMargins(18, 18, 18, 18)
        hero_layout.setSpacing(12)

        title_row = QHBoxLayout()
        title_row.setSpacing(16)

        title_col = QVBoxLayout()
        title_col.setSpacing(4)
        title_label = QLabel(_("Песочница", "Sandbox"))
        title_label.setObjectName("ChatHeroTitle")
        title_col.addWidget(title_label)

        subtitle_label = QLabel(
            _(
                "Экспериментируй, общайся и тестируй возможности NeuroMita в новой launcher-оболочке.",
                "Experiment, chat and test NeuroMita inside the rebuilt launcher shell.",
            )
        )
        subtitle_label.setObjectName("ChatHeroSubtitle")
        subtitle_label.setWordWrap(True)
        title_col.addWidget(subtitle_label)
        title_row.addLayout(title_col, 1)

        guide_button = QPushButton(_("Открыть руководство", "Open guide"))
        guide_button.setObjectName("SecondaryButton")
        guide_button.clicked.connect(self.gui._show_guide)
        title_row.addWidget(guide_button, 0, Qt.AlignmentFlag.AlignTop)
        hero_layout.addLayout(title_row)

        selectors = QHBoxLayout()
        selectors.setSpacing(10)

        character_card, character_layout = self._make_selector_card(_("Персонаж", "Character"))
        self.gui.chat_character_combobox = QComboBox()
        self.gui.chat_character_combobox.setObjectName("ChatCharacterCombo")
        self.gui.chat_character_combobox.setToolTip(_("Выбрать персонажа", "Select character"))
        self.gui.chat_character_combobox.currentTextChanged.connect(self._on_chat_character_changed)
        character_layout.addWidget(self.gui.chat_character_combobox)
        selectors.addWidget(character_card, 2)

        model_card, model_layout = self._make_selector_card(_("Модель", "Model"))
        self.gui.chat_model_combobox = QComboBox()
        self.gui.chat_model_combobox.setObjectName("ChatCharacterCombo")
        self.gui.chat_model_combobox.setToolTip(_("Активный API-пресет (модель)", "Active API preset (model)"))
        self.gui.chat_model_combobox.currentIndexChanged.connect(self._on_chat_model_changed)
        model_layout.addWidget(self.gui.chat_model_combobox)
        selectors.addWidget(model_card, 2)

        tts_card, tts_layout = self._make_selector_card(_("TTS", "TTS"))
        self.gui.chat_tts_combobox = QComboBox()
        self.gui.chat_tts_combobox.setObjectName("ChatCharacterCombo")
        self.gui.chat_tts_combobox.setToolTip(_("Способ озвучки: TG или установленные локальные модели", "Voice output: TG or installed local models"))
        self.gui.chat_tts_combobox.currentIndexChanged.connect(self._on_chat_voice_changed)
        tts_layout.addWidget(self.gui.chat_tts_combobox)
        selectors.addWidget(tts_card, 1)

        asr_card, asr_layout = self._make_selector_card(_("ASR", "ASR"))
        self.gui.chat_asr_combobox = QComboBox()
        self.gui.chat_asr_combobox.setObjectName("ChatCharacterCombo")
        self.gui.chat_asr_combobox.setToolTip(_("Установленные модели распознавания речи", "Installed speech recognition models"))
        self.gui.chat_asr_combobox.currentIndexChanged.connect(self._on_chat_asr_changed)
        asr_layout.addWidget(self.gui.chat_asr_combobox)
        selectors.addWidget(asr_card, 1)

        mode_card, mode_layout = self._make_selector_card(_("Режим интерфейса", "UI mode"))
        self.gui.chat_mode_combobox = QComboBox()
        self.gui.chat_mode_combobox.setObjectName("ChatCharacterCombo")
        self.gui.chat_mode_combobox.setToolTip(_("Режим интерфейса (объём настроек)", "UI mode (settings depth)"))
        self.gui.chat_mode_combobox.addItems(
            [
                _("Базовый", "Basic"),
                _("Продвинутый", "Advanced"),
                _("Полный", "Full"),
            ]
        )
        self.gui.chat_mode_combobox.currentTextChanged.connect(self._on_chat_mode_changed)
        mode_layout.addWidget(self.gui.chat_mode_combobox)
        selectors.addWidget(mode_card, 1)

        hero_layout.addLayout(selectors)
        return hero_card

    def _build_inspector_params_tab(self) -> QWidget:
        page, layout = self._make_tab_page()

        status_card, status_layout = self._make_inspector_card(_("Подключения", "Connections"))
        create_status_indicators(self.gui, status_layout)
        layout.addWidget(status_card)

        quick_card, quick_layout = self._make_inspector_card(_("Быстрые действия", "Quick actions"))
        self.gui.clear_chat_button = QPushButton(_("Очистить чат", "Clear chat"))
        self.gui.clear_chat_button.setObjectName("SandboxQuickAction")
        self.gui.clear_chat_button.clicked.connect(self.gui.clear_chat_display)
        quick_layout.addWidget(self.gui.clear_chat_button)

        self.gui.load_history_button = QPushButton(_("Загрузить историю", "Load history"))
        self.gui.load_history_button.setObjectName("SandboxQuickAction")
        self.gui.load_history_button.clicked.connect(self.gui.load_chat_history)
        quick_layout.addWidget(self.gui.load_history_button)

        api_button = QPushButton(_("Полные настройки API", "Full API settings"))
        api_button.setObjectName("SandboxQuickAction")
        api_button.clicked.connect(lambda: self._jump_to_settings("api"))
        quick_layout.addWidget(api_button)
        layout.addWidget(quick_card)

        layout.addStretch(1)
        return page

    def _build_inspector_memory_tab(self) -> QWidget:
        page, layout = self._make_tab_page()

        profile_card, profile_layout = self._make_inspector_card(_("Профиль памяти", "Memory profile"))
        self.gui.sandbox_memory_profile_combo = QComboBox()
        self.gui.sandbox_memory_profile_combo.setObjectName("ChatCharacterCombo")
        self.gui.sandbox_memory_profile_combo.addItems(
            [
                _("Оптимизированный", "Optimized"),
                _("Сбалансированный", "Balanced"),
                _("Большой", "Large"),
                _("Своё", "Custom"),
            ]
        )
        self.gui.sandbox_memory_profile_combo.currentTextChanged.connect(self._on_memory_profile_changed)
        profile_layout.addWidget(self.gui.sandbox_memory_profile_combo)
        layout.addWidget(profile_card)

        counts_card, counts_layout = self._make_inspector_card(_("Лимиты памяти", "Memory limits"))
        for label_text, key, fallback in (
            (_("Сообщений в окне", "Messages in window"), "MODEL_MESSAGE_LIMIT", 35),
            (_("Долгосрочная память", "Long-term memory"), "MEMORY_CAPACITY", 50),
            (_("Результатов RAG", "RAG results"), "RAG_MAX_RESULTS", 50),
        ):
            row = QHBoxLayout()
            row.setSpacing(8)
            label = QLabel(label_text)
            label.setObjectName("SandboxInspectorLabel")
            row.addWidget(label)
            row.addStretch()
            value = QLabel(str(self.gui._get_setting(key, fallback)))
            value.setObjectName("SandboxInspectorValue")
            row.addWidget(value)
            counts_layout.addLayout(row)
            self._memory_limit_values[key] = value

        full_btn = QPushButton(_("Открыть RAG / память", "Open RAG / memory"))
        full_btn.setObjectName("SandboxQuickAction")
        full_btn.clicked.connect(lambda: self._jump_to_settings("models"))
        counts_layout.addWidget(full_btn)
        layout.addWidget(counts_card)

        layout.addStretch(1)
        return page

    def _build_inspector_debug_tab(self) -> QWidget:
        page, layout = self._make_tab_page()

        summary_card, summary_layout = self._make_inspector_card(_("Контекст сессии", "Session context"))
        summary_lines = [
            ("voice", _("Голос", "Voice"), str(self.gui._get_setting("VOICEOVER_METHOD", "TG"))),
            (
                "screen",
                _("Экран", "Screen"),
                _("Включён", "Enabled") if self.gui._get_setting("ENABLE_SCREEN_ANALYSIS", False) else _("Выключен", "Disabled"),
            ),
            (
                "camera",
                _("Камера", "Camera"),
                _("Включена", "Enabled") if self.gui._get_setting("ENABLE_CAMERA_CAPTURE", False) else _("Выключена", "Disabled"),
            ),
            ("mode", _("Режим", "Mode"), get_mode_label(self.gui._get_setting("INTERFACE_MODE", _("Базовый", "Basic")))),
        ]
        for key, label_text, value_text in summary_lines:
            row = QHBoxLayout()
            row.setSpacing(8)
            label = QLabel(label_text)
            label.setObjectName("SandboxInspectorLabel")
            row.addWidget(label)
            row.addStretch()
            value = QLabel(value_text)
            value.setObjectName("SandboxInspectorValue")
            row.addWidget(value)
            summary_layout.addLayout(row)
            self._debug_summary_values[key] = value
        layout.addWidget(summary_card)

        actions_card, actions_layout = self._make_inspector_card(_("Диагностика", "Diagnostics"))
        db_btn = QPushButton(_("Открыть DB персонажа", "Open character DB"))
        db_btn.setObjectName("SandboxQuickAction")
        db_btn.clicked.connect(self._open_selected_character_history)
        actions_layout.addWidget(db_btn)

        debug_btn = QPushButton(_("Debug настройки", "Debug settings"))
        debug_btn.setObjectName("SandboxQuickAction")
        debug_btn.clicked.connect(lambda: self._jump_to_settings("debug"))
        actions_layout.addWidget(debug_btn)

        logs_btn = QPushButton(_("Открыть страницу логов", "Open logs page"))
        logs_btn.setObjectName("SandboxQuickAction")
        logs_btn.clicked.connect(lambda: self.gui.switch_main_page("logs"))
        actions_layout.addWidget(logs_btn)
        layout.addWidget(actions_card)

        layout.addStretch(1)
        return page

    def _build_inspector(self) -> QWidget:
        inspector = QWidget()
        inspector.setObjectName("SandboxInspector")
        inspector.setFixedWidth(320)

        layout = QVBoxLayout(inspector)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        tabs = QTabWidget()
        tabs.setObjectName("SandboxInspectorTabs")
        tabs.setDocumentMode(True)
        tabs.addTab(self._build_inspector_params_tab(), _("Параметры", "Params"))
        tabs.addTab(self._build_inspector_memory_tab(), _("Память", "Memory"))
        tabs.addTab(self._build_inspector_debug_tab(), _("Отладка", "Debug"))
        layout.addWidget(tabs, 1)
        self.gui.sandbox_inspector_tabs = tabs
        return inspector

    def _build_ui(self):
        page_layout = QVBoxLayout(self)
        page_layout.setContentsMargins(18, 18, 18, 18)
        page_layout.setSpacing(12)
        page_layout.addWidget(self._build_header())

        content_row = QHBoxLayout()
        content_row.setSpacing(12)

        self._chat_panel = ChatPanel(self.gui)
        content_row.addWidget(self._chat_panel, 1)
        content_row.addWidget(self._build_inspector())
        page_layout.addLayout(content_row, 1)


def build_sandbox_page(window) -> QWidget:
    return SandboxPage(window)
