from ui.gui_templates import create_settings_section, create_section_header
from utils import getTranslationVariant as _

def setup_game_controls(self, parent):
    create_section_header(parent, _("РќР°СЃС‚СЂРѕР№РєРё РёРіСЂС‹", "Game Settings"))

    api_config = [
        {'label': _('РќР• РќРђР–РРњРђРўР¬!', 'Do not turn this on!'),
         'type': 'text'},
        {'label': _('РСЃРїРѕР»СЊР·РѕРІР°С‚СЊ РЅРѕРІС‹Р№ API', 'Use new API'), 'key': 'USE_NEW_API', 'type': 'checkbutton',
        'default_checkbutton': True,
        'tooltip': _('РСЃРїРѕР»СЊР·РѕРІР°С‚СЊ РЅРѕРІСѓСЋ СЃРёСЃС‚РµРјСѓ РїРµСЂРµРґР°С‡Рё РґР°РЅРЅС‹С… СЃ Р·Р°РґР°С‡Р°РјРё', 'Use new task-based data transfer system')},
    ]

    create_settings_section(
        self,
        parent,
        _("РќР°СЃС‚СЂРѕР№РєРё СЃРµСЂРІРµСЂР°", "Server settings"),
        api_config
    )
    
    dialogue_config = [
        {'label': _('Р”РёР°Р»РѕРіРё РјРёС‚ Р°РІС‚РѕРјР°С‚РёС‡РµСЃРєРё', 'Mitas\'s dialogues automatically'), 'key': 'MITA_DIALOGUE_AUTO', 'type': 'checkbutton',
         'default_checkbutton': False, 'tooltip': _("РњРёС‚С‹ Р°РІС‚РѕРјР°С‚РёС‡РµСЃРєРёРєРё РіРѕРІРѕСЂСЏС‚ РїРѕ РїРѕСЂСЏРґРєСѓ, Р±РµР· РІС‹Р·РѕРІР° РєРѕРјР°РЅРґ","Mitas response by order, without using commands")},
        {'label': _('Р›РёРјРёС‚ СЂРµС‡РµР№ РЅРїСЃ %', 'Limit NPC conversation'), 'key': 'CC_Limit_mod', 'type': 'entry',
         'default': 100, 'tooltip': _('РЎРєРѕР»СЊРєРѕ РѕС‚ РєРѕР»-РІР° РїРµСЂСЃРѕРЅР°Р¶РµР№ РјРѕР¶РµС‚ РѕС‚РєР»РѕРЅСЏС‚СЊСЃСЏ РїРѕРІС‚РѕСЂ СЂРµС‡РµР№ РЅРїСЃ',
                                      'How long NPC can talk ignoring player'),'depends_on':'MITA_DIALOGUE_OLD_ON'},
        {'label': _('Р“РµР№РјРњР°СЃС‚РµСЂ - СЌРєСЃРїРµСЂРёРјРµРЅС‚Р°Р»СЊРЅР°СЏ С„СѓРЅРєС†РёСЏ', 'GameMaster is experimental feature'),
         'type': 'text'},
        {'label': _('Р“РµР№РјРњР°СЃС‚РµСЂ РІРєР»СЋС‡РµРЅ', 'GameMaster is on'), 'key': 'GM_ON', 'type': 'checkbutton',
         'default_checkbutton': False, 'tooltip': 'РџРѕРјРѕРіР°РµС‚ РІРµСЃС‚Рё РґРёР°Р»РѕРіРё, РІ С‚РµРѕСЂРёРё СѓСЃС‚СЂР°РЅСЏСЏ РїСЂРѕР±Р»РµРјС‹'},
        {'label': _('Р—Р°РґР°С‡Р° Р“РњСѓ', 'GM task'), 'key': 'GM_SMALL_PROMPT', 'type': 'textarea', 'default': ""},
        {'label': _('Р“РµР№РјРњР°СЃС‚РµСЂ РІСЃС‚СЂРµРІР°РµС‚ РєР°Р¶РґС‹Рµ', 'GameMaster intervene each'), 'key': 'GM_REPEAT',
         'type': 'entry',
         'default': 2,
         'tooltip': _('РџСЂРёРјРµСЂ: 3 РћР·РЅР°С‡Р°РµС‚, С‡С‚Рѕ С‡РµСЂРµР· РєР°Р¶РґС‹Рµ РґРІРµ С„СЂР°Р·С‹ Р“Рњ РЅР°РїРёС€РµС‚ СЃРІРѕРµ СЃРѕРѕР±С‰РµРЅРёРµ',
                      'Example: 3 means that after 2 phrases GM will write his message')},
    ]
    
    create_settings_section(
        self,
        parent,
        _("РќР°СЃС‚СЂРѕР№РєРё РґРёР°Р»РѕРіРѕРІ Рё GameMaster", "Dialogue and GameMaster Settings"),
        dialogue_config
    )
    
    mod_config = [
        {'label': _('РњРµРЅСЋ РґРµР№СЃС‚РІРёР№', 'Action menu'), 'key': 'ACTION_MENU', 'type': 'checkbutton', 
        'default_checkbutton': True,
        'tooltip': _('РџРѕРєР°Р·С‹РІР°С‚СЊ РјРµРЅСЋ РґРµР№СЃС‚РІРёР№ РІ РёРіСЂРµ (Y)', 'Show action menu in game (Y)')},
        {'label': _('РњРµРЅСЋ РІС‹Р±РѕСЂР° РњРёС‚', 'Mitas selection menu'), 'key': 'MITAS_MENU', 'type': 'checkbutton', 
        'default_checkbutton': False,
        'tooltip': _('РџРѕРєР°Р·С‹РІР°С‚СЊ РјРµРЅСЋ РІС‹Р±РѕСЂР° РїРµСЂСЃРѕРЅР°Р¶РµР№ РњРёС‚ РІ РёРіСЂРµ', 'Show Mitas character selection menu in game')},
        {'label': _('Р”РµСЂРµРІРѕ РёРµСЂР°СЂС…РёРё РјРёСЂР° (СѓСЃС‚Р°СЂРµР»Рѕ)', 'World hierarchy tree (outdated)'), 'key': 'WORLD_HIERARCHY_TREE', 'type': 'checkbutton',
         'default_checkbutton': False,
         'tooltip': _('РќРµР№СЂРѕРЅРєР° Р±СѓРґРµС‚ Р·РЅР°С‚СЊ РєР°РєРёРµ РѕР±СЉРµРєС‚С‹ РµСЃС‚СЊ РІ СЂР°РґРёСѓСЃРµ Рё СЂР°СЃСЃС‚РѕСЏРЅРёРµ РґРѕ РЅРёС…. Р¤СѓРЅРєС†РёСЏ СѓСЃС‚Р°СЂРµР»Р°.',
                      'The neural network will know which objects are in range and the distance to them. This feature is outdated.')},
        {'label': _('РРіРЅРѕСЂРёСЂРѕРІР°С‚СЊ Р·Р°РїСЂРѕСЃС‹', 'Ignore requests'), 'key': 'IGNORE_GAME_REQUESTS', 'type': 'checkbutton',
        'default_checkbutton': False,
        'tooltip': _('Р‘Р»РѕРєРёСЂРѕРІР°С‚СЊ Р·Р°РїСЂРѕСЃС‹ РёР· РёРіСЂС‹', 'Block requests from the game'),
        'widget_name': 'IGNORE_GAME_REQUESTS'},
        {'label': _('РЈСЂРѕРІРµРЅСЊ Р±Р»РѕРєРёСЂРѕРІРєРё', 'Blocking level'), 'key': 'GAME_BLOCK_LEVEL', 'type': 'combobox',
        'options': ['Idle events', 'All events'],
        'default': 'Idle events',
        'depends_on': 'IGNORE_GAME_REQUESTS',
        'tooltip': _('Idle events - Р±Р»РѕРєРёСЂСѓРµС‚ Р·Р°РїСЂРѕСЃС‹ РѕС‚ С‚Р°Р№РјРµСЂР° РјРѕР»С‡Р°РЅРёСЏ, All events - Р±Р»РѕРєРёСЂСѓРµС‚ РІСЃРµ Р·Р°РїСЂРѕСЃС‹ СЃ РІРЅСѓС‚СЂРёРёРіСЂРѕРІС‹С… СЃРѕР±С‹С‚РёР№',
                    'Idle events - blocks idle timer requests, All events - blocks all in-game event requests')},
    ]
    
    create_settings_section(
        self,
        parent,
        _("РќР°СЃС‚СЂРѕР№РєРё РјРѕРґР°", "Mod Settings"),
        mod_config
    )

    games_config = [
        {
            'label': _('Р’РєР»СЋС‡РёС‚СЊ РёРіСЂС‹', 'Enable games'),
            'key': 'ENABLE_GAMES',
            'type': 'checkbutton',
            'default_checkbutton': False,
            'tooltip': _('Р“Р»РѕР±Р°Р»СЊРЅРѕ СЂР°Р·СЂРµС€Р°РµС‚ Р·Р°РїСѓСЃРє РІСЃС‚СЂРѕРµРЅРЅС‹С… РёРіСЂ (С€Р°С…РјР°С‚С‹, РјРѕСЂСЃРєРѕР№ Р±РѕР№).',
                         'Globally allows launching built-in games (Chess, Sea Battle).')
        },
        {
            'label': _('Р Р°Р·СЂРµС€РёС‚СЊ Р·Р°РїСѓСЃРє РёРіСЂ РїСЂРё РїРѕРґРєР»СЋС‡РµРЅРЅРѕРј Unity', 'Allow games when Unity is connected'),
            'key': 'ALLOW_GAMES_WHEN_CONNECTED',
            'type': 'checkbutton',
            'default_checkbutton': False,
            'depends_on': 'ENABLE_GAMES',
            'tooltip': _('Р•СЃР»Рё Р’Р«РљР› Рё Unity РїРѕРґРєР»СЋС‡РµРЅ Рє СЃРµСЂРІРµСЂСѓ, РёРіСЂС‹ РЅРµ Р±СѓРґСѓС‚ Р·Р°РїСѓСЃРєР°С‚СЊСЃСЏ.',
                         'If OFF and Unity client is connected, games will not be launched.')
        },
        {
            'label': _('РЁР°С…РјР°С‚С‹', 'Chess'),
            'key': 'ENABLE_GAME_CHESS',
            'type': 'checkbutton',
            'default_checkbutton': False,
            'depends_on': 'ENABLE_GAMES',
            'tooltip': _('Р Р°Р·СЂРµС€РёС‚СЊ РёРіСЂСѓ "РЁР°С…РјР°С‚С‹".', 'Allow "Chess" game.')
        },
        {
            'label': _('РњРѕСЂСЃРєРѕР№ Р±РѕР№', 'Sea Battle'),
            'key': 'ENABLE_GAME_SEABATTLE',
            'type': 'checkbutton',
            'default_checkbutton': False,
            'depends_on': 'ENABLE_GAMES',
            'tooltip': _('Р Р°Р·СЂРµС€РёС‚СЊ РёРіСЂСѓ "РњРѕСЂСЃРєРѕР№ Р±РѕР№".', 'Allow "Sea Battle" game.')
        },
    ]

    create_settings_section(
        self,
        parent,
        _("РРіСЂС‹", "Games"),
        games_config
    )

    beat_sync_config = [
        {
            'label': _('Синхронизация кивания по биту', 'Beat-driven head bob sync'),
            'key': 'BEAT_SYNC_ENABLED',
            'type': 'checkbutton',
            'default_checkbutton': False,
            'tooltip': _('Если включено, Unity будет запрашивать биты трека у Python перед проигрыванием.',
                         'If enabled, Unity will request track beats from Python before playback.')
        },
        {
            'label': _('Автоустановка beat-this', 'Auto-install beat-this'),
            'key': 'BEAT_SYNC_AUTO_INSTALL',
            'type': 'checkbutton',
            'default_checkbutton': True,
            'depends_on': 'BEAT_SYNC_ENABLED',
            'tooltip': _('Если пакет beat-this не установлен, попытаться установить автоматически при первом запуске.',
                         'If beat-this is not installed, try to install it automatically on first use.')
        },        {
            'label': _('Потоковая отправка битов', 'Stream beats in chunks'),
            'key': 'BEAT_SYNC_STREAMING',
            'type': 'checkbutton',
            'default_checkbutton': True,
            'depends_on': 'BEAT_SYNC_ENABLED',
            'tooltip': _('Если анализ медленный, биты будут приходить частями во время обработки.',
                         'If analysis is slow, beats will be delivered in chunks while processing.')
        },
        {
            'label': _('Размер чанка (сек)', 'Chunk size (sec)'),
            'key': 'BEAT_SYNC_CHUNK_SECONDS',
            'type': 'entry',
            'default': 8,
            'depends_on': 'BEAT_SYNC_ENABLED',
            'tooltip': _('Оптимально 6-12 секунд. Меньше = раньше первые биты.',
                         'Recommended 6-12 seconds. Smaller = earlier first beats.')
        },
        {
            'label': _('Мин. уверенность бита', 'Min beat confidence'),
            'key': 'BEAT_SYNC_MIN_CONFIDENCE',
            'type': 'entry',
            'default': 0.2,
            'depends_on': 'BEAT_SYNC_ENABLED',
            'tooltip': _('Порог фильтрации шумных битов (0.0 - 1.0).',
                         'Threshold to filter noisy beats (0.0 - 1.0).')
        },
    ]

    create_settings_section(
        self,
        parent,
        _('Бит-синхронизация (Beat This)', 'Beat Sync (Beat This)'),
        beat_sync_config
    )

