import asyncio
import os
import sys
import tkinter as tk
from tkinter import messagebox, ttk

from guiTemplates import find_widget_child_by_type
from ui.settings.prompt_catalogue_settings import list_prompt_sets

from utils.prompt_catalogue_manager import copy_prompt_set, get_prompt_catalogue_folder_name

from Logger import logger
from utils import getTranslationVariant as _
import subprocess


def setup_mita_controls(self, parent):
    default_prompt_pack = self.settings.get("PROMPT_SET", None)

    # Основные настройки
    mita_config = [
        {'label': _('Персонажи', 'Characters'), 'key': 'CHARACTER', 'type': 'combobox',
         'options': self.model.get_all_mitas(),
         'default': "Crazy",
         'widget_name':"Characters_combobox",
         'command': lambda : change_character_actions(self)},
        {'label': _('Набор промтов', 'Prompt Set'), 'key': 'PROMPT_SET', 'type': 'combobox',
         'options': list_prompt_sets("PromptsCatalogue", self.model.current_character.char_id),
         'default': _("Выберите", "Choose"),  # default_prompt_pack,
         'widget_name': 'prompt_pack'},


        {'label': _('Управление персонажем', 'Character Management'), 'type': 'text'},


        {'label': _('Открыть папку персонажа', 'Open character folder'), 'type': 'button',
         'command': lambda: open_character_folder(self)},
        {'label': _('Открыть папку истории персонажа', 'Open character history folder'), 'type': 'button',
         'command': lambda: open_character_history_folder(self)},

        {'label': _('Аккуратно!', 'Be careful!'), 'type': 'text'},
        {'label': _('Очистить историю персонажа', 'Clear character history'), 'type': 'button',
         'command': lambda: clear_history(self)},
        {'label': _('Перекачать промпты', 'ReDownload prompts'), 'type': 'button',
         'command': lambda: reload_prompts(self)},
        {'label': _("Очистить все истории", "Clear all histories"), 'type': 'button',
         'command': lambda: clear_history_all(self)},

        {'label': _('Экспериментальные функции', 'Experimental features'), 'type': 'text'},
        {'label': _('Меню выбора Мит', 'Mita selection menu'), 'key': 'MITAS_MENU', 'type': 'checkbutton',
         'default_checkbutton': False},
        {'label': _('Меню эмоций Мит', 'Emotion menu'), 'key': 'EMOTION_MENU', 'type': 'checkbutton',
                 'default_checkbutton': False},


    ]

    section = self.create_settings_section(parent, _("Настройки персонажей", "Characters settings"), mita_config)

    # find comboboxes
    character_combobox = find_widget_child_by_type(section, "Characters_combobox", ttk.Combobox)
    prompt_pack_combobox = find_widget_child_by_type(section, "prompt_pack", ttk.Combobox)

    self.character_prompt_pack_combobox = prompt_pack_combobox
    self.character_combobox = character_combobox

    if prompt_pack_combobox:
        prompt_pack_combobox.bind("<<ComboboxSelected>>", lambda e: apply_prompt_set(self))
        # Set default value

    #if character_combobox:
     #   character_combobox.bind("<<ComboboxSelected>>", lambda e: [,self.settings.save()])

    change_character_actions(self,self.settings.get("CHARACTER", None))

def set_default_prompt_pack(self, combobox):
    character_name = self.character_combobox.get()
    character_prompts_path = os.path.join("Prompts", character_name)

    folder_name = get_prompt_catalogue_folder_name(character_prompts_path)
    combobox.set(folder_name)
    
def change_character_actions(self,character = None):
    """Обновляет список наборов промтов в combobox."""
    if character:
        selected_character = character
    else:
        selected_character = self.character_combobox.get()

    self.model.current_character_to_change = selected_character
    self.model.check_change_current_character()

    if not selected_character:
        messagebox.showwarning(_("Внимание", "Warning"), _("Персонаж не выбран.", "No character selected."))
        return

    if not selected_character:
        messagebox.showwarning(_("Внимание", "Warning"), _("Не найден char_id для выбранного персонажа.", "No char_id found for selected character."))
        return

    # Обновляем список опций для combobox'а
    if self.character_prompt_pack_combobox:
        new_options = list_prompt_sets("PromptsCatalogue", selected_character)
        self.character_prompt_pack_combobox['values'] = new_options
        # Optionally, reset the selected value
        set_default_prompt_pack(self,self.character_prompt_pack_combobox)

def apply_prompt_set(self):
    """Применяет выбранный набор промтов к текущему персонажу."""
    chat_to = self.character_prompt_pack_combobox.get()
    char_from = self.character_combobox.get()
    if not chat_to:
        messagebox.showwarning(_("Внимание", "Warning"), _("Набор промптов не выбран.", "No prompt set selected."))
        return

    # Show confirmation dialog
    confirm = messagebox.askokcancel(
        _("Подтверждение", "Confirmation"),
        _("Применить набор промтов?", "Apply prompt set?"),
        icon='warning', parent=self.root
    )
    if not confirm:
        # Restore previous value
        set_default_prompt_pack(self,self.character_prompt_pack_combobox)
        return

    catalogue_path = "PromptsCatalogue"
    set_path = os.path.join(catalogue_path, chat_to)

    if char_from:
        character_prompts_path = os.path.join("Prompts", char_from)
        if copy_prompt_set(set_path, character_prompts_path):
            messagebox.showinfo(_("Успех", "Success"), _("Набор промптов успешно применен.", "Prompt set applied successfully."))
            # Перезагружаем данные персонажа
            if hasattr(self.model.current_character, 'reload_character_data'):
                self.model.current_character.reload_character_data()
            else:
                print("Warning: current_character does not have reload_character_data method.")  # Для отладки
        else:
            messagebox.showerror(_("Ошибка", "Error"), _("Не удалось применить набор промтов.", "Failed to apply prompt set."))
    else:
        messagebox.showwarning(_("Внимание", "Warning"), _("Персонаж не выбран.", "No character selected."))


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


def clear_history(self):
    self.model.current_character.clear_history()
    self.clear_chat_display()
    self.update_debug_info()


def clear_history_all(self):
    for character in self.model.characters.values():
        character.clear_history()
    self.clear_chat_display()
    self.update_debug_info()


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


def reload_prompts(self):
    """Скачивает свежие промпты с GitHub и перезагружает их для текущего персонажа."""
    # Запускаем асинхронную задачу через event loop
    #тут делаем запрос подверждение
    confirm = messagebox.askokcancel(
        _("Подтверждение", "Confirmation"),
        _("Это удалит текущие промпты! Продолжить?", "This will delete the current prompts! Continue?"),
        icon='warning', parent=self.root
    )
    if not confirm:
        return
    if confirm:
        # Показать индикатор загрузки
        self._show_loading_popup(_("Загрузка промптов...", "Downloading prompts..."))
        if self.loop and self.loop.is_running():
            asyncio.run_coroutine_threadsafe(self.async_reload_prompts(), self.loop)
        else:
            logger.error("Цикл событий asyncio не запущен. Невозможно выполнить асинхронную загрузку промптов.")
            messagebox.showerror(
                _("Ошибка", "Error"),
                _("Не удалось запустить асинхронную загрузку промптов.",
                  "Failed to start asynchronous prompt download.")
            )


async def async_reload_prompts(self):
    try:
        from utils.prompt_downloader import PromptDownloader
        downloader = PromptDownloader()

        success = await self.loop.run_in_executor(None, downloader.download_and_replace_prompts)

        if success:
            character = self.model.characters.get(self.model.current_character_to_change)
            if character:
                await self.loop.run_in_executor(None, character.reload_prompts)
            else:
                logger.error("Персонаж для перезагрузки не найден")

            self._close_loading_popup()
            messagebox.showinfo(
                _("Успешно", "Success"),
                _("Промпты успешно скачаны и перезагружены.", "Prompts successfully downloaded and reloaded.")
            )
        else:
            messagebox.showerror(
                _("Ошибка", "Error"),
                _("Не удалось скачать промпты с GitHub. Проверьте подключение к интернету.",
                  "Failed to download prompts from GitHub. Check your internet connection.")
            )
    except Exception as e:
        logger.error(f"Ошибка при обновлении промптов: {e}")
        messagebox.showerror(
            _("Ошибка", "Error"),
            _("Не удалось обновить промпты.", "Failed to update prompts.")
        )
