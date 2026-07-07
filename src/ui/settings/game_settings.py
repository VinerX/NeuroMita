
import threading
from pathlib import Path

from PyQt6.QtCore import QUrl
from PyQt6.QtGui import QDesktopServices
from PyQt6.QtWidgets import QComboBox, QFileDialog, QHBoxLayout, QLabel, QWidget

from core.events import Events
from game_connections.services.beat_backend_spec import (
    BACKEND_AUTO,
    BACKEND_BEAT_THIS,
    BACKEND_DSP,
    BACKEND_LIBROSA,
    backend_display_name,
    normalize_backend_choice,
)
from game_connections.services.beat_service import get_beat_service
from main_logger import logger
from ui.async_bus import dispatch_to_gui
from ui.gui_templates import create_settings_section, create_section_header
from utils import getTranslationVariant as _
from localization.live import tr_set


_BEAT_BACKEND_OPTIONS = (
    (BACKEND_AUTO, _("Авто", "Auto")),
    (BACKEND_BEAT_THIS, "Beat This"),
    (BACKEND_LIBROSA, "Librosa"),
    (BACKEND_DSP, _("DSP fallback", "DSP fallback")),
)


def _format_beat_cache_size(total_bytes: int) -> str:
    if total_bytes < 1024:
        return f"{total_bytes} B"
    if total_bytes < 1024 * 1024:
        return f"{total_bytes / 1024.0:.1f} KB"
    return f"{total_bytes / (1024.0 * 1024.0):.1f} MB"


def _format_beat_status_text(status, extra_message: str | None = None) -> str:
    selected_line = _("Режим: {}", "Mode: {}").format(
        backend_display_name(status.preferred_backend)
    )
    active_line = _("Активен: {}", "Active: {}").format(
        backend_display_name(status.resolved_backend)
    )
    cache_line = _("Кеш: {} файлов, {}", "Cache: {} files, {}").format(
        status.cache_entries,
        _format_beat_cache_size(status.cache_bytes),
    )

    lines = [selected_line, active_line, cache_line]
    if extra_message:
        lines.append(extra_message)
    return "\n".join(lines)


def _set_beat_status_label(gui, text: str) -> None:
    label = getattr(gui, "beat_sync_status_label", None)
    if label is None:
        return

    def _apply():
        label.setText(text)
        label.show()

    if threading.current_thread() is threading.main_thread():
        _apply()
    else:
        gui.run_ui_task_signal.emit(_apply)


def _set_beat_action_buttons_enabled(gui, enabled: bool) -> None:
    def _apply():
        for attr_name in (
            "beat_sync_manage_button",
            "beat_sync_open_cache_button",
            "beat_sync_rebuild_button",
        ):
            widget = getattr(gui, attr_name, None)
            if widget is not None:
                widget.setEnabled(enabled)

    if threading.current_thread() is threading.main_thread():
        _apply()
    else:
        gui.run_ui_task_signal.emit(_apply)


def _refresh_beat_sync_status(gui, extra_message: str | None = None) -> None:
    # May be called from the event-bus processor thread (e.g. install
    # finished/failed callbacks). All Qt widget mutations must happen on the
    # GUI thread or Qt prints "QBasicTimer::start: Timers cannot be started
    # from another thread" and randomly corrupts widget state.
    def _apply():
        try:
            status = get_beat_service().get_backend_status()
            _update_beat_backend_combo(gui, status)
            _sync_beat_buttons(gui, status)
            _set_beat_status_label(gui, _format_beat_status_text(status, extra_message))
        except Exception as exc:
            logger.error(f"[BeatSync] status refresh failed: {exc}", exc_info=True)

    if threading.current_thread() is threading.main_thread():
        _apply()
    else:
        gui.run_ui_task_signal.emit(_apply)


def _install_beat_sync_backend(gui) -> None:
    _open_beat_ai_hub(gui)


def _initialize_beat_sync_backend(gui) -> None:
    _open_beat_ai_hub(gui)


def _uninstall_beat_sync_backend(gui) -> None:
    _open_beat_ai_hub(gui)


