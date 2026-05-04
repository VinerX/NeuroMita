import base64

from PyQt6.QtCore import QBuffer, QIODevice, QPoint, QPropertyAnimation, QTimer, Qt
from PyQt6.QtGui import QFont, QPixmap
from PyQt6.QtWidgets import (
    QFileDialog,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QComboBox,
    QSizePolicy,
    QTabWidget,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

import qtawesome as qta

from core.events import Events
from main_logger import logger
from styles.main_styles import get_stylesheet
from ui.chat.chat_widget import ChatWidget
from ui.widgets.image_preview_widget import ImagePreviewBar
from ui.widgets.image_viewer_widget import ImageViewerWidget
from ui.widgets.mita_status_widget import MitaStatusWidget
from ui.widgets.status_indicators_widget import create_status_indicators
from utils import _

TOP_ICON_BUTTON_SIZE = 30


_MODEL_CONFIGURE_SENTINEL = "__configure_models__"
_TTS_CONFIGURE_SENTINEL = "__configure_tts__"
_ASR_CONFIGURE_SENTINEL = "__configure_asr__"


def _populate_model_combobox(gui):
    combo = getattr(gui, "chat_model_combobox", None)
    if combo is None:
        return
    try:
        result = gui.event_bus.emit_and_wait(Events.ApiPresets.GET_PRESET_LIST, timeout=1.0)
        meta = result[0] if result else {}
    except Exception:
        meta = {}

    customs = list((meta or {}).get("custom", []))

    combo.blockSignals(True)
    try:
        combo.clear()

        # Показываем только настроенные (custom) пресеты — голые шаблоны
        # без api-ключей в саб-меню не нужны. Создание/настройка — через
        # пункт «Настроить…», который уводит в API-страницу.
        if customs:
            for preset in customs:
                pid = getattr(preset, "id", None)
                name = getattr(preset, "name", "")
                if pid is None:
                    continue
                combo.addItem(str(name), int(pid))
            combo.insertSeparator(combo.count())
        else:
            combo.addItem(_("Нет настроенных моделей", "No configured models"), None)
            combo.insertSeparator(combo.count())

        combo.addItem(_("Настроить…", "Configure…"), _MODEL_CONFIGURE_SENTINEL)

        try:
            current_res = gui.event_bus.emit_and_wait(Events.ApiPresets.GET_CURRENT_PRESET_ID, timeout=0.5)
            current_id = current_res[0] if current_res else None
        except Exception:
            current_id = None

        if current_id is not None:
            for i in range(combo.count()):
                if combo.itemData(i) == int(current_id):
                    combo.setCurrentIndex(i)
                    break
    finally:
        combo.blockSignals(False)


def _on_chat_model_changed(gui, index: int):
    combo = getattr(gui, "chat_model_combobox", None)
    if combo is None or index < 0:
        return
    data = combo.itemData(index)
    if data == _MODEL_CONFIGURE_SENTINEL:
        # Возвращаем выделение к актуальному пресету и открываем API-настройки.
        QTimer.singleShot(0, lambda: _populate_model_combobox(gui))
        _jump_to_settings(gui, "api")
        return
    if data is None:
        return
    try:
        gui.event_bus.emit(Events.ApiPresets.SET_CURRENT_PRESET_ID, {"id": int(data)})
    except Exception as exc:
        logger.error(f"Failed to switch preset: {exc}")


def _populate_tts_combobox(gui):
    combo = getattr(gui, "chat_tts_combobox", None)
    if combo is None:
        return

    # Список установленных локальных голосов.
    installed_local: set[str] = set()
    try:
        from core.events import Events as _Events
        res = gui.event_bus.emit_and_wait(_Events.VoiceModel.GET_INSTALLED_MODELS, timeout=0.5)
        got = res[0] if res else None
        if isinstance(got, (set, list, tuple)):
            installed_local = set(str(x) for x in got)
    except Exception:
        installed_local = set()

    try:
        from ui.settings.voiceover_settings import LOCAL_VOICE_MODELS
    except Exception:
        LOCAL_VOICE_MODELS = []

    method = str(gui._get_setting("VOICEOVER_METHOD", "TG") or "TG")
    selected_local_id = str(gui._get_setting("LOCAL_VOICE_MODEL_ID", "") or "")

    combo.blockSignals(True)
    try:
        combo.clear()
        # data = ("TG", None) для Telegram, ("Local", model_id) для локалок.
        combo.addItem("Telegram (TG)", ("TG", None))

        for model in LOCAL_VOICE_MODELS:
            mid = str(model.get("id") or "")
            name = str(model.get("name") or mid)
            if mid in installed_local:
                combo.addItem(name, ("Local", mid))

        combo.insertSeparator(combo.count())
        combo.addItem(_("Настроить…", "Configure…"), (_TTS_CONFIGURE_SENTINEL, None))

        active_index = 0
        for i in range(combo.count()):
            data = combo.itemData(i)
            if not isinstance(data, tuple):
                continue
            kind, mid = data
            if method == "TG" and kind == "TG":
                active_index = i
                break
            if method == "Local" and kind == "Local" and mid == selected_local_id:
                active_index = i
                break
        combo.setCurrentIndex(active_index)
    finally:
        combo.blockSignals(False)


def _on_chat_voice_changed(gui, index: int):
    combo = getattr(gui, "chat_tts_combobox", None)
    if combo is None or index < 0:
        return
    data = combo.itemData(index)
    if not isinstance(data, tuple):
        return
    kind, mid = data
    if kind == _TTS_CONFIGURE_SENTINEL:
        QTimer.singleShot(0, lambda: _populate_tts_combobox(gui))
        _jump_to_settings(gui, "voice")
        return
    try:
        gui.settings.set("VOICEOVER_METHOD", kind)
        if kind == "Local" and mid:
            gui.settings.set("LOCAL_VOICE_MODEL_ID", mid)
            try:
                gui.event_bus.emit(Events.GUI.VOICEOVER_MODEL_SELECTED, {"model_id": mid})
            except Exception:
                pass
    except Exception:
        try:
            gui.settings["VOICEOVER_METHOD"] = kind
        except Exception:
            pass


def _populate_asr_combobox(gui):
    combo = getattr(gui, "chat_asr_combobox", None)
    if combo is None:
        return

    combo.blockSignals(True)
    combo.clear()
    combo.addItem(_("Загрузка…", "Loading…"), None)
    combo.setEnabled(False)
    combo.blockSignals(False)

    def _apply(items):
        if combo is None:
            return
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
            current = str(gui._get_setting("RECOGNIZER_TYPE", "") or "")
            for i in range(combo.count()):
                if combo.itemData(i) == current:
                    combo.setCurrentIndex(i)
                    break
        finally:
            combo.blockSignals(False)

    def cb(result, error=None):
        QTimer.singleShot(0, lambda r=result: _apply(r if isinstance(r, list) else []))

    try:
        gui.event_bus.emit(Events.Speech.GET_ASR_MODELS_GLOSSARY, {"callback": cb})
    except Exception:
        _apply([])


def _on_chat_asr_changed(gui, index: int):
    combo = getattr(gui, "chat_asr_combobox", None)
    if combo is None or index < 0:
        return
    data = combo.itemData(index)
    if data == _ASR_CONFIGURE_SENTINEL:
        QTimer.singleShot(0, lambda: _populate_asr_combobox(gui))
        _jump_to_settings(gui, "microphone")
        return
    if not data:
        return
    try:
        gui.settings.set("RECOGNIZER_TYPE", str(data))
    except Exception:
        try:
            gui.settings["RECOGNIZER_TYPE"] = str(data)
        except Exception:
            pass


def _on_chat_mode_changed(gui, value: str):
    value = (value or "").strip()
    if not value:
        return
    try:
        gui.settings.set("INTERFACE_MODE", value)
    except Exception:
        try:
            gui.settings["INTERFACE_MODE"] = value
        except Exception:
            pass
    try:
        from ui.widgets.settings_panel import apply_interface_mode
        apply_interface_mode(gui, value)
    except Exception as exc:
        logger.info(f"apply_interface_mode failed: {exc}")


def _populate_chat_character_combobox(gui):
    combo = getattr(gui, "chat_character_combobox", None)
    if combo is None:
        return

    all_characters = gui.event_bus.emit_and_wait(Events.Character.GET_ALL, timeout=1.0)
    character_list = all_characters[0] if all_characters else ["Crazy"]
    if not character_list:
        character_list = ["Crazy"]

    current_profile_res = gui.event_bus.emit_and_wait(Events.Character.GET_CURRENT_PROFILE, timeout=1.0)
    current_profile = current_profile_res[0] if current_profile_res else {}
    current_char_id = current_profile.get("character_id", character_list[0]) if isinstance(current_profile, dict) else character_list[0]

    combo.blockSignals(True)
    try:
        combo.clear()
        combo.addItems(character_list)
        idx = combo.findText(str(current_char_id), Qt.MatchFlag.MatchFixedString)
        if idx >= 0:
            combo.setCurrentIndex(idx)
    finally:
        combo.blockSignals(False)


def _on_chat_character_changed(gui, character_id):
    character_id = str(character_id or "").strip()
    if not character_id:
        return

    settings_combo = getattr(gui, "character_combobox", None)
    if settings_combo is not None and settings_combo.currentText() != character_id:
        idx = settings_combo.findText(character_id, Qt.MatchFlag.MatchFixedString)
        if idx >= 0:
            settings_combo.setCurrentIndex(idx)
            return

    gui.event_bus.emit(Events.Character.SET_CURRENT, {"character_id": character_id})
    gui.event_bus.emit(Events.Character.RELOAD_DATA)


def _open_selected_character_history(gui):
    combo = getattr(gui, "chat_character_combobox", None)
    character_id = combo.currentText().strip() if combo is not None else ""
    if character_id:
        gui.event_bus.emit(Events.Character.SET_CURRENT, {"character_id": character_id})

    try:
        from ui.settings.character_settings.logic import open_db_viewer

        open_db_viewer(gui)
    except Exception as e:
        logger.error(f"Failed to open character history: {e}", exc_info=True)


def _jump_to_settings(gui, category: str):
    gui.switch_main_page("settings")
    gui.show_settings_category(category)


def _make_selector_card(title: str) -> tuple[QFrame, QVBoxLayout]:
    card = QFrame()
    card.setObjectName("SandboxSelectorCard")
    layout = QVBoxLayout(card)
    layout.setContentsMargins(14, 12, 14, 12)
    layout.setSpacing(6)

    label = QLabel(title)
    label.setObjectName("SandboxSelectorLabel")
    layout.addWidget(label)
    return card, layout


def _build_chat_header(gui) -> QFrame:
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
    guide_button.clicked.connect(gui._show_guide)
    title_row.addWidget(guide_button, 0, Qt.AlignmentFlag.AlignTop)
    hero_layout.addLayout(title_row)

    selectors = QHBoxLayout()
    selectors.setSpacing(10)

    character_card, character_layout = _make_selector_card(_("Персонаж", "Character"))
    gui.chat_character_combobox = QComboBox()
    gui.chat_character_combobox.setObjectName("ChatCharacterCombo")
    gui.chat_character_combobox.setToolTip(_("Выбрать персонажа", "Select character"))
    gui.chat_character_combobox.currentTextChanged.connect(lambda text: _on_chat_character_changed(gui, text))
    character_layout.addWidget(gui.chat_character_combobox)
    _populate_chat_character_combobox(gui)
    selectors.addWidget(character_card, 2)

    model_card, model_layout = _make_selector_card(_("Модель", "Model"))
    gui.chat_model_combobox = QComboBox()
    gui.chat_model_combobox.setObjectName("ChatCharacterCombo")
    gui.chat_model_combobox.setToolTip(_("Активный API-пресет (модель)", "Active API preset (model)"))
    gui.chat_model_combobox.currentIndexChanged.connect(lambda idx: _on_chat_model_changed(gui, idx))
    model_layout.addWidget(gui.chat_model_combobox)
    _populate_model_combobox(gui)
    selectors.addWidget(model_card, 2)

    tts_card, tts_layout = _make_selector_card(_("TTS", "TTS"))
    gui.chat_tts_combobox = QComboBox()
    gui.chat_tts_combobox.setObjectName("ChatCharacterCombo")
    gui.chat_tts_combobox.setToolTip(_("Способ озвучки: TG или установленные локальные модели", "Voice output: TG or installed local models"))
    gui.chat_tts_combobox.currentIndexChanged.connect(lambda idx: _on_chat_voice_changed(gui, idx))
    _populate_tts_combobox(gui)
    tts_layout.addWidget(gui.chat_tts_combobox)
    selectors.addWidget(tts_card, 1)

    asr_card, asr_layout = _make_selector_card(_("ASR", "ASR"))
    gui.chat_asr_combobox = QComboBox()
    gui.chat_asr_combobox.setObjectName("ChatCharacterCombo")
    gui.chat_asr_combobox.setToolTip(_("Установленные модели распознавания речи", "Installed speech recognition models"))
    gui.chat_asr_combobox.currentIndexChanged.connect(lambda idx: _on_chat_asr_changed(gui, idx))
    _populate_asr_combobox(gui)
    asr_layout.addWidget(gui.chat_asr_combobox)
    selectors.addWidget(asr_card, 1)

    mode_card, mode_layout = _make_selector_card(_("Режим интерфейса", "UI mode"))
    gui.chat_mode_combobox = QComboBox()
    gui.chat_mode_combobox.setObjectName("ChatCharacterCombo")
    gui.chat_mode_combobox.setToolTip(_("Режим интерфейса (объём настроек)", "UI mode (settings depth)"))
    mode_options = [_("Базовый", "Basic"), _("Продвинутый", "Advanced"), _("Полный", "Full")]
    gui.chat_mode_combobox.addItems(mode_options)
    current_mode = str(gui._get_setting("INTERFACE_MODE", mode_options[0]) or mode_options[0])
    idx = gui.chat_mode_combobox.findText(current_mode, Qt.MatchFlag.MatchFixedString)
    if idx >= 0:
        gui.chat_mode_combobox.setCurrentIndex(idx)
    gui.chat_mode_combobox.currentTextChanged.connect(lambda v: _on_chat_mode_changed(gui, v))
    mode_layout.addWidget(gui.chat_mode_combobox)
    selectors.addWidget(mode_card, 1)

    hero_layout.addLayout(selectors)
    return hero_card


def _build_chat_inspector(gui) -> QWidget:
    inspector = QWidget()
    inspector.setObjectName("SandboxInspector")
    inspector.setFixedWidth(320)
    layout = QVBoxLayout(inspector)
    layout.setContentsMargins(0, 0, 0, 0)
    layout.setSpacing(0)

    tabs = QTabWidget()
    tabs.setObjectName("SandboxInspectorTabs")
    tabs.setDocumentMode(True)
    tabs.addTab(_build_inspector_params_tab(gui), _("Параметры", "Params"))
    tabs.addTab(_build_inspector_memory_tab(gui), _("Память", "Memory"))
    tabs.addTab(_build_inspector_debug_tab(gui), _("Отладка", "Debug"))
    layout.addWidget(tabs, 1)
    gui.sandbox_inspector_tabs = tabs
    return inspector


def _make_tab_page() -> tuple[QWidget, QVBoxLayout]:
    page = QWidget()
    page.setObjectName("SandboxInspectorTabPage")
    layout = QVBoxLayout(page)
    layout.setContentsMargins(2, 12, 2, 4)
    layout.setSpacing(12)
    return page, layout


def _make_inspector_card(title_text: str | None = None) -> tuple[QFrame, QVBoxLayout]:
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


def _build_inspector_params_tab(gui) -> QWidget:
    page, layout = _make_tab_page()

    status_card, status_layout = _make_inspector_card(_("Подключения", "Connections"))
    create_status_indicators(gui, status_layout)
    layout.addWidget(status_card)

    quick_card, quick_layout = _make_inspector_card(_("Быстрые действия", "Quick actions"))
    gui.clear_chat_button = QPushButton(_("Очистить чат", "Clear chat"))
    gui.clear_chat_button.setObjectName("SandboxQuickAction")
    gui.clear_chat_button.clicked.connect(gui.clear_chat_display)
    quick_layout.addWidget(gui.clear_chat_button)

    gui.load_history_button = QPushButton(_("Загрузить историю", "Load history"))
    gui.load_history_button.setObjectName("SandboxQuickAction")
    gui.load_history_button.clicked.connect(gui.load_chat_history)
    quick_layout.addWidget(gui.load_history_button)

    api_button = QPushButton(_("Полные настройки API", "Full API settings"))
    api_button.setObjectName("SandboxQuickAction")
    api_button.clicked.connect(lambda: _jump_to_settings(gui, "api"))
    quick_layout.addWidget(api_button)
    layout.addWidget(quick_card)

    layout.addStretch(1)
    return page


def _build_inspector_memory_tab(gui) -> QWidget:
    page, layout = _make_tab_page()

    profile_card, profile_layout = _make_inspector_card(_("Профиль памяти", "Memory profile"))
    profile_combo = QComboBox()
    profile_combo.setObjectName("ChatCharacterCombo")
    profile_options = [
        _("Оптимизированный", "Optimized"),
        _("Сбалансированный", "Balanced"),
        _("Большой", "Large"),
        _("Своё", "Custom"),
    ]
    profile_combo.addItems(profile_options)

    try:
        from ui.settings.memory_profile import (
            detect_memory_profile,
            apply_memory_profile,
            KEY_TO_LABEL_RU,
            KEY_TO_LABEL_EN,
        )
        lang = str(gui._get_setting("LANGUAGE", "RU") or "RU")
        key_to_label = KEY_TO_LABEL_EN if lang == "EN" else KEY_TO_LABEL_RU
        current_label = key_to_label.get(detect_memory_profile(gui), profile_options[1])
    except Exception:
        apply_memory_profile = None
        current_label = profile_options[1]

    idx = profile_combo.findText(current_label, Qt.MatchFlag.MatchFixedString)
    if idx >= 0:
        profile_combo.setCurrentIndex(idx)

    def _on_profile_changed(label: str):
        if apply_memory_profile is not None:
            apply_memory_profile(gui, label)
        try:
            gui.settings.set("MEMORY_PROFILE", label)
        except Exception:
            try:
                gui.settings["MEMORY_PROFILE"] = label
            except Exception:
                pass

    profile_combo.currentTextChanged.connect(_on_profile_changed)
    profile_layout.addWidget(profile_combo)
    gui.sandbox_memory_profile_combo = profile_combo
    layout.addWidget(profile_card)

    counts_card, counts_layout = _make_inspector_card(_("Лимиты памяти", "Memory limits"))
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
        value = QLabel(str(gui._get_setting(key, fallback)))
        value.setObjectName("SandboxInspectorValue")
        row.addWidget(value)
        counts_layout.addLayout(row)

    full_btn = QPushButton(_("Открыть RAG / память", "Open RAG / memory"))
    full_btn.setObjectName("SandboxQuickAction")
    full_btn.clicked.connect(lambda: _jump_to_settings(gui, "models"))
    counts_layout.addWidget(full_btn)
    layout.addWidget(counts_card)

    layout.addStretch(1)
    return page


def _build_inspector_debug_tab(gui) -> QWidget:
    page, layout = _make_tab_page()

    summary_card, summary_layout = _make_inspector_card(_("Контекст сессии", "Session context"))
    summary_lines = [
        (_("Голос", "Voice"), str(gui._get_setting("VOICEOVER_METHOD", "TG"))),
        (_("Экран", "Screen"), _("Включён", "Enabled") if gui._get_setting("ENABLE_SCREEN_ANALYSIS", False) else _("Выключен", "Disabled")),
        (_("Камера", "Camera"), _("Включена", "Enabled") if gui._get_setting("ENABLE_CAMERA_CAPTURE", False) else _("Выключена", "Disabled")),
        (_("Режим", "Mode"), str(gui._get_setting("INTERFACE_MODE", _("Базовый", "Basic")))),
    ]
    for label_text, value_text in summary_lines:
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
    layout.addWidget(summary_card)

    actions_card, actions_layout = _make_inspector_card(_("Диагностика", "Diagnostics"))
    db_btn = QPushButton(_("Открыть DB персонажа", "Open character DB"))
    db_btn.setObjectName("SandboxQuickAction")
    db_btn.clicked.connect(lambda: _open_selected_character_history(gui))
    actions_layout.addWidget(db_btn)

    debug_btn = QPushButton(_("Debug настройки", "Debug settings"))
    debug_btn.setObjectName("SandboxQuickAction")
    debug_btn.clicked.connect(lambda: _jump_to_settings(gui, "debug"))
    actions_layout.addWidget(debug_btn)

    logs_btn = QPushButton(_("Открыть страницу логов", "Open logs page"))
    logs_btn.setObjectName("SandboxQuickAction")
    logs_btn.clicked.connect(lambda: gui.switch_main_page("logs"))
    actions_layout.addWidget(logs_btn)
    layout.addWidget(actions_card)

    layout.addStretch(1)
    return page


def _build_chat_conversation_strip(gui) -> QFrame:
    """Тонкая полоса между шапкой и сообщениями: «Разговор с …», заглушки
    статуса памяти/настроения и быстрые действия. Память/настроение пока
    декоративные — туда позже подключатся реальные данные из RAG/character.
    """
    strip = QFrame()
    strip.setObjectName("ChatConversationStrip")
    layout = QHBoxLayout(strip)
    layout.setContentsMargins(14, 8, 14, 8)
    layout.setSpacing(14)

    heart = QLabel()
    heart.setPixmap(qta.icon("fa6s.heart", color="#ff7eb6").pixmap(14, 14))
    layout.addWidget(heart, 0, Qt.AlignmentFlag.AlignVCenter)

    char_id = ""
    try:
        res = gui.event_bus.emit_and_wait(__import__("core.events", fromlist=["Events"]).Events.Character.GET_CURRENT_PROFILE, timeout=0.3)
        profile = res[0] if res else {}
        char_id = str((profile or {}).get("character_id") or "")
    except Exception:
        char_id = ""
    char_label_text = _("Разговор с ", "Conversation with ") + (char_id or _("персонажем", "character"))
    char_label = QLabel(char_label_text)
    char_label.setObjectName("ChatStripTitle")
    layout.addWidget(char_label, 0, Qt.AlignmentFlag.AlignVCenter)
    gui.chat_strip_title = char_label

    # «Память активна» / «Настроение» убраны как декоративные заглушки —
    # вернём, когда подключим реальные данные RAG/character.

    layout.addStretch(1)

    clear_button = QPushButton(_("Очистить чат", "Clear chat"))
    clear_button.setObjectName("ChatStripGhostButton")
    clear_button.setIcon(qta.icon("fa6s.trash", color="#ffd2ec"))
    clear_button.setCursor(Qt.CursorShape.PointingHandCursor)
    clear_button.clicked.connect(gui.clear_chat_display)
    layout.addWidget(clear_button, 0, Qt.AlignmentFlag.AlignVCenter)

    return strip


def setup_chat_panel(gui, main_layout):
    from ui.pages.sandbox.sandbox_page_widget import SandboxPage

    page = SandboxPage(gui)
    gui.sandbox_page = page
    main_layout.addWidget(page, 1)
    return page

    page_root = QWidget()
    page_root.setObjectName("SandboxPage")

    page_layout = QVBoxLayout(page_root)
    page_layout.setContentsMargins(18, 18, 18, 18)
    page_layout.setSpacing(12)
    page_layout.addWidget(_build_chat_header(gui))

    content_row = QHBoxLayout()
    content_row.setSpacing(12)

    chat_column = QWidget()
    chat_column.setObjectName("ChatWorkspace")
    chat_layout = QVBoxLayout(chat_column)
    chat_layout.setContentsMargins(0, 0, 0, 0)
    chat_layout.setSpacing(12)

    chat_layout.addWidget(_build_chat_conversation_strip(gui))

    gui.chat_window = ChatWidget()
    gui.chat_window.setObjectName("ChatScrollArea")
    initial_font_size = int(gui._get_setting("CHAT_FONT_SIZE", 12))
    gui._chat_font_size = initial_font_size
    chat_layout.addWidget(gui.chat_window, 1)

    gui.scroll_to_bottom_btn = gui.chat_window._scroll_btn
    gui.scroll_to_bottom_anim = gui.chat_window._scroll_btn._opacity_anim
    gui.mita_status = MitaStatusWidget(gui.chat_window)

    input_frame = QFrame()
    input_frame.setObjectName("ChatComposerCard")
    input_frame.setStyleSheet(get_stylesheet())
    input_layout = QVBoxLayout(input_frame)
    input_layout.setContentsMargins(18, 16, 18, 16)
    input_layout.setSpacing(8)

    gui.token_count_label = QLabel(_("Токены: 0/0 | Стоимость: 0.00 ₽", "Tokens: 0/0 | Cost: 0.00 ₽"))
    gui.token_count_label.setObjectName("TokenCountLabel")
    input_layout.addWidget(gui.token_count_label)

    input_container = QWidget()
    input_container.setObjectName("ChatInputContainer")
    container_layout = QGridLayout(input_container)
    container_layout.setContentsMargins(5, 5, 5, 5)
    container_layout.setSpacing(5)

    gui.user_entry = QTextEdit()
    gui.user_entry.setMinimumHeight(24)
    gui.user_entry.setMaximumHeight(80)
    gui.user_entry.setFixedHeight(36)
    gui.user_entry.setPlaceholderText(_("Напиши что-нибудь Mita…", "Write something to Mita…"))
    gui.user_entry.setStyleSheet(
        """
        QTextEdit {
            background-color: transparent;
            border: none;
            color: #f7edf5;
            padding: 4px 2px;
        }
        QTextEdit:focus {
            background-color: transparent;
            border: none;
        }
        """
    )
    gui.user_entry.textChanged.connect(lambda: adjust_input_height(gui))
    gui.user_entry.textChanged.connect(lambda: update_send_button_state(gui))
    gui.user_entry.installEventFilter(gui)
    container_layout.addWidget(gui.user_entry, 0, 0, 1, 2)

    button_container = QWidget()
    button_container.setFixedHeight(24)
    button_container.setStyleSheet("background-color: transparent; border: none;")
    button_layout_inner = QHBoxLayout(button_container)
    button_layout_inner.setContentsMargins(0, 0, 0, 0)
    button_layout_inner.setSpacing(4)

    gui.attach_button = QPushButton(qta.icon("fa6s.paperclip", color="#b0b0b0", scale_factor=0.7), "")
    gui.attach_button.setObjectName("ChatIconMini")
    gui.attach_button.clicked.connect(lambda: attach_images(gui))
    gui.attach_button.setFixedSize(20, 20)
    gui.attach_button.setCursor(Qt.CursorShape.PointingHandCursor)
    gui.attach_button.setToolTip(_("Прикрепить изображения", "Attach images"))

    gui.send_screen_button = QPushButton(qta.icon("fa6s.camera", color="#b0b0b0", scale_factor=0.7), "")
    gui.send_screen_button.setObjectName("ChatIconMini")
    gui.send_screen_button.clicked.connect(lambda: send_screen_capture(gui))
    gui.send_screen_button.setFixedSize(20, 20)
    gui.send_screen_button.setCursor(Qt.CursorShape.PointingHandCursor)
    gui.send_screen_button.setToolTip(_("Сделать скриншот экрана", "Take screenshot"))

    button_layout_inner.addWidget(gui.attach_button)
    button_layout_inner.addWidget(gui.send_screen_button)
    button_layout_inner.addStretch()
    container_layout.addWidget(button_container, 1, 0)

    gui.send_button = QPushButton(qta.icon("fa6s.paper-plane", color="white", scale_factor=0.8), "")
    gui.send_button.setObjectName("ChatSendButtonCircle")
    gui.send_button.clicked.connect(gui.send_message)
    gui.send_button.setFixedSize(28, 28)
    gui.send_button.setCursor(Qt.CursorShape.PointingHandCursor)
    gui.send_button.setToolTip(_("Отправить сообщение", "Send message"))

    send_container = QWidget()
    send_container.setStyleSheet("background-color: transparent; border: none;")
    send_layout = QHBoxLayout(send_container)
    send_layout.setContentsMargins(0, 0, 0, 0)
    send_layout.addStretch()
    send_layout.addWidget(gui.send_button)
    container_layout.addWidget(send_container, 1, 1)

    input_layout.addWidget(input_container)
    gui.attachment_label = QLabel("")
    gui.attachment_label.setVisible(False)
    gui.clear_attach_btn = QPushButton("")
    gui.clear_attach_btn.setVisible(False)

    chat_layout.addWidget(input_frame)
    update_send_button_state(gui)

    content_row.addWidget(chat_column, 1)
    content_row.addWidget(_build_chat_inspector(gui))
    page_layout.addLayout(content_row, 1)
    main_layout.addWidget(page_root, 1)


def create_scroll_to_bottom_button(gui):
    pass


def handle_chat_scroll(gui):
    pass


def fade_in_scroll_button(gui):
    pass


def fade_out_scroll_button(gui):
    pass


def reposition_scroll_button(gui):
    if hasattr(gui, "chat_window") and hasattr(gui.chat_window, "_reposition_scroll_button"):
        gui.chat_window._reposition_scroll_button()


def adjust_input_height(gui):
    doc = gui.user_entry.document()
    doc_height = doc.size().height()
    new_height = int(doc_height + 10)
    new_height = max(36, min(new_height, 80))
    gui.user_entry.setFixedHeight(new_height)


def update_send_button_state(gui):
    has_text = bool(gui.user_entry.toPlainText().strip())
    has_images = bool(getattr(gui, "staged_image_data", []))

    has_auto_images = False
    if gui._get_setting("ENABLE_SCREEN_ANALYSIS", False):
        frames = gui.event_bus.emit_and_wait(Events.Capture.CAPTURE_SCREEN, {"limit": 1}, timeout=0.5)
        has_auto_images = bool(frames and frames[0])

    if gui._get_setting("ENABLE_CAMERA_CAPTURE", False):
        camera_frames = gui.event_bus.emit_and_wait(Events.Capture.GET_CAMERA_FRAMES, {"limit": 1}, timeout=0.5)
        has_auto_images = has_auto_images or bool(camera_frames and camera_frames[0])

    is_enabled = has_text or has_images or has_auto_images
    gui.send_button.setEnabled(is_enabled)


def init_image_preview(gui):
    gui.staged_image_data = []


def show_image_preview_bar(gui):
    if not getattr(gui, "image_preview_bar", None):
        input_frame = None
        widget = gui.user_entry
        while widget:
            if isinstance(widget, QFrame) and widget.objectName() != "":
                break
            if hasattr(widget, "layout") and widget.layout():
                for i in range(widget.layout().count()):
                    item = widget.layout().itemAt(i)
                    if item and item.widget() == gui.token_count_label:
                        input_frame = widget
                        break
            if input_frame:
                break
            widget = widget.parent()
        if not input_frame:
            input_frame = gui.token_count_label.parent()
        if input_frame:
            gui.image_preview_bar = ImagePreviewBar(input_frame)
            gui.image_preview_bar.thumbnail_clicked.connect(lambda img: show_full_image(gui, img))
            gui.image_preview_bar.remove_requested.connect(lambda idx: remove_staged_image(gui, idx))
            input_frame.layout().insertWidget(1, gui.image_preview_bar)
    gui.image_preview_bar.show()


def remove_staged_image(gui, index):
    if 0 <= index < len(gui.staged_image_data):
        gui.staged_image_data.pop(index)
        gui.image_preview_bar.remove_at(index)
        if len(gui.staged_image_data) == 0:
            hide_image_preview_bar(gui)
        update_send_button_state(gui)


def hide_image_preview_bar(gui):
    if getattr(gui, "image_preview_bar", None):
        gui.image_preview_bar.hide()


def show_full_image(gui, image_data):
    try:
        if isinstance(image_data, str) and image_data.startswith("data:image"):
            base64_data = image_data.split(",")[1]
            img_bytes = base64.b64decode(base64_data)
        elif isinstance(image_data, bytes):
            img_bytes = image_data
        else:
            return
        pixmap = QPixmap()
        pixmap.loadFromData(img_bytes)
        viewer = ImageViewerWidget(pixmap)
        viewer.close_requested.connect(gui.overlay.hide_animated)
        gui.overlay.set_content(viewer)
        gui.overlay.show_animated()
    except Exception as e:
        logger.error(f"Ошибка при показе изображения: {e}")


def clipboard_image_to_controller(gui) -> bool:
    from PyQt6.QtWidgets import QApplication

    cb = QApplication.clipboard()
    if not cb.mimeData().hasImage():
        return False
    qimg = cb.image()
    if qimg.isNull():
        return False
    buf = QBuffer()
    buf.open(QIODevice.OpenModeFlag.WriteOnly)
    qimg.save(buf, "PNG")
    img_bytes = buf.data().data()
    gui.staged_image_data.append(img_bytes)
    gui.event_bus.emit(Events.Chat.STAGE_IMAGE, {"image_data": img_bytes})
    show_image_preview_bar(gui)
    gui.image_preview_bar.add_image(img_bytes)
    update_send_button_state(gui)
    return True


def attach_images(gui):
    file_paths, __ = QFileDialog.getOpenFileNames(
        gui,
        _("Выберите изображения", "Select Images"),
        "",
        _("Файлы изображений (*.png *.jpg *.jpeg *.bmp *.gif)", "Image Files (*.png *.jpg *.jpeg *.bmp *.gif)"),
    )
    if file_paths:
        for file_path in file_paths:
            gui.event_bus.emit(Events.Chat.STAGE_IMAGE, {"image_data": file_path})
        for file_path in file_paths:
            try:
                with open(file_path, "rb") as f:
                    img_data = f.read()
                    gui.staged_image_data.append(img_data)
                    show_image_preview_bar(gui)
                    gui.image_preview_bar.add_image(img_data)
            except Exception as e:
                logger.error(f"Ошибка чтения файла {file_path}: {e}")
        logger.info(f"Прикреплены изображения: {file_paths}")
        update_send_button_state(gui)


def clear_staged_images(gui):
    gui.event_bus.emit(Events.Chat.CLEAR_STAGED_IMAGES)
    gui.staged_image_data.clear()
    if getattr(gui, "image_preview_bar", None):
        gui.image_preview_bar.clear()
        hide_image_preview_bar(gui)
    update_send_button_state(gui)


def send_screen_capture(gui):
    logger.info("Запрошена отправка скриншота.")
    frames = gui.event_bus.emit_and_wait(Events.Capture.CAPTURE_SCREEN, {"limit": 1}, timeout=0.5)
    if not frames or not frames[0]:
        from PyQt6.QtWidgets import QMessageBox

        QMessageBox.warning(
            gui,
            _("Ошибка", "Error"),
            _(
                "Не удалось захватить экран. Убедитесь, что анализ экрана включен в настройках.",
                "Failed to capture the screen. Make sure screen analysis is enabled in settings.",
            ),
        )
        return
    for frame_data in frames[0]:
        gui.staged_image_data.append(frame_data)
        gui.event_bus.emit(Events.Chat.STAGE_IMAGE, {"image_data": frame_data})
        show_image_preview_bar(gui)
        gui.image_preview_bar.add_image(frame_data)
    update_send_button_state(gui)


def position_mita_status(gui):
    if not hasattr(gui, "mita_status") or not gui.mita_status:
        return
    chat_viewport = gui.chat_window.viewport().rect()
    status_width = gui.mita_status.width()
    status_height = gui.mita_status.height()
    x = chat_viewport.width() - status_width - 20
    y = chat_viewport.height() - status_height - 20
    gui.mita_status.move(gui.chat_window.mapToParent(QPoint(x, y)))
