from ui.gui_templates import create_settings_section, create_section_header
from utils import getTranslationVariant as _

def setup_general_settings_controls(self, parent):
    create_section_header(parent, _("Основные настройки", "General Settings"))

    privacy_config = [
        {'label': _('Скрывать (приватные) данные', 'Hide (private) data'), 
         'key': 'HIDE_PRIVATE',
         'type': 'checkbutton', 
         'default_checkbutton': True},
    ]
    create_settings_section(
        self, 
        parent, 
        _("Приватность", "Privacy"), 
        privacy_config, 
        icon_name='fa5s.user-shield'
    )

    chat_settings_config = [
        {'label': _('Размер шрифта чата', 'Chat Font Size'), 'key': 'CHAT_FONT_SIZE', 'type': 'entry',
         'default': 12, 'validation': self.validate_positive_integer,
         'tooltip': _('Размер шрифта в окне чата.', 'Font size in the chat window.')},
        {'label': _('Показывать метки времени', 'Show Timestamps'), 'key': 'SHOW_CHAT_TIMESTAMPS',
         'type': 'checkbutton', 'default_checkbutton': False,
         'tooltip': _('Показывать метки времени рядом с сообщениями в чате.',
                      'Show timestamps next to messages in chat.')},
        {'label': _('Скрывать теги', 'Hide Tags'), 'key': 'HIDE_CHAT_TAGS',
         'type': 'checkbutton', 'default_checkbutton': True,
         'tooltip': _('Скрывать теги (<e>, <c>, <a>, [b], [i], [color]) в отображаемом тексте чата.',
                      'Hide tags (<e>, <c>, <a>, [b], [i], [color]) in the displayed chat text.')},

        {'label': _('Выводить мышление', 'Show thinking'), 'key': 'SHOW_THINK_IN_GUI',
         'type': 'checkbutton', 'default_checkbutton': True},
        {'label': _('Показывать structured output (📊)', 'Show structured output (📊)'), 'key': 'SHOW_STRUCTURED_IN_GUI',
         'type': 'checkbutton', 'default_checkbutton': False,
         'tooltip': _('Показывать кнопку 📊 на сообщениях с командами/эмоциями/памятью (дебаг).',
                      'Show 📊 button on messages with commands/emotions/memory (debug).')}
    ]

    create_settings_section(
        self, 
        parent,
        _("Настройки чата", "Chat Settings"),
        chat_settings_config,
        icon_name='fa5s.comments'
    )

    language_config = [
        {'label': 'Язык / Language', 'key': 'LANGUAGE', 'type': 'combobox',
         'options': ["RU", "EN"], 'default': "RU"},
        {'label': 'Перезапусти программу после смены!', 'type': 'text'},
        {'label': 'Restart program after change!', 'type': 'text'},
    ]

    create_settings_section(
        self, 
        parent,
        "Язык / Language",
        language_config,
        icon_name='fa5s.globe'
    )