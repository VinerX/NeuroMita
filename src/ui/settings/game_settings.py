
from pathlib import Path

from PyQt6.QtCore import QUrl
from PyQt6.QtGui import QDesktopServices
from PyQt6.QtWidgets import (
    QComboBox,
    QFileDialog,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QMessageBox,
    QWidget,
)
from controllers.gui.async_runner import dispatch_to_gui
from core.events import Events, get_event_bus

from ui.settings.beat_settings_presentation import (
    BeatBackendSelected,
    BeatOpenCacheRequested,
    BeatOpenDirectory,
    BeatOpenHubRequested,
    BeatRebuildCacheRequested,
    BeatSettingsActivated,
    BeatSettingsState,
    BeatShowMessage,
)
from ui.gui_templates import create_settings_section
from ui.settings.dialogue_settings import add_dialogue_settings_section
from ui.settings.settings_access import get_setting
from core.services import use
from services.contracts import CharacterRegistry, GameLinkService
from utils import getTranslationVariant as _
from localization.live import tr_set


_BEAT_BACKEND_OPTIONS = ("auto", "beat_this", "librosa", "dsp_fallback")


def _manual_game_translate(russian: str, english: str) -> str:
    return _(russian, english) if callable(_) else russian


def _manual_game_display_name(game_id: str) -> str:
    return {
        "chess": _manual_game_translate("Шахматы", "Chess"),
        "seabattle": _manual_game_translate("Морской бой", "Sea Battle"),
    }.get(str(game_id or "").split("/", 1)[0].lower(), str(game_id or ""))


def _manual_game_button_text(game_id: str, sandbox_name: str, unity_name: str = "") -> str:
    game_name = _manual_game_display_name(game_id)
    if unity_name and unity_name != sandbox_name:
        return _manual_game_translate("{}: {} / Unity: {}", "{}: {} / Unity: {}").format(
            game_name, sandbox_name, unity_name
        )
    return _manual_game_translate("{} с {}", "{} with {}").format(game_name, sandbox_name)


def _set_sandbox_current_character(character_id: str) -> None:
    get_event_bus().emit(
        Events.Character.SET_CURRENT,
        {"character_id": str(character_id or "")},
    )


def _unity_target_character():
    try:
        game_link = use(GameLinkService)
        if not game_link.is_connected():
            return None
        unity_id = game_link.unity_target_character_id()
        return use(CharacterRegistry).get(unity_id) if unity_id else None
    except Exception:
        return None


def _select_manual_game_character(launcher_character, unity_character, choose_target):
    """Resolve the explicit owner for a desktop-launched mini-game."""
    if unity_character is None or str(unity_character.char_id) == str(launcher_character.char_id):
        return launcher_character

    def _label(character):
        name = str(getattr(character, "display_name", "") or character.char_id)
        return f"{name} ({character.char_id})"

    choices = [_label(unity_character), _label(launcher_character)]
    selected = choose_target(choices, choices[0])
    if selected == choices[0]:
        return unity_character
    if selected == choices[1]:
        return launcher_character
    return None


def _resolve_manual_game_target(gui, launcher_character):
    """Offer the current Unity target when it differs from the launcher selection."""
    unity_character = _unity_target_character()

    def _choose(choices, preferred):
        selected, accepted = QInputDialog.getItem(
            gui,
            _("Персонаж для игры", "Choose a character for the game"),
            _manual_game_translate(
                "В Sandbox выбран {sandbox}, в Unity игрок общается с {unity}. С кем начать игру?",
                "Sandbox has {sandbox} selected, while Unity is talking to {unity}. Who should play?",
            ).format(
                sandbox=getattr(launcher_character, "display_name", "") or launcher_character.char_id,
                unity=getattr(unity_character, "display_name", "") or unity_character.char_id,
            ),
            choices,
            choices.index(preferred),
            False,
        )
        return selected if accepted else None

    return _select_manual_game_character(launcher_character, unity_character, _choose), unity_character


def _start_manual_game(gui, game_id: str) -> None:
    """Open a mini-game for an explicitly resolved character."""
    try:
        character = use(CharacterRegistry).current()
    except Exception:
        character = None

    if character is None:
        QMessageBox.warning(
            gui,
            _("Игра недоступна", "Game unavailable"),
            _(
                "Мита ещё не загружена. Дождитесь готовности приложения и повторите.",
                "Mita is not loaded yet. Wait for the application to finish starting and try again.",
            ),
        )
        return

    launcher_character = character
    character, unity_character = _resolve_manual_game_target(gui, launcher_character)
    if character is None:
        return
    if not hasattr(character, "game_manager"):
        QMessageBox.warning(
            gui,
            _("Игра недоступна", "Game unavailable"),
            _(
                "Выбранный персонаж ещё не загружен. Выберите текущего персонажа лаунчера и повторите.",
                "The selected character is not loaded yet. Choose the launcher's current character and try again.",
            ),
        )
        return

    if (
        unity_character is not None
        and str(character.char_id) == str(unity_character.char_id)
        and str(character.char_id) != str(launcher_character.char_id)
    ):
        _set_sandbox_current_character(character.char_id)

    if character.game_manager.start_game_from_player(game_id):
        return

    QMessageBox.warning(
        gui,
        _("Не удалось запустить игру", "Could not start game"),
        _(
            "Включите общий переключатель игр и разрешение для выбранной игры. "
            "При подключённом Unity также разрешите запуск игр с Unity.",
            "Enable games globally and allow the selected game. "
            "When Unity is connected, also allow games while Unity is connected.",
        ),
    )


def _bind_manual_game_launch_buttons(gui) -> None:
    """Keep the action buttons in sync with both game enable switches."""
    mappings = (
        ("ENABLE_GAME_CHESS", "launch_chess_button"),
        ("ENABLE_GAME_SEABATTLE", "launch_seabattle_button"),
    )

    def _sync(_=None) -> None:
        global_enabled = bool(getattr(gui, "ENABLE_GAMES", None) and gui.ENABLE_GAMES.isChecked())
        registry = use(CharacterRegistry)
        launcher_character = registry.current()
        sandbox_id = str(
            getattr(launcher_character, "char_id", "")
            or registry.current_id()
            or ""
        )
        sandbox_name = str(
            getattr(launcher_character, "display_name", "")
            or registry.display_name_of(sandbox_id)
            or sandbox_id
            or "?"
        )
        unity_character = _unity_target_character()
        unity_name = str(
            getattr(unity_character, "display_name", "")
            or getattr(unity_character, "char_id", "")
            or ""
        )
        try:
            unity_connected = bool(use(GameLinkService).is_connected())
        except Exception:
            unity_connected = False
        allow_toggle = getattr(gui, "ALLOW_GAMES_WHEN_CONNECTED", None)
        connection_allowed = not unity_connected or bool(allow_toggle and allow_toggle.isChecked())
        for setting_name, button_name in mappings:
            toggle = getattr(gui, setting_name, None)
            button = getattr(gui, button_name, None)
            if button is not None:
                button.setEnabled(global_enabled and connection_allowed and bool(toggle and toggle.isChecked()))
                button.setText(_manual_game_button_text(
                    "chess" if setting_name.endswith("CHESS") else "seabattle",
                    sandbox_name,
                    unity_name,
                ))
                if unity_name and unity_name != sandbox_name:
                    tooltip = _manual_game_translate(
                        "Sandbox: {}. Unity: {}. При запуске можно выбрать персонажа.",
                        "Sandbox: {}. Unity: {}. Choose the game character when launching.",
                    ).format(sandbox_name, unity_name)
                else:
                    tooltip = _manual_game_translate(
                        "Запустить игру с {}.", "Start the game with {}."
                    ).format(sandbox_name)
                button.setToolTip(tooltip)

    for setting_name in (
        "ENABLE_GAMES",
        "ENABLE_GAME_CHESS",
        "ENABLE_GAME_SEABATTLE",
        "ALLOW_GAMES_WHEN_CONNECTED",
    ):
        toggle = getattr(gui, setting_name, None)
        if toggle is None:
            continue
        callbacks = getattr(toggle, "_settings_dependency_sync_callbacks", None)
        if callbacks is None:
            callbacks = []
            setattr(toggle, "_settings_dependency_sync_callbacks", callbacks)
        callbacks.append(_sync)
        toggle.stateChanged.connect(_sync)
    _sync()

    if not getattr(gui, "_manual_game_launch_event_callbacks", None):
        callbacks = []
        for event_name in (
            Events.Character.CURRENT_CHANGED,
            Events.Server.GAME_DIALOGUE_TARGET_CHANGED,
            Events.GUI.UPDATE_STATUS_COLORS,
        ):
            callback = lambda _event, sync=_sync: dispatch_to_gui(gui, sync)
            get_event_bus().subscribe(event_name, callback, weak=False)
            callbacks.append(callback)
        gui._manual_game_launch_event_callbacks = callbacks


