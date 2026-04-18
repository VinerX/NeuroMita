from ui.gui_templates import create_settings_section, create_section_header
from utils import getTranslationVariant as _

def setup_game_controls(self, parent):
    create_section_header(parent, _("Настройки игры", "Game Settings"))

    api_config = [
        {'label': _('НЕ НАЖИМАТЬ!', 'Do not turn this on!'),
         'type': 'text'},
        {'label': _('Использовать новый API', 'Use new API'), 'key': 'USE_NEW_API', 'type': 'checkbutton',
        'default_checkbutton': False,
        'tooltip': _('Использовать новую систему передачи данных с задачами', 'Use new task-based data transfer system')},
    ]

    create_settings_section(
        self,
        parent,
        _("Настройки сервера", "Server settings"),
        api_config
    )
    
    dialogue_config = [
        {'label': _('Диалоги мит автоматически', 'Mitas\'s dialogues automatically'), 'key': 'MITA_DIALOGUE_AUTO', 'type': 'checkbutton',
         'default_checkbutton': False, 'tooltip': _("Миты автоматическики говорят по порядку, без вызова команд","Mitas response by order, without using commands")},
        {'label': _('Лимит речей нпс %', 'Limit NPC conversation'), 'key': 'CC_Limit_mod', 'type': 'entry',
         'default': 100, 'tooltip': _('Сколько от кол-ва персонажей может отклоняться повтор речей нпс',
                                      'How long NPC can talk ignoring player'),'depends_on':'MITA_DIALOGUE_OLD_ON'},
        {'label': _('ГеймМастер - экспериментальная функция', 'GameMaster is experimental feature'),
         'type': 'text'},
        {'label': _('ГеймМастер включен', 'GameMaster is on'), 'key': 'GM_ON', 'type': 'checkbutton',
         'default_checkbutton': False, 'tooltip': 'Помогает вести диалоги, в теории устраняя проблемы'},
        {'label': _('Задача ГМу', 'GM task'), 'key': 'GM_SMALL_PROMPT', 'type': 'textarea', 'default': ""},
        {'label': _('ГеймМастер встревает каждые', 'GameMaster intervene each'), 'key': 'GM_REPEAT',
         'type': 'entry',
         'default': 2,
         'tooltip': _('Пример: 3 Означает, что через каждые две фразы ГМ напишет свое сообщение',
                      'Example: 3 means that after 2 phrases GM will write his message')},
    ]
    
    create_settings_section(
        self,
        parent,
        _("Настройки диалогов и GameMaster", "Dialogue and GameMaster Settings"),
        dialogue_config
    )
    
    mod_config = [
        {'label': _('Меню действий', 'Action menu'), 'key': 'ACTION_MENU', 'type': 'checkbutton', 
        'default_checkbutton': True,
        'tooltip': _('Показывать меню действий в игре (Y)', 'Show action menu in game (Y)')},
        {'label': _('Меню выбора Мит', 'Mitas selection menu'), 'key': 'MITAS_MENU', 'type': 'checkbutton', 
        'default_checkbutton': False,
        'tooltip': _('Показывать меню выбора персонажей Мит в игре', 'Show Mitas character selection menu in game')},
        {'label': _('?????? ???????? ???? (????????)', 'World hierarchy tree (outdated)'), 'key': 'WORLD_HIERARCHY_TREE', 'type': 'checkbutton',
         'default_checkbutton': False,
         'tooltip': _('???????? ????? ????? ????? ??????? ???? ? ??????? ? ?????????? ?? ???. ??????? ????????.',
                      'The neural network will know which objects are in range and the distance to them. This feature is outdated.')},
        {'label': _('Игнорировать запросы', 'Ignore requests'), 'key': 'IGNORE_GAME_REQUESTS', 'type': 'checkbutton',
        'default_checkbutton': False,
        'tooltip': _('Блокировать запросы из игры', 'Block requests from the game'),
        'widget_name': 'IGNORE_GAME_REQUESTS'},
        {'label': _('Уровень блокировки', 'Blocking level'), 'key': 'GAME_BLOCK_LEVEL', 'type': 'combobox',
        'options': ['Idle events', 'All events'],
        'default': 'Idle events',
        'depends_on': 'IGNORE_GAME_REQUESTS',
        'tooltip': _('Idle events - блокирует запросы от таймера молчания, All events - блокирует все запросы с внутриигровых событий',
                    'Idle events - blocks idle timer requests, All events - blocks all in-game event requests')},
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
            'tooltip': _('Глобально разрешает запуск встроенных игр (шахматы, морской бой).',
                         'Globally allows launching built-in games (Chess, Sea Battle).')
        },
        {
            'label': _('Разрешить запуск игр при подключенном Unity', 'Allow games when Unity is connected'),
            'key': 'ALLOW_GAMES_WHEN_CONNECTED',
            'type': 'checkbutton',
            'default_checkbutton': False,
            'depends_on': 'ENABLE_GAMES',
            'tooltip': _('Если ВЫКЛ и Unity подключен к серверу, игры не будут запускаться.',
                         'If OFF and Unity client is connected, games will not be launched.')
        },
        {
            'label': _('Шахматы', 'Chess'),
            'key': 'ENABLE_GAME_CHESS',
            'type': 'checkbutton',
            'default_checkbutton': False,
            'depends_on': 'ENABLE_GAMES',
            'tooltip': _('Разрешить игру "Шахматы".', 'Allow "Chess" game.')
        },
        {
            'label': _('Морской бой', 'Sea Battle'),
            'key': 'ENABLE_GAME_SEABATTLE',
            'type': 'checkbutton',
            'default_checkbutton': False,
            'depends_on': 'ENABLE_GAMES',
            'tooltip': _('Разрешить игру "Морской бой".', 'Allow "Sea Battle" game.')
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
            'label': _('????????????? ??????? ?? ????', 'Beat-driven head bob sync'),
            'key': 'BEAT_SYNC_ENABLED',
            'type': 'checkbutton',
            'default_checkbutton': False,
            'tooltip': _('???? ????????, Unity ????? ??????????? ???? ????? ? Python ????? ?????????????.',
                         'If enabled, Unity will request track beats from Python before playback.')
        },
        {
            'label': _('????????????? beat-this', 'Auto-install beat-this'),
            'key': 'BEAT_SYNC_AUTO_INSTALL',
            'type': 'checkbutton',
            'default_checkbutton': True,
            'depends_on': 'BEAT_SYNC_ENABLED',
            'tooltip': _('???? ????? beat-this ?? ??????????, ?????????? ?????????? ????????????? ??? ?????? ???????.',
                         'If beat-this is not installed, try to install it automatically on first use.')
        },
        {
            'label': _('????????? ???????? ?????', 'Stream beats in chunks'),
            'key': 'BEAT_SYNC_STREAMING',
            'type': 'checkbutton',
            'default_checkbutton': True,
            'depends_on': 'BEAT_SYNC_ENABLED',
            'tooltip': _('???? ?????? ?????????, ???? ????? ????????? ??????? ?? ????? ?????????.',
                         'If analysis is slow, beats will be delivered in chunks while processing.')
        },
        {
            'label': _('?????? ????? (???)', 'Chunk size (sec)'),
            'key': 'BEAT_SYNC_CHUNK_SECONDS',
            'type': 'entry',
            'default': 8,
            'depends_on': 'BEAT_SYNC_ENABLED',
            'tooltip': _('?????????? 6-12 ??????. ?????? = ?????? ?????? ????.',
                         'Recommended 6-12 seconds. Smaller = earlier first beats.')
        },
        {
            'label': _('???. ??????????? ????', 'Min beat confidence'),
            'key': 'BEAT_SYNC_MIN_CONFIDENCE',
            'type': 'entry',
            'default': 0.2,
            'depends_on': 'BEAT_SYNC_ENABLED',
            'tooltip': _('????? ?????????? ?????? ????? (0.0 - 1.0).',
                         'Threshold to filter noisy beats (0.0 - 1.0).')
        },
    ]

    create_settings_section(
        self,
        parent,
        _('???-????????????? (Beat This)', 'Beat Sync (Beat This)'),
        beat_sync_config
    )