def _rebuild_beat_sync_cache(gui) -> None:
    start_dir = str(gui._get_setting("BEAT_SYNC_LAST_SCAN_DIR", str(Path.cwd())))
    selected_dir = QFileDialog.getExistingDirectory(
        gui,
        _("Выберите папку с музыкой", "Select music folder"),
        start_dir,
    )
    if not selected_dir:
        return

    gui._save_setting("BEAT_SYNC_LAST_SCAN_DIR", selected_dir)
    _set_beat_action_buttons_enabled(gui, False)
    _set_beat_status_label(
        gui,
        _("Сканирование музыки и построение кеша...", "Scanning music and building cache..."),
    )

    def _worker():
        try:
            summary = get_beat_service().build_cache_for_directory(selected_dir, auto_install=False)
            msg = _(
                "Обработано: {}/{} | Уже в кеше: {} | Построено: {} | Ошибок: {}",
                "Processed: {}/{} | Cached: {} | Built: {} | Errors: {}",
            ).format(
                summary.scanned_files - summary.failed,
                summary.scanned_files,
                summary.cache_hits,
                summary.generated,
                summary.failed,
            )
            _refresh_beat_sync_status(gui, msg)
            gui.event_bus.emit(Events.GUI.SHOW_INFO_MESSAGE, {
                "title": _("Beat Sync", "Beat Sync"),
                "message": msg,
            })
        except Exception as exc:
            logger.error(f"[BeatSync] cache rebuild failed: {exc}", exc_info=True)
            msg = _("Не удалось построить кеш битов:\n{}", "Failed to build beat cache:\n{}").format(exc)
            _refresh_beat_sync_status(gui, msg)
            gui.event_bus.emit(Events.GUI.SHOW_ERROR_MESSAGE, {
                "title": _("Beat Sync", "Beat Sync"),
                "message": msg,
            })
        finally:
            _set_beat_action_buttons_enabled(gui, True)

    threading.Thread(target=_worker, name="beat-sync-cache-build", daemon=True).start()


def _open_beat_cache_folder(gui) -> None:
    cache_dir = get_beat_service().get_backend_status().cache_dir
    path = Path(cache_dir)
    path.mkdir(parents=True, exist_ok=True)
    QDesktopServices.openUrl(QUrl.fromLocalFile(str(path.resolve())))


def _open_beat_ai_hub(gui) -> None:
    preferred = normalize_backend_choice(gui._get_setting("BEAT_SYNC_BACKEND", BACKEND_AUTO))
    gui.event_bus.emit(
        Events.GUI.SHOW_WINDOW,
        {
            "window_id": "ai_hub",
            "payload": {
                "category": "beats",
                "component_id": f"beats:{preferred}",
            },
        },
    )


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
        backend_id = normalize_backend_choice(combo.currentData())
        gui._save_setting("BEAT_SYNC_BACKEND", backend_id)
        get_beat_service().reset_runtime_state()
        _refresh_beat_sync_status(gui)

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


def _combo_backend_ids_for_status(status) -> list[str]:
    backend_ids = [BACKEND_AUTO]
    backends = status.backends if isinstance(status.backends, dict) else {}

    beat_this_state = backends.get(BACKEND_BEAT_THIS) if isinstance(backends.get(BACKEND_BEAT_THIS), dict) else {}
    if beat_this_state.get("installed"):
        backend_ids.append(BACKEND_BEAT_THIS)

    librosa_state = backends.get(BACKEND_LIBROSA) if isinstance(backends.get(BACKEND_LIBROSA), dict) else {}
    if librosa_state.get("installed"):
        backend_ids.append(BACKEND_LIBROSA)

    backend_ids.append(BACKEND_DSP)
    return backend_ids


def _sync_beat_buttons(gui, status) -> None:
    install_button = getattr(gui, "beat_sync_install_button", None)
    uninstall_button = getattr(gui, "beat_sync_uninstall_button", None)
    initialize_button = getattr(gui, "beat_sync_initialize_button", None)

    beat_this_state = status.backends.get(BACKEND_BEAT_THIS) if isinstance(status.backends, dict) else None
    beat_this_installed = bool(beat_this_state.get("installed")) if isinstance(beat_this_state, dict) else False

    def _apply():
        if install_button is not None:
            install_button.setVisible(not beat_this_installed)
        if uninstall_button is not None:
            uninstall_button.setVisible(beat_this_installed)
        if initialize_button is not None:
            initialize_button.setEnabled(True)

    if threading.current_thread() is threading.main_thread():
        _apply()
    else:
        gui.run_ui_task_signal.emit(_apply)


