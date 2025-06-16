import tkinter.simpledialog as simpledialog
import tkinter.messagebox as messagebox
import tkinter as tk
from utils import _
def setup_api_controls(self, parent):
    # Основные настройки
    common_config = [
        {'label': _('Ссылка', 'URL'), 'key': 'NM_API_URL', 'type': 'entry'},
        {'label': _('Модель', 'Model'), 'key': 'NM_API_MODEL', 'type': 'entry'},
        {'label': _('Ключ', 'Key'), 'key': 'NM_API_KEY', 'type': 'entry', 'default': ""},
        {'label': _('Резервные ключи', 'Reserve keys'), 'key': 'NM_API_KEY_RES', 'type': 'text',
         'hide': bool(self.settings.get("HIDE_PRIVATE")), 'default': ""},
        {'label': _('Через Request', 'Using Request'), 'key': 'NM_API_REQ', 'type': 'checkbutton'},
        {'label': _('Гемини для ProxiAPI', 'Gemini for ProxiAPI'), 'key': 'GEMINI_CASE', 'type': 'checkbutton',
         'default_checkbutton': False}
    ]
    self.api_controls = self.create_settings_section(parent,
                                 _("Настройки API", "API settings"),
                                 common_config)

def setup_api_config_controls(self, parent):
    # API Config settings
    api_config = [
        {'label': _('Активная конфигурация', 'Active configuration'), 'key': 'active_api_config', 'type': 'combobox',
         'values': get_api_config_names(self), 'command': lambda : on_api_config_changed(self)},
    ]
    api_config_section = self.create_settings_section(parent,
                                 _("Конфигурации API", "API Configurations"),
                                 api_config)

    # Кнопки управления конфигурациями
    button_frame = tk.Frame(api_config_section.content_frame)
    button_frame.pack(fill=tk.X, pady=5)


    create_button = tk.Button(button_frame, text=_("Создать новую", "Create new"), command=lambda : create_api_config(self))
    create_button.pack(side=tk.LEFT, padx=5)

    save_button = tk.Button(button_frame, text=_("Сохранить текущую", "Save current"), command= lambda :save_api_config(self))
    save_button.pack(side=tk.LEFT, padx=5)

    delete_button = tk.Button(button_frame, text=_("Удалить текущую", "Delete current"), command=lambda :delete_api_config(self))
    delete_button.pack(side=tk.LEFT, padx=5)

def get_api_config_names(self):
    # Get API config names from APIConfigManager
    if hasattr(self, 'api_config_manager'):
        self.api_config_manager.load_configs()
        return list(self.api_config_manager.configs.keys())
    else:
        return []

def create_api_config(self):
    # Открывает диалог для ввода имени новой конфигурации.
    name = simpledialog.askstring(_("Создать конфигурацию", "Create configuration"), _("Имя конфигурации", "Configuration name"))
    if name:
        self.api_config_manager.create_config(name)
        self.update_api_config_combobox()

def save_api_config(self):
    # Сохраняет текущие значения полей API в активную конфигурацию.
    active_config_name = self.api_config_manager.get_active_config()
    config = self.api_config_manager.load_config(active_config_name)
    if config:
        config["NM_API_URL"] = self.settings.get("NM_API_URL")
        config["NM_API_MODEL"] = self.settings.get("NM_API_MODEL")
        config["NM_API_KEY"] = self.settings.get("NM_API_KEY")
        config["NM_API_KEY_RES"] = self.settings.get("NM_API_KEY_RES")
        config["NM_API_REQ"] = self.settings.get("NM_API_REQ")
        config["GEMINI_CASE"] = self.settings.get("GEMINI_CASE")
        config["gpt4free"] = self.settings.get("gpt4free")
        config["gpt4free_model"] = self.settings.get("gpt4free_model")
        self.api_config_manager.save_config(active_config_name, config)
    else:
        messagebox.showerror(_("Ошибка", "Error"), _("Активная конфигурация не найдена", "Active configuration not found"))

def delete_api_config(self):
    # Удаляет выбранную конфигурацию (с подтверждением).
    active_config_name = self.api_config_manager.get_active_config()
    if active_config_name == "default":
        messagebox.showerror(_("Ошибка", "Error"), _("Нельзя удалить конфигурацию по умолчанию", "Cannot delete default configuration"))
        return
    if messagebox.askyesno(_("Удалить конфигурацию", "Delete configuration"), _("Вы уверены, что хотите удалить конфигурацию", "Are you sure you want to delete configuration") + f" '{active_config_name}'?"):
        self.api_config_manager.delete_config(active_config_name)
        self.update_api_config_combobox()

def update_api_config_combobox(self):
    # Обновляет список конфигураций в выпадающем списке.
    if hasattr(self, 'api_config_controls') and 'active_api_config' in self.api_config_controls:
        self.api_config_controls['active_api_config']['values'] = self.get_api_config_names()

def on_api_config_changed(self, event=None):
    # Загружает значения из выбранной конфигурации и устанавливает их в соответствующие поля.
    active_config_name = self.api_config_manager.get_active_config()
    config = self.api_config_manager.load_config(active_config_name)
    if config:
        self.settings.set("NM_API_URL", config.get("NM_API_URL", ""))
        self.settings.set("NM_API_MODEL", config.get("NM_API_MODEL", ""))
        self.settings.set("NM_API_KEY", config.get("NM_API_KEY", ""))
        self.settings.set("NM_API_KEY_RES", config.get("NM_API_KEY_RES", ""))
        self.settings.set("NM_API_REQ", config.get("NM_API_REQ", False))
        self.settings.set("GEMINI_CASE", config.get("GEMINI_CASE", False))
        self.settings.set("gpt4free", config.get("gpt4free", True))
        self.settings.set("gpt4free_model", config.get("gpt4free_model", ""))
        # Обновляем значения полей в интерфейсе
        self.update_api_controls()
    else:
        messagebox.showerror(_("Ошибка", "Error"), _("Активная конфигурация не найдена", "Active configuration not found"))

def update_api_controls(self):
    # Обновляет значения полей в интерфейсе
    if hasattr(self, 'api_controls'):
        for key, control in self.api_controls.items():
            if control['type'] == 'entry':
                control['widget'].delete(0, tk.END)
                control['widget'].insert(0, self.settings.get(key, ""))
            elif control['type'] == 'checkbutton':
                control['variable'].set(self.settings.get(key, False))

def setup_ui(self, parent):
    self.setup_api_controls(parent)
    self.setup_api_config_controls(parent)