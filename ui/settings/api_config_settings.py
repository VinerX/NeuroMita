import tkinter as tk
from tkinter import ttk

import guiTemplates
from SettingsManager import CollapsibleSection
from ui.settings.APIConfigManager import APIConfigManager
from tkinter import simpledialog, messagebox
from utils import getTranslationVariant as _

def setup_api_config_controls(self, parent):
    api_config = [
        {'label': _('Выбрать конфигурацию', 'Select configuration'), 'key': 'API_CONFIG', 'type': 'combobox',
         'options': list(self.api_config_manager.get_config_names()),
         'command': lambda : on_api_config_selected(self)},
        {'label': _('Создать новую конфигурацию', 'Create new configuration'), 'key': 'CREATE_API_CONFIG',
         'type': 'button', 'command': lambda : create_api_config(self)},
        {'label': _('Сохранить текущую конфигурацию', 'Save current configuration'), 'key': 'SAVE_API_CONFIG',
         'type': 'button', 'command': lambda : save_api_config(self)},
        {'label': _('Удалить текущую конфигурацию', 'Delete current configuration'), 'key': 'DELETE_API_CONFIG',
         'type': 'button', 'command': lambda : delete_api_config(self)},
    ]

    section = self.create_settings_section(parent, _("Настройки конфигураций API", "API Configuration Settings"), api_config)

    self.api_config_combobox = guiTemplates.find_widget_child_by_type(section,"API_CONFIG",ttk.Combobox)

def create_api_config(self):
    new_config_name = simpledialog.askstring(_("Новая конфигурация API", "New API Configuration"),
                                             _("Введите имя для новой конфигурации:", "Enter a name for the new configuration:"),
                                             parent=self.master)
    if new_config_name:
        if self.api_config_manager.create_config(new_config_name, self._get_current_api_settings()):
            messagebox.showinfo(_("Успех", "Success"),
                                _(f"Конфигурация '{new_config_name}' успешно создана.",
                                  f"Configuration '{new_config_name}' created successfully."))
            self.update_api_config_combobox()
            self.api_config_manager.set_active_config(new_config_name)
            self.load_api_settings()
        else:
            messagebox.showerror(_("Ошибка", "Error"),
                                 _("Конфигурация с таким именем уже существует.",
                                   "A configuration with this name already exists."))

def save_api_config(self):
    active_config_name = self.api_config_manager.active_config_name
    if active_config_name:
        current_settings = self._get_current_api_settings()
        if self.api_config_manager.save_config(active_config_name, current_settings):
            messagebox.showinfo(_("Успех", "Success"),
                                _(f"Конфигурация '{active_config_name}' успешно сохранена.",
                                  f"Configuration '{active_config_name}' saved successfully."))
        else:
            messagebox.showerror(_("Ошибка", "Error"),
                                 _("Не удалось сохранить конфигурацию.", "Failed to save configuration."))
    else:
        messagebox.showwarning(_("Предупреждение", "Warning"),
                               _("Нет активной конфигурации для сохранения.", "No active configuration to save."))

def delete_api_config(self):
    active_config_name = self.api_config_manager.active_config_name
    if active_config_name == self.api_config_manager.DEFAULT_CONFIG_FILE.replace(".json", ""):
        messagebox.showwarning(_("Предупреждение", "Warning"),
                               _("Невозможно удалить конфигурацию по умолчанию.",
                                 "Cannot delete the default configuration."))
        return

    if active_config_name and messagebox.askyesno(_("Удалить конфигурацию", "Delete Configuration"),
                                                  _(f"Вы уверены, что хотите удалить конфигурацию '{active_config_name}'?",
                                                    f"Are you sure you want to delete configuration '{active_config_name}'?")):
        if self.api_config_manager.delete_config(active_config_name):
            messagebox.showinfo(_("Успех", "Success"),
                                _(f"Конфигурация '{active_config_name}' успешно удалена.",
                                  f"Configuration '{active_config_name}' deleted successfully."))
            self.update_api_config_combobox()
            self.load_api_settings() # Загрузить новую активную конфигурацию
        else:
            messagebox.showerror(_("Ошибка", "Error"),
                                 _("Не удалось удалить конфигурацию.", "Failed to delete configuration."))
    elif not active_config_name:
        messagebox.showwarning(_("Предупреждение", "Warning"),
                               _("Нет активной конфигурации для удаления.", "No active configuration to delete."))