def _update_beat_backend_combo(gui, status) -> None:
    combo = getattr(gui, "beat_sync_backend_combo", None)
    if combo is None:
        return

    available_backend_ids = _combo_backend_ids_for_status(status)
    current_backend = normalize_backend_choice(status.preferred_backend)
    if current_backend not in available_backend_ids:
        current_backend = BACKEND_AUTO
        gui._save_setting("BEAT_SYNC_BACKEND", current_backend)

    combo.blockSignals(True)
    try:
        combo.clear()
        for backend_id, default_label in _BEAT_BACKEND_OPTIONS:
            if backend_id not in available_backend_ids:
                continue
            # backend_display_name переводит вживую (для всех языков), в отличие от
            # default_label, замороженного на языке момента импорта модуля.
            combo.addItem(backend_display_name(backend_id), backend_id)

        selected_index = combo.findData(current_backend)
        if selected_index >= 0:
            combo.setCurrentIndex(selected_index)
    finally:
        combo.blockSignals(False)


def _ensure_beat_install_hooks(gui) -> None:
    if getattr(gui, "_beat_sync_install_hooks_bound", False):
        return

    gui._beat_sync_install_hooks_bound = True
    gui.event_bus.subscribe(Events.Install.TASK_FINISHED, lambda event: _on_beat_install_finished(gui, event), weak=False)
    gui.event_bus.subscribe(Events.Install.TASK_FAILED, lambda event: _on_beat_install_failed(gui, event), weak=False)


def _on_beat_install_finished(gui, event) -> None:
    data = event.data if isinstance(event.data, dict) else {}
    meta = data.get("meta") if isinstance(data.get("meta"), dict) else {}
    if meta.get("kind") != "beats":
        return

    op = str(meta.get("op") or "install")
    msg_map = {
        "install": _("Beat backend установлен", "Beat backend installed"),
        "initialize": _("Beat backend инициализирован", "Beat backend initialized"),
        "uninstall": _("Beat backend удалён", "Beat backend uninstalled"),
    }
    msg = msg_map.get(op, _("Beat backend обновлён", "Beat backend updated"))

    def _apply():
        get_beat_service().reset_runtime_state()
        _set_beat_action_buttons_enabled(gui, True)
        _refresh_beat_sync_status(gui, msg)
        gui.event_bus.emit(
            Events.GUI.SHOW_INFO_MESSAGE,
            {
                "title": _("Beat Sync", "Beat Sync"),
                "message": msg,
            },
        )

    dispatch_to_gui(gui, _apply)

def _on_beat_install_failed(gui, event) -> None:
    data = event.data if isinstance(event.data, dict) else {}
    meta = data.get("meta") if isinstance(data.get("meta"), dict) else {}
    if meta.get("kind") != "beats":
        return

    op = str(meta.get("op") or "install")
    msg_map = {
        "install": _("Ошибка установки Beat backend", "Beat backend installation failed"),
        "initialize": _("Ошибка инициализации Beat backend", "Beat backend initialization failed"),
        "uninstall": _("Ошибка удаления Beat backend", "Beat backend removal failed"),
    }
    msg = msg_map.get(op, _("Ошибка операции Beat backend", "Beat backend operation failed"))

    def _apply():
        get_beat_service().reset_runtime_state()
        _set_beat_action_buttons_enabled(gui, True)
        _refresh_beat_sync_status(gui, msg)
        gui.event_bus.emit(
            Events.GUI.SHOW_ERROR_MESSAGE,
            {
                "title": _("Beat Sync", "Beat Sync"),
                "message": msg,
            },
        )

    dispatch_to_gui(gui, _apply)

def setup_game_controls(self, parent) -> None:
    _ensure_beat_install_hooks(self)

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
    _refresh_beat_sync_status(self)

    # Живая смена языка: комбобокс бэкендов и строки статуса строятся из строк,
    # переведённых на момент вызова (не через реестр tr_set), поэтому при смене
    # языка пере-собираем их вручную. Подписываемся один раз на GUI-объект.
    if not getattr(self, "_beat_sync_lang_hook_bound", False):
        self._beat_sync_lang_hook_bound = True
        try:
            from localization.live import language_changed_signal
            language_changed_signal().connect(lambda *_a: _refresh_beat_sync_status(self))
        except Exception:
            pass
