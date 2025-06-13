import tkinter as tk
from utils import getTranslationVariant as _


def setup_chat_settings_controls(self, parent):
    """Создает секцию настроек специально для чата."""
    chat_settings_config = [
        {'label': _('Размер шрифта чата', 'Chat Font Size'), 'key': 'CHAT_FONT_SIZE', 'type': 'entry',
         'default': 12, 'validation': self.validate_positive_integer,
         'tooltip': _('Размер шрифта в окне чата.', 'Font size in the chat window.')},
        {'label': _('Показывать метки времени', 'Show Timestamps'), 'key': 'SHOW_CHAT_TIMESTAMPS',
         'type': 'checkbutton', 'default_checkbutton': False,
         'tooltip': _('Показывать метки времени рядом с сообщениями в чате.',
                      'Show timestamps next to messages in chat.')},
        #{'label': _('Макс. сообщений в истории', 'Max Messages in History'), 'key': 'MAX_CHAT_HISTORY_DISPLAY',
        # 'type': 'entry', 'default': 100, 'validation': self.validate_positive_integer,
         #'tooltip': _('Максимальное количество сообщений, отображаемых в окне чата.',
         #             'Maximum number of messages displayed in the chat window.')},
        {'label': _('Скрывать теги', 'Hide Tags'), 'key': 'HIDE_CHAT_TAGS',
         'type': 'checkbutton', 'default_checkbutton': False,
         'tooltip': _('Скрывать теги (<e>, <c>, <a>, [b], [i], [color]) в отображаемом тексте чата.',
                      'Hide tags (<e>, <c>, <a>, [b], [i], [color]) in the displayed chat text.')},
    ]

    self.create_settings_section(parent,
                                 _("Настройки чата", "Chat Settings"),
                                 chat_settings_config)