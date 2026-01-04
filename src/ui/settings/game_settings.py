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
        {'label': _('Лимит речей нпс %', 'Limit NPC conversation'), 'key': 'CC_Limit_mod', 'type': 'entry',
         'default': 100, 'tooltip': _('Сколько от кол-ва персонажей может отклоняться повтор речей нпс',
                                      'How long NPC can talk ignoring player')},
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