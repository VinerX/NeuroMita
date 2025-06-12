import tkinter as tk
from utils import getTranslationVariant as _


def setup_mita_controls(self, parent):
    # Основные настройки
    mita_config = [
        {'label': _('Персонажи', 'Characters'), 'key': 'CHARACTER', 'type': 'combobox',
         'options': self.model.get_all_mitas(),
         'default': "Crazy"},

        {'label': _('Управление персонажем', 'Character Management'), 'type': 'text'},
        {'label': _('Очистить историю персонажа', 'Clear character history'), 'type': 'button',
         'command': self.clear_history},

        {'label': _('Открыть папку персонажа', 'Open character folder'), 'type': 'button',
         'command': self.open_character_folder},
        {'label': _('Открыть папку истории персонажа', 'Open character history folder'), 'type': 'button',
         'command': self.open_character_history_folder},

        {'label': _('Аккуратно!', 'Be careful!'), 'type': 'text'},
        {'label': _('Перекачать промпты', 'ReDownload prompts'), 'type': 'button',
         'command': self.reload_prompts},
        {'label': _("Очистить все истории", "Clear all histories"), 'type': 'button',
         'command': self.clear_history_all},

        {'label': _('Экспериментальные функции', 'Experimental features'), 'type': 'text'},
        {'label': _('Меню выбора Мит', 'Mita selection menu'), 'key': 'MITAS_MENU', 'type': 'checkbutton',
         'default_checkbutton': False},
        {'label': _('Меню эмоций Мит', 'Emotion menu'), 'key': 'EMOTION_MENU', 'type': 'checkbutton',
         'default_checkbutton': False},

        #  {'label': _('Миты в работе', 'Mitas in work'), 'key': 'TEST_MITAS', 'type': 'checkbutton',
        #   'default_checkbutton': False,'tooltip':_("Позволяет выбирать нестабильные версии Мит", "Allow to choose ustable Mita versions")}
    ]

    self.create_settings_section(parent, _("Настройки персонажей", "Characters settings"), mita_config)