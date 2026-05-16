from ui.gui_templates import create_settings_section, create_section_header
from utils import getTranslationVariant as _


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
            'label': _('Автоустановка beat-this', 'Auto-install beat-this'),
            'key': 'BEAT_SYNC_AUTO_INSTALL',
            'type': 'checkbutton',
            'default_checkbutton': True,
            'depends_on': 'BEAT_SYNC_ENABLED',
            'tooltip': _(
                'Если пакет beat-this не установлен, попытаться установить его автоматически при первом запуске.',
                'If beat-this is not installed, try to install it automatically on first use.',
            ),
        },
        {
            'label': _('Передавать трек через файл', 'Transfer track via file'),
            'key': 'BEAT_SYNC_USE_FILE_TRANSFER',
            'type': 'checkbutton',
            'default_checkbutton': True,
            'depends_on': 'BEAT_SYNC_ENABLED',
            'tooltip': _(
                'Если выключено, Python-анализ битов не будет запрашиваться, и останется только локальный DSP fallback в Unity.',
                'If OFF, Python beat analysis will not be requested and only the local Unity DSP fallback will remain.',
            ),
        },
        {
            'label': _('Потоковая отправка битов', 'Stream beats in chunks'),
            'key': 'BEAT_SYNC_STREAMING',
            'type': 'checkbutton',
            'default_checkbutton': True,
            'depends_on': 'BEAT_SYNC_ENABLED',
            'tooltip': _(
                'Если анализ идёт медленно, биты будут приходить частями по мере обработки.',
                'If analysis is slow, beats will be delivered in chunks while processing.',
            ),
        },
        {
            'label': _('Размер чанка (сек)', 'Chunk size (sec)'),
            'key': 'BEAT_SYNC_CHUNK_SECONDS',
            'type': 'entry',
            'default': 8,
            'depends_on': 'BEAT_SYNC_ENABLED',
            'tooltip': _(
                'Рекомендуется 6-12 секунд. Меньше значение = быстрее первые биты.',
                'Recommended 6-12 seconds. Smaller = earlier first beats.',
            ),
        },
        {
            'label': _('Мин. уверенность бита', 'Min beat confidence'),
            'key': 'BEAT_SYNC_MIN_CONFIDENCE',
            'type': 'entry',
            'default': 0.2,
            'depends_on': 'BEAT_SYNC_ENABLED',
            'tooltip': _(
                'Порог уверенности детекции бита (0.0 - 1.0).',
                'Threshold to filter noisy beats (0.0 - 1.0).',
            ),
        },
    ]

    create_settings_section(
        self,
        parent,
        _('Бит-синхронизация (Beat This)', 'Beat Sync (Beat This)'),
        beat_sync_config
    )
