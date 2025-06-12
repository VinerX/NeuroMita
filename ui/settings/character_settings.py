import os
import sys
import tkinter as tk
from tkinter import messagebox

from Logger import logger
from utils import getTranslationVariant as _
import subprocess

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
         'command': lambda : open_character_folder(self)},
        {'label': _('Открыть папку истории персонажа', 'Open character history folder'), 'type': 'button',
         'command': lambda : open_character_history_folder(self)},

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

def open_character_folder(self):
    """Открывает папку текущего персонажа в проводнике."""
    if self.model.current_character and self.model.current_character.char_id:
        character_name = self.model.current_character.char_id
        character_folder_path = os.path.join("Prompts", character_name)

        if os.path.exists(character_folder_path):
            try:
                if sys.platform == "win32":
                    os.startfile(character_folder_path)
                elif sys.platform == "darwin":  # macOS
                    subprocess.Popen(['open', character_folder_path])
                else:  # Linux и другие Unix-подобные
                    subprocess.Popen(['xdg-open', character_folder_path])
                logger.info(f"Открыта папка персонажа: {character_folder_path}")
            except Exception as e:
                logger.error(f"Не удалось открыть папку персонажа {character_folder_path}: {e}")
                messagebox.showerror(_("Ошибка", "Error"),
                                     _("Не удалось открыть папку персонажа.", "Failed to open character folder."),
                                     parent=self.root)
        else:
            messagebox.showwarning(_("Внимание", "Warning"),
                                   _("Папка персонажа не найдена: ",
                                     "Character folder not found: ") + character_folder_path,
                                   parent=self.root)
    else:
        messagebox.showinfo(_("Информация", "Information"),
                            _("Персонаж не выбран или его имя недоступно.",
                              "No character selected or its name is not available."),
                            parent=self.root)


def open_character_history_folder(self):
    """Открывает папку истории текущего персонажа в проводнике."""
    if self.model.current_character and self.model.current_character.char_id:
        character_name = self.model.current_character.char_id
        history_folder_path = os.path.join("Histories", character_name)

        if os.path.exists(history_folder_path):
            try:
                if sys.platform == "win32":
                    os.startfile(history_folder_path)
                elif sys.platform == "darwin":  # macOS
                    subprocess.Popen(['open', history_folder_path])
                else:  # Linux и другие Unix-подобные
                    subprocess.Popen(['xdg-open', history_folder_path])
                logger.info(f"Открыта папка истории персонажа: {history_folder_path}")
            except Exception as e:
                logger.error(f"Не удалось открыть папку истории персонажа {history_folder_path}: {e}")
                messagebox.showerror(_("Ошибка", "Error"),
                                     _("Не удалось открыть папку истории персонажа.",
                                       "Failed to open character history folder."),
                                     parent=self.root)
        else:
            messagebox.showwarning(_("Внимание", "Warning"),
                                   _("Папка истории персонажа не найдена: ",
                                     "Character history folder not found: ") + history_folder_path,
                                   parent=self.root)
    else:
        messagebox.showinfo(_("Информация", "Information"),
                            _("Персонаж не выбран или его имя недоступно.",
                              "No character selected or its name is not available."),
                            parent=self.root)