def _format_beat_cache_size(total_bytes: int) -> str:
    if total_bytes < 1024:
        return f"{total_bytes} B"
    if total_bytes < 1024 * 1024:
        return f"{total_bytes / 1024.0:.1f} KB"
    return f"{total_bytes / (1024.0 * 1024.0):.1f} MB"


def _format_beat_status_text(state: BeatSettingsState) -> str:
    labels = dict(state.backend_labels)
    selected_line = _("Режим: {}", "Mode: {}").format(
        labels.get(state.preferred_backend, state.preferred_backend)
    )
    active_line = _("Активен: {}", "Active: {}").format(
        labels.get(state.resolved_backend, state.resolved_backend)
    )
    cache_line = _("Кеш: {} файлов, {}", "Cache: {} files, {}").format(
        state.cache_entries,
        _format_beat_cache_size(state.cache_bytes),
    )
    lines = [selected_line, active_line, cache_line]
    if state.message:
        lines.append(state.message)
    return "\n".join(lines)


def _beat_view_model(gui):
    view_model = getattr(gui, "_beat_settings_view_model", None)
    if view_model is None:
        raise RuntimeError("Beat settings view model is not attached")
    return view_model


def _attach_beat_view_model(gui, view_model) -> None:
    gui._beat_settings_view_model = view_model
    view_model.state_changed.connect(lambda state: _render_beat_state(gui, state))
    view_model.effect_emitted.connect(lambda effect: _handle_beat_effect(gui, effect))


def _render_beat_state(gui, state: BeatSettingsState) -> None:
    combo = getattr(gui, "beat_sync_backend_combo", None)
    if combo is not None:
        combo.blockSignals(True)
        try:
            combo.clear()
            labels = dict(state.backend_labels)
            for backend_id in state.available_backends:
                combo.addItem(labels.get(backend_id, backend_id), backend_id)
            index = combo.findData(state.preferred_backend)
            if index >= 0:
                combo.setCurrentIndex(index)
        finally:
            combo.blockSignals(False)

    label = getattr(gui, "beat_sync_status_label", None)
    if label is not None:
        label.setText(_format_beat_status_text(state))
        label.show()

    for attr_name in (
        "beat_sync_manage_button",
        "beat_sync_open_cache_button",
        "beat_sync_rebuild_button",
    ):
        widget = getattr(gui, attr_name, None)
        if widget is not None:
            widget.setEnabled(not state.busy)


def _handle_beat_effect(gui, effect) -> None:
    if isinstance(effect, BeatOpenDirectory):
        QDesktopServices.openUrl(QUrl.fromLocalFile(effect.directory))
        return
    if isinstance(effect, BeatShowMessage):
        method = QMessageBox.critical if effect.error else QMessageBox.information
        method(gui, effect.title, effect.message)


def _rebuild_beat_sync_cache(gui) -> None:
    start_dir = str(
        get_setting(
            gui,
            "BEAT_SYNC_LAST_SCAN_DIR",
            str(Path.cwd()),
        )
    )
    selected_dir = QFileDialog.getExistingDirectory(
        gui,
        _("Выберите папку с музыкой", "Select music folder"),
        start_dir,
    )
    if not selected_dir:
        return
    _beat_view_model(gui).dispatch(BeatRebuildCacheRequested(selected_dir))


def _open_beat_cache_folder(gui) -> None:
    _beat_view_model(gui).dispatch(BeatOpenCacheRequested())


def _open_beat_ai_hub(gui) -> None:
    _beat_view_model(gui).dispatch(BeatOpenHubRequested())


def _create_beat_backend_selector(gui) -> QWidget:
    frame = QWidget()
    frame.setObjectName("SettingRow")
    layout = QHBoxLayout(frame)
    layout.setContentsMargins(0, 2, 0, 2)
    layout.setSpacing(10)

    label = tr_set(QLabel(), "Backend Beat Sync", "Beat Sync backend")
    label.setMinimumWidth(140)
    label.setMaximumWidth(140)
    label.setWordWrap(True)

    combo = QComboBox()

    def _save_backend(_index: int) -> None:
        _beat_view_model(gui).dispatch(
            BeatBackendSelected(str(combo.currentData() or "auto"))
        )

    combo.currentIndexChanged.connect(_save_backend)

    layout.addWidget(label)
    layout.addWidget(combo, 1)

    gui.beat_sync_backend_combo = combo
    gui.beat_sync_backend_combo_frame = frame
    return frame


