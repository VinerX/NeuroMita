from utils import getTranslationVariant as _

def setup_game_master_controls(self, parent):
    # Основные настройки
    common_config = [
        {'label': _('Лимит речей нпс %', 'Limit NPC convesationg'), 'key': 'CC_Limit_mod', 'type': 'entry',
         'default': 100, 'tooltip': _('Сколько от кол-ва персонажей может отклоняться повтор речей нпс',
                                      'How long NPC can talk ignoring player')},
        {'label': _('ГеймМастер - экспериментальная функция', 'GameMaster is experimental feature'),
         'type': 'text'},
        {'label': _('ГеймМастер включен', 'GameMaster is on'), 'key': 'GM_ON', 'type': 'checkbutton',
         'default_checkbutton': False, 'tooltip': 'Помогает вести диалоги, в теории устраняя проблемы'},
        # {'label': _('ГеймМастер зачитывается', 'GameMaster write in game'), 'key': 'GM_READ', 'type': 'checkbutton',
        # 'default_checkbutton': False},
        # {'label': _('ГеймМастер озвучивает', 'GameMaster is voiced'), 'key': 'GM_VOICE', 'type': 'checkbutton',
        #  'default_checkbutton': False},
        {'label': _('Задача ГМу', 'GM task'), 'key': 'GM_SMALL_PROMPT', 'type': 'text', 'default': ""},
        {'label': _('ГеймМастер встревает каждые', 'GameMaster intervene each'), 'key': 'GM_REPEAT',
         'type': 'entry',
         'default': 2,
         'tooltip': _('Пример: 3 Означает, что через каждые две фразы ГМ напишет свое сообщение',
                      'Example: 3 means that after 2 phreses GM will write his message')},

    ]
    self.create_settings_section(parent,
                                 _("Настройки Мастера игры и Диалогов", "GameMaster and Dialogues settings"),
                                 common_config)
