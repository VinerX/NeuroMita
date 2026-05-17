import threading
from pathlib import Path

from PyQt6.QtWidgets import QFileDialog

from core.events import Events
from game_connections.services.beat_service import get_beat_service
from main_logger import logger
from ui.gui_templates import create_settings_section, create_section_header
from utils import getTranslationVariant as _


def _format_beat_cache_size(total_bytes: int) -> str:
    if total_bytes < 1024:
        return f"{total_bytes} B"
    if total_bytes < 1024 * 1024:
        return f"{total_bytes / 1024.0:.1f} KB"
    return f"{total_bytes / (1024.0 * 1024.0):.1f} MB"


def _format_beat_status_text(extra_message: str | None = None) -> str:
    service = get_beat_service()
    status = service.get_backend_status()
    install_state = _("установлен", "installed") if status.beat_this_installed else _("не установлен", "not installed")
    ready_state = _("готов", "ready") if status.beat_this_ready else _("не прогрет", "not warmed up")
    backend_line = _("Backend: {}", "Backend: {}").format(status.active_backend)
    cache_line = _("Кеш: {} файлов, {}", "Cache: {} files, {}").format(
        status.cache_entries,
        _format_beat_cache_size(status.cache_bytes),
    )
    root_line = _("Папка кеша: {}", "Cache folder: {}").format(status.cache_dir)
    status_line = _("beat-this: {}, {}", "beat-this: {}, {}").format(install_state, ready_state)

    lines = [status_line, backend_line, cache_line, root_line]
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
        for attr_name in ("beat_sync_install_button", "beat_sync_rebuild_button"):
            btn = getattr(gui, attr_name, None)
            if btn is not None:
                btn.setEnabled(enabled)

    if threading.current_thread() is threading.main_thread():
        _apply()
    else:
        gui.run_ui_task_signal.emit(_apply)


def _refresh_beat_sync_status(gui, extra_message: str | None = None) -> None:
    try:
        _set_beat_status_label(gui, _format_beat_status_text(extra_message))
    except Exception as exc:
        logger.error(f"[BeatSync] status refresh failed: {exc}", exc_info=True)


def _install_beat_sync_backend(gui) -> None:
    _set_beat_action_buttons_enabled(gui, False)
    _set_beat_status_label(gui, _("Установка beat-this...", "Installing beat-this..."))

    def _worker():
        try:
            status = get_beat_service().install_or_update_backend()
            msg = _("Пакет beat-this готов. Backend: {}", "beat-this is ready. Backend: {}").format(status.active_backend)
            _refresh_beat_sync_status(gui, msg)
            gui.event_bus.emit(Events.GUI.SHOW_INFO_MESSAGE, {
                "title": _("Beat Sync", "Beat Sync"),
                "message": msg,
            })
        except Exception as exc:
            logger.error(f"[BeatSync] install/update failed: {exc}", exc_info=True)
            msg = _("Не удалось установить beat-this:\n{}", "Failed to install beat-this:\n{}").format(exc)
            _refresh_beat_sync_status(gui, msg)
            gui.event_bus.emit(Events.GUI.SHOW_ERROR_MESSAGE, {
                "title": _("Beat Sync", "Beat Sync"),
                "message": msg,
            })
        finally:
            _set_beat_action_buttons_enabled(gui, True)

    threading.Thread(target=_worker, name="beat-sync-install", daemon=True).start()


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


def setup_game_controls(self, parent):
    create_section_header(parent, _("Настройки игры", "Game Settings"))

    api_config = [
        {
            'label': _('НЕ НАЖИМАТЬ!', 'Do not turn this on!'),
            'type': 'text',
        },
        {
            'label': _('Использовать новый API', 'Use new API'),
            'key': 'USE_NEW_API',
            'type': 'checkbutton',
            'default_checkbutton': False,
            'tooltip': _(
                'Использовать новую систему передачи данных с задачами',
                'Use new task-based data transfer system',
            ),
        },
    ]

    create_settings_section(
        self,
        parent,
        _("Настройки сервера", "Server settings"),
        api_config
    )

    dialogue_config = [
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
            'depends_on': 'MITA_DIALOGUE_OLD_ON',
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
            'label': _('Статус Beat Sync', 'Beat Sync status'),
            'type': 'text',
            'widget_name': 'beat_sync_status_label',
        },
        {
            'label': _('Установить / обновить beat-this', 'Install / update beat-this'),
            'type': 'button',
            'command': lambda: _install_beat_sync_backend(self),
            'widget_name': 'beat_sync_install_button',
            'tooltip': _(
                'Устанавливает или обновляет backend beat-this. Выполняется вручную, без авто-скачивания при запросе из Unity.',
                'Installs or updates the beat-this backend. Manual action, no auto-download during Unity requests.',
            ),
        },
        {
            'label': _('Построить кеш битов для папки музыки', 'Build beat cache for music folder'),
            'type': 'button',
            'command': lambda: _rebuild_beat_sync_cache(self),
            'widget_name': 'beat_sync_rebuild_button',
            'tooltip': _(
                'Проходит по выбранной папке, считает биты для всех поддерживаемых аудиофайлов и сохраняет JSON-кеш в корне Python-проекта.',
                'Scans the selected folder, computes beats for all supported audio files, and saves JSON cache files in the Python project root.',
            ),
        },
    ]

    create_settings_section(
        self,
        parent,
        _('Бит-синхронизация (Beat This)', 'Beat Sync (Beat This)'),
        beat_sync_config
    )
    _refresh_beat_sync_status(self)