def _create_beat_status_label_widget(gui) -> QWidget:
    frame = QWidget()
    frame.setObjectName("SettingRow")
    layout = QHBoxLayout(frame)
    layout.setContentsMargins(0, 2, 0, 2)
    layout.setSpacing(10)

    label = tr_set(QLabel(), "Статус Beat Sync", "Beat Sync status")
    label.setMinimumWidth(140)
    label.setMaximumWidth(140)
    label.setWordWrap(True)

    value = QLabel("")
    value.setObjectName("SeparatorLabel")
    value.setWordWrap(True)

    layout.addWidget(label)
    layout.addWidget(value, 1)

    gui.beat_sync_status_label = value
    gui.beat_sync_status_label_frame = frame
    return frame


def setup_game_controls(self, parent, *, beat_view_model) -> None:
    _attach_beat_view_model(self, beat_view_model)

    mod_config = [
        {
            'label': _('Внутриигровые меню мода и обработка запросов из игры.',
                       'In-game mod menus and handling of requests from the game.'),
            'type': 'text',
        },
        {
            'label': _('Меню действий', 'Action menu'),
            'key': 'ACTION_MENU',
            'type': 'checkbutton',
            'default_checkbutton': True,
            'tooltip': _('Показывать меню действий в игре (Y)', 'Show action menu in game (Y)'),
        },
        {
            'label': _('Меню выбора Мит', 'Mitas selection menu'),
            'key': 'MITAS_MENU',
            'type': 'checkbutton',
            'default_checkbutton': False,
            'tooltip': _('Показывать меню выбора персонажей Мит в игре', 'Show Mitas character selection menu in game'),
        },
        {
            'label': _('Дерево иерархии мира (устарело)', 'World hierarchy tree (outdated)'),
            'key': 'WORLD_HIERARCHY_TREE',
            'type': 'checkbutton',
            'default_checkbutton': False,
            'tooltip': _(
                'Нейросеть будет знать, какие объекты находятся рядом и расстояние до них. Функция устарела.',
                'The neural network will know which objects are in range and the distance to them. This feature is outdated.',
            ),
        },
        {
            'label': _('Игнорировать запросы', 'Ignore requests'),
            'key': 'IGNORE_GAME_REQUESTS',
            'type': 'checkbutton',
            'default_checkbutton': False,
            'tooltip': _('Блокировать запросы из игры', 'Block requests from the game'),
            'widget_name': 'IGNORE_GAME_REQUESTS',
        },
        {
            'label': _('Уровень блокировки', 'Blocking level'),
            'key': 'GAME_BLOCK_LEVEL',
            'type': 'combobox',
            'options': ['Idle events', 'All events'],
            'default': 'Idle events',
            'depends_on': 'IGNORE_GAME_REQUESTS',
            'hide_when_disabled': True,
            'tooltip': _(
                'Idle events — блокирует запросы от таймера молчания, All events — блокирует все запросы с внутриигровых событий',
                'Idle events - blocks idle timer requests, All events - blocks all in-game event requests',
            ),
        },
    ]

    create_settings_section(
        self,
        parent,
        _("Настройки мода", "Mod Settings"),
        mod_config,
        icon_name='fa5s.sliders-h'
    )

    add_dialogue_settings_section(self, parent)

    games_config = [
        {
            'label': _('Включение и выбор доступных мини-игр с Митой.',
                       'Enable and choose available mini-games with Mita.'),
            'type': 'text',
        },
        {
            'label': _('Включить игры', 'Enable games'),
            'key': 'ENABLE_GAMES',
            'type': 'checkbutton',
            'default_checkbutton': False,
            'tooltip': _(
                'Глобально разрешает запуск встроенных игр (шахматы, морской бой).',
                'Globally allows launching built-in games (Chess, Sea Battle).',
            ),
        },
        {
            'label': _('Разрешить запуск игр при подключенном Unity', 'Allow games when Unity is connected'),
            'key': 'ALLOW_GAMES_WHEN_CONNECTED',
            'type': 'checkbutton',
            'default_checkbutton': False,
            'depends_on': 'ENABLE_GAMES',
            'tooltip': _(
                'Если выключено и Unity подключен к серверу, игры не будут запускаться.',
                'If OFF and Unity client is connected, games will not be launched.',
            ),
        },
        {
            'label': _('Шахматы', 'Chess'),
            'key': 'ENABLE_GAME_CHESS',
            'type': 'checkbutton',
            'default_checkbutton': False,
            'depends_on': 'ENABLE_GAMES',
            'tooltip': _('Разрешить игру "Шахматы".', 'Allow "Chess" game.'),
        },
        {
            'label': _('Морской бой', 'Sea Battle'),
            'key': 'ENABLE_GAME_SEABATTLE',
            'type': 'checkbutton',
            'default_checkbutton': False,
            'depends_on': 'ENABLE_GAMES',
            'tooltip': _('Разрешить игру "Морской бой".', 'Allow "Sea Battle" game.'),
        },
        {
            'type': 'subsection',
            'label': _('Ручной запуск', 'Manual launch'),
        },
        {
            'type': 'button_group',
            'buttons': [
                {
                    'label': _('Запустить шахматы', 'Start chess'),
                    'command': lambda: _start_manual_game(self, 'chess'),
                    'widget_name': 'launch_chess_button',
                    'tooltip': _(
                        'Открыть шахматы с выбранной Митой. Если игровые запросы не заглушены и реакции L2 включены, '
                        'Мита отреагирует в чате.',
                        'Open chess with the selected Mita. If game requests are not muted and L2 reactions are enabled, '
                        'Mita will react in chat.',
                    ),
                },
                {
                    'label': _('Запустить морской бой', 'Start Sea Battle'),
                    'command': lambda: _start_manual_game(self, 'seabattle'),
                    'widget_name': 'launch_seabattle_button',
                    'tooltip': _(
                        'Открыть морской бой с выбранной Митой. Если игровые запросы не заглушены и реакции L2 включены, '
                        'Мита отреагирует в чате.',
                        'Open Sea Battle with the selected Mita. If game requests are not muted and L2 reactions are enabled, '
                        'Mita will react in chat.',
                    ),
                },
            ],
        },
        {
            'type': 'end',
        },
    ]

    create_settings_section(
        self,
        parent,
        _("Игры", "Games"),
        games_config,
        icon_name='fa5s.gamepad'
    )
    _bind_manual_game_launch_buttons(self)

    beat_sync_config = [
        {
            'label': _('Синхронизация покачивания головы Миты с битами музыки.',
                       'Sync Mita head bob with the music beats.'),
            'type': 'text',
        },
        {
            'label': _('Синхронизация покачивания от бита', 'Beat-driven head bob sync'),
            'key': 'BEAT_SYNC_ENABLED',
            'type': 'checkbutton',
            'default_checkbutton': False,
            'tooltip': _(
                'Если включено, Unity будет запрашивать биты трека у Python перед воспроизведением.',
                'If enabled, Unity will request track beats from Python before playback.',
            ),
        },
        {
            'type': 'widget',
            'factory': _create_beat_backend_selector,
        },
        {
            'type': 'widget',
            'factory': _create_beat_status_label_widget,
        },
        {
            'type': 'subsection',
            'label': _('Управление', 'Management'),
        },
        {
            'type': 'button_group',
            'buttons': [
                {
                    'label': _('Открыть AI Hub', 'Open AI Hub'),
                    'command': lambda: _open_beat_ai_hub(self),
                    'widget_name': 'beat_sync_manage_button',
                },
            ],
        },
        {
            'type': 'end',
        },
        {
            'type': 'subsection',
            'label': _('Кеш', 'Cache'),
        },
        {
            'type': 'button_group',
            'buttons': [
                {
                    'label': _('Открыть папку кеша', 'Open cache folder'),
                    'command': lambda: _open_beat_cache_folder(self),
                    'widget_name': 'beat_sync_open_cache_button',
                },
                {
                    'label': _('Переиндексировать кеш', 'Reindex cache'),
                    'command': lambda: _rebuild_beat_sync_cache(self),
                    'widget_name': 'beat_sync_rebuild_button',
                },
            ],
        },
        {
            'type': 'end',
        },
    ]

    create_settings_section(
        self,
        parent,
        _('Бит-синхронизация (Beat This)', 'Beat Sync (Beat This)'),
        beat_sync_config,
        icon_name='fa5s.music'
    )
    beat_view_model.dispatch(BeatSettingsActivated())

    # Живая смена языка: комбобокс бэкендов и строки статуса строятся из строк,
    # переведённых на момент вызова (не через реестр tr_set), поэтому при смене
    # языка пере-собираем их вручную. Подписываемся один раз на GUI-объект.
    if not getattr(self, "_beat_sync_lang_hook_bound", False):
        self._beat_sync_lang_hook_bound = True
        try:
            from localization.live import language_changed_signal
            language_changed_signal().connect(
                lambda *_a: beat_view_model.dispatch(BeatSettingsActivated())
            )
        except Exception:
            pass
