
from pathlib import Path

from PyQt6.QtCore import QUrl
from PyQt6.QtGui import QDesktopServices
from PyQt6.QtWidgets import (
    QComboBox,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QWidget,
)

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
from ui.settings.settings_access import get_setting
from utils import getTranslationVariant as _
from localization.live import tr_set


_BEAT_BACKEND_OPTIONS = ("auto", "beat_this", "librosa", "dsp_fallback")


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

    dialogue_config = [
        {
            'label': _('Управление автодиалогами Мит и режимом ГеймМастера.',
                       'Manage Mitas auto-dialogues and the GameMaster mode.'),
            'type': 'text',
        },
        {
            'label': _('Диалоги Мит автоматически', "Mitas's dialogues automatically"),
            'key': 'MITA_DIALOGUE_AUTO',
            'type': 'checkbutton',
            'default_checkbutton': False,
            'tooltip': _(
                'Миты автоматически отвечают по порядку, без вызова команд',
                'Mitas response by order, without using commands',
            ),
        },
        {
            'label': _('Лимит разговоров NPC %', 'Limit NPC conversation'),
            'key': 'CC_Limit_mod',
            'type': 'entry',
            'default': 100,
            'tooltip': _(
                'Насколько может отклоняться длина диалога NPC без участия игрока',
                'How long NPC can talk ignoring player',
            ),
            'depends_on': 'MITA_DIALOGUE_AUTO',
        },
        {
            'label': _('ГеймМастер — экспериментальная функция', 'GameMaster is experimental feature'),
            'type': 'text',
        },
        {
            'label': _('ГеймМастер включён', 'GameMaster is on'),
            'key': 'GM_ON',
            'type': 'checkbutton',
            'default_checkbutton': False,
            'tooltip': _('Помогает вести диалоги, в теории устраняя проблемы', 'Helps manage dialogues and reduce issues in theory'),
        },
        {
            'label': _('Задача ГМу', 'GM task'),
            'key': 'GM_SMALL_PROMPT',
            'type': 'textarea',
            'default': "",
        },
        {
            'label': _('ГеймМастер вмешивается каждые', 'GameMaster intervene each'),
            'key': 'GM_REPEAT',
            'type': 'entry',
            'default': 2,
            'tooltip': _(
                'Пример: 3 означает, что после каждых двух фраз ГМ напишет своё сообщение',
                'Example: 3 means that after 2 phrases GM will write his message',
            ),
        },
    ]

    create_settings_section(
        self,
        parent,
        _("Настройки диалогов и GameMaster", "Dialogue and GameMaster Settings"),
        dialogue_config
    )

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
        mod_config
    )

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
    ]

    create_settings_section(
        self,
        parent,
        _("Игры", "Games"),
        games_config
    )

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
        beat_sync_config
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
