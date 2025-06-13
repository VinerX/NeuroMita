import subprocess
import sys
import tkinter as tk
import tkinter.ttk as ttk
import os
import json
from tkinter import messagebox, filedialog

from utils import getTranslationVariant as _
from utils.prompt_catalogue_manager import (
    list_prompt_sets, read_info_json, write_info_json,
    copy_prompt_set, create_new_set, delete_prompt_set
)
from guiTemplates import CollapsibleSection # Предполагается, что CollapsibleSection находится в guiTemplates

def setup_prompt_catalogue_controls(self, parent):
    """
    Настраивает элементы управления для каталога промптов.
    """
    catalogue_path = "PromptsCatalogue" # Путь к каталогу промптов

    # Создаем сворачиваемую секцию
    prompt_catalogue_section = CollapsibleSection(parent, _("Каталог промптов", "Prompt Catalogue"))
    prompt_catalogue_section.pack(fill="x", padx=5, pady=2)

    # Фрейм для элементов управления каталогом
    catalogue_frame = prompt_catalogue_section.content_frame

    # Выбор набора промптов
    ttk.Label(catalogue_frame, text=_("Выберите набор промптов:", "Select prompt set:"), background="#2c2c2c", foreground="#ffffff", font=("Arial", 10)).pack(pady=2, anchor="w")

    # Frame for combobox and refresh button
    combobox_refresh_frame = tk.Frame(catalogue_frame, background="#2c2c2c") # New line
    combobox_refresh_frame.pack(fill="x", pady=2) # New line

    prompt_set_combobox = ttk.Combobox(combobox_refresh_frame, state="readonly", background="#1e1e1e", foreground="#ffffff", font=("Arial", 10)) # Modified line
    prompt_set_combobox.pack(side="left", fill="x", expand=True, padx=(0, 5)) # Modified line

    def update_prompt_set_combobox():
        sets = list_prompt_sets(catalogue_path)
        prompt_set_combobox['values'] = sets
        if sets:
            prompt_set_combobox.set(sets[0]) # Выбираем первый набор по умолчанию
            load_info_json(os.path.join(catalogue_path, sets[0]))
        else:
            prompt_set_combobox.set("")
            clear_info_json_fields()

    # Refresh button
    refresh_button = tk.Button(combobox_refresh_frame, text=_("Обновить", "Refresh"), command=update_prompt_set_combobox, bg="#8a2be2", fg="#ffffff", activebackground="#6a1bcb", activeforeground="#ffffff", relief=tk.RAISED, bd=2) # New line
    refresh_button.pack(side="left") # New line



    def on_prompt_set_selected(event):
        selected_set_name = prompt_set_combobox.get()
        if selected_set_name:
            set_path = os.path.join(catalogue_path, selected_set_name)
            load_info_json(set_path)


    prompt_set_combobox.bind("<<ComboboxSelected>>", on_prompt_set_selected)

    # Фрейм для кнопок управления каталогом
    button_frame = tk.Frame(catalogue_frame, background="#2c2c2c")
    button_frame.pack(fill="x", pady=5)

    # Кнопка "Заменить" (копировать в папку персонажа)
    def replace_prompt_set_action():
        selected_set_name = prompt_set_combobox.get()
        if not selected_set_name:
            messagebox.showwarning(_("Внимание", "Warning"), _("Набор промптов не выбран для замены.", "No prompt set selected for replacement."))
            return

        set_path = os.path.join(catalogue_path, selected_set_name)

        if self.model.current_character and self.model.current_character.char_id:
             character_prompts_path = os.path.join("Prompts", self.model.current_character.char_id)
             if copy_prompt_set(set_path, character_prompts_path):
                 messagebox.showinfo(_("Успех", "Success"), _("Набор промптов успешно скопирован.", "Prompt set copied successfully."))
                 # Перезагружаем данные персонажа
                 # Предполагается наличие метода reload_character_data в self.model.current_character
                 if hasattr(self.model.current_character, 'reload_character_data'):
                     self.model.current_character.reload_character_data()
                 else:
                     print("Warning: current_character does not have reload_character_data method.") # Для отладки
             else:
                 messagebox.showerror(_("Ошибка", "Error"), _("Не удалось скопировать набор промптов.", "Failed to copy prompt set."))
        else:
             messagebox.showwarning(_("Внимание", "Warning"), _("Персонаж не выбран. Не удалось скопировать набор промптов.", "No character selected. Failed to copy prompt set."))

    tk.Button(button_frame, text=_("Заменить", "Replace"), command=replace_prompt_set_action, bg="#8a2be2", fg="#ffffff", activebackground="#6a1bcb", activeforeground="#ffffff", relief=tk.RAISED, bd=2).pack(side="left", padx=2)


    # Кнопка "Создать новый набор"
    def create_new_set_action():
        if self.model.current_character and self.model.current_character.char_id:
            character = self.model.current_character
            if character.is_cartridge:
                character_name = "Cartridges"
            else:
                character_name = character.char_id
            prompts_path = os.path.join("Prompts", character_name)
            new_set_path = create_new_set(character_name, catalogue_path, prompts_path)
            if new_set_path:
                messagebox.showinfo(_("Успех", "Success"), _(f"Новый набор создан: {os.path.basename(new_set_path)}", f"New set created: {os.path.basename(new_set_path)}"))
                update_prompt_set_combobox()
                prompt_set_combobox.set(os.path.basename(new_set_path)) # Выбираем новый набор
                load_info_json(new_set_path)
            else:
                 messagebox.showerror(_("Ошибка", "Error"), _("Не удалось создать новый набор промптов.", "Failed to create new prompt set."))
        else:
            messagebox.showwarning(_("Внимание", "Warning"), _("Персонаж не выбран. Не удалось создать новый набор промптов.", "No character selected. Failed to create new prompt set."))


    tk.Button(button_frame, text=_("Создать новый набор", "Create New Set"), command=create_new_set_action, bg="#8a2be2", fg="#ffffff", activebackground="#6a1bcb", activeforeground="#ffffff", relief=tk.RAISED, bd=2).pack(side="left", padx=2)

    # Кнопка "Открыть папку набора"
    def open_set_folder_action():
        selected_set_name = prompt_set_combobox.get()
        if selected_set_name:
            set_path = os.path.join(catalogue_path, selected_set_name)
            if os.path.exists(set_path):
                try:
                    if sys.platform == "win32":
                        os.startfile(set_path)
                    elif sys.platform == "darwin":  # macOS
                        subprocess.Popen(['open', set_path])
                    else:  # Linux и другие Unix-подобные
                        subprocess.Popen(['xdg-open', set_path])
                except Exception as e:
                    messagebox.showerror(_("Ошибка", "Error"), _(f"Не удалось открыть папку: {e}", f"Failed to open folder: {e}"))
            else:
                messagebox.showwarning(_("Внимание", "Warning"), _("Папка набора не найдена.", "Set folder not found."))
        else:
            messagebox.showwarning(_("Внимание", "Warning"), _("Набор промптов не выбран.", "No prompt set selected."))

    tk.Button(button_frame, text=_("Открыть папку набора", "Open Set Folder"), command=open_set_folder_action, bg="#8a2be2", fg="#ffffff", activebackground="#6a1bcb", activeforeground="#ffffff", relief=tk.RAISED, bd=2).pack(side="left", padx=2)

    # Кнопка "Удалить набор"
    def delete_set_action():
        selected_set_name = prompt_set_combobox.get()
        if selected_set_name:
            set_path = os.path.join(catalogue_path, selected_set_name)
            if delete_prompt_set(set_path):
                messagebox.showinfo(_("Успех", "Success"), _("Набор промптов успешно удален.", "Prompt set deleted successfully."))
                update_prompt_set_combobox()
            # delete_prompt_set уже содержит messagebox для ошибок/отмены
        else:
            messagebox.showwarning(_("Внимание", "Warning"), _("Набор промптов не выбран.", "No prompt set selected."))

    tk.Button(button_frame, text=_("Удалить набор", "Delete Set"), command=delete_set_action, bg="#8a2be2", fg="#ffffff", activebackground="#6a1bcb", activeforeground="#ffffff", relief=tk.RAISED, bd=2).pack(side="left", padx=2)

    # --- GUI для редактирования info.json ---
    info_json_frame = tk.LabelFrame(catalogue_frame, text=_("Информация о наборе", "Set Information"), background="#2c2c2c", foreground="#ffffff")
    info_json_frame.pack(fill="x", pady=5, padx=2)

    self.info_json_entries = {} # Словарь для хранения Entry виджетов

    def create_info_field(parent_frame, label_text, key):
        frame = tk.Frame(parent_frame)
        frame.pack(fill="x", pady=1)
        tk.Label(frame, text=label_text, width=15, background="#2c2c2c", foreground="#ffffff", font=("Arial", 10)).pack(side="left", padx=2)
        entry = tk.Entry(frame, background="#1e1e1e", foreground="#ffffff", font=("Arial", 10))
        entry.pack(side="left", fill="x", expand=True, padx=2)
        self.info_json_entries[key] = entry
        return entry

    create_info_field(info_json_frame, _("Папка:", "Folder:"), "folder") # New line
    create_info_field(info_json_frame, _("Персонаж:", "Character:"), "character")
    create_info_field(info_json_frame, _("Автор:", "Author:"), "author")
    create_info_field(info_json_frame, _("Версия:", "Version:"), "version")

    # Поле для описания (может быть Text widget для многострочности, но пока используем Entry)
    create_info_field(info_json_frame, _("Описание:", "Description:"), "description")

    # Кнопка для сохранения info.json
    def save_info_json_action():
        selected_set_name = prompt_set_combobox.get()
        if selected_set_name:
            set_path = os.path.join(catalogue_path, selected_set_name)
            info_data = read_info_json(set_path) # Читаем текущие данные, чтобы сохранить дополнительные параметры
            if info_data is None: # Handle read error
                 info_data = {}

            # Обновляем основные поля
            for key, entry in self.info_json_entries.items():
                info_data[key] = entry.get()

            # Дополнительные параметры пока не редактируются через GUI, но сохраняются
            # Если нужно редактирование доп. параметров, потребуется более сложный GUI

            if write_info_json(set_path, info_data):
                messagebox.showinfo(_("Успех", "Success"), _("Информация о наборе сохранена.", "Set information saved."))
            # write_info_json уже содержит messagebox для ошибок
        else:
            messagebox.showwarning(_("Внимание", "Warning"), _("Набор промптов не выбран для сохранения.", "No prompt set selected for saving."))

    tk.Button(info_json_frame, text=_("Сохранить информацию", "Save Information"), command=save_info_json_action, bg="#8a2be2", fg="#ffffff", activebackground="#6a1bcb", activeforeground="#ffffff", relief=tk.RAISED, bd=2).pack(pady=5)


    def load_info_json(set_path):
        """Загружает данные из info.json и заполняет поля GUI."""
        info_data = read_info_json(set_path)
        if info_data:
            for key, entry in self.info_json_entries.items():
                entry.delete(0, tk.END)
                if key in info_data:
                    entry.insert(0, info_data[key])
                else:
                    entry.insert(0, "") # Очищаем поле, если ключа нет
        else:
            clear_info_json_fields()

    def clear_info_json_fields():
         """Очищает все поля info.json GUI."""
         for entry in self.info_json_entries.values():
             entry.delete(0, tk.END)


    # Инициализация: заполняем комбобокс при запуске
    update_prompt_set_combobox()

# Примечание: Эта функция setup_prompt_catalogue_controls должна быть вызвана из gui.py
# в соответствующем месте, например, в методе setup_right_frame.
# Также необходимо убедиться, что self.model.current_character и self.model.characters доступны.