def on_api_config_selected(self, event=None):
    selected_config_name = self.api_config_combobox.get()
    if selected_config_name:
        self.api_config_manager.set_active_config(selected_config_name)
        self.load_api_settings()

def update_api_config_combobox(self):
    self.api_config_combobox['values'] = list(self.api_config_manager.get_config_names())
    if self.api_config_manager.active_config_name:
        self.api_config_combobox.set(self.api_config_manager.active_config_name)
    else:
        self.api_config_combobox.set("") # Очистить, если нет активной

def _get_current_api_settings(self):
    # Собирает текущие значения полей API из GUI
    settings = {
        "name": self.api_config_manager.active_config_name,
        "NM_API_KEY": self.settings.get('NM_API_KEY', ''),
        "NM_API_URL": self.settings.get('NM_API_URL', ''),
        "NM_API_MODEL": self.settings.get('NM_API_MODEL', ''),
        "NM_API_REQ": self.settings.get('NM_API_REQ', False),
        "GEMINI_CASE": self.settings.get('GEMINI_CASE', False),
        "gpt4free": self.settings.get('gpt4free', True),
        "gpt4free_model": self.settings.get('gpt4free_model', ''),
        "SEPARATE_PROMPTS": self.settings.get('SEPARATE_PROMPTS', True),
        "MODEL_MESSAGE_LIMIT": self.settings.get('MODEL_MESSAGE_LIMIT', 40),
        "GPT4FREE_LAST_ATTEMPT": self.settings.get('GPT4FREE_LAST_ATTEMPT', False),
        "MODEL_MESSAGE_ATTEMPTS_COUNT": self.settings.get('MODEL_MESSAGE_ATTEMPTS_COUNT', 3),
        "MODEL_MESSAGE_ATTEMPTS_TIME": self.settings.get('MODEL_MESSAGE_ATTEMPTS_TIME', 0.20),
        "ENABLE_STREAMING": self.settings.get('ENABLE_STREAMING', False),
        "TEXT_WAIT_TIME": self.settings.get('TEXT_WAIT_TIME', 40),
        "VOICE_WAIT_TIME": self.settings.get('VOICE_WAIT_TIME', 40),
        "USE_MODEL_MAX_RESPONSE_TOKENS": self.settings.get('USE_MODEL_MAX_RESPONSE_TOKENS', True),
        "MODEL_MAX_RESPONSE_TOKENS": self.settings.get('MODEL_MAX_RESPONSE_TOKENS', 2500),
        "MODEL_TEMPERATURE": self.settings.get('MODEL_TEMPERATURE', 0.5),
        "USE_MODEL_TOP_K": self.settings.get('USE_MODEL_TOP_K', True),
        "MODEL_TOP_K": self.settings.get('MODEL_TOP_K', 0),
        "USE_MODEL_TOP_P": self.settings.get('USE_MODEL_TOP_P', True),
        "MODEL_TOP_P": self.settings.get('MODEL_TOP_P', 1.0),
        "USE_MODEL_THINKING_BUDGET": self.settings.get('USE_MODEL_THINKING_BUDGET', False),
        "MODEL_THINKING_BUDGET": self.settings.get('MODEL_THINKING_BUDGET', 0.0),
        "USE_MODEL_PRESENCE_PENALTY": self.settings.get('USE_MODEL_PRESENCE_PENALTY', False),
        "MODEL_PRESENCE_PENALTY": self.settings.get('MODEL_PRESENCE_PENALTY', 0.0),
        "USE_MODEL_FREQUENCY_PENALTY": self.settings.get('USE_MODEL_FREQUENCY_PENALTY', False),
        "MODEL_FREQUENCY_PENALTY": self.settings.get('MODEL_FREQUENCY_PENALTY', 0.0),
        "USE_MODEL_LOG_PROBABILITY": self.settings.get('USE_MODEL_LOG_PROBABILITY', False),
        "MODEL_LOG_PROBABILITY": self.settings.get('MODEL_LOG_PROBABILITY', 0.0),
    }
    return settings