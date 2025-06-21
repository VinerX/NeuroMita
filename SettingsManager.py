import base64
import json
import os

import tkinter as tk
from tkinter import ttk

from Logger import logger
from tkinter import messagebox

import json
import os

class APIConfigManager:
    def __init__(self, config_dir="Settings/API_Configs/", default_config="default.json"):
        self.config_dir = config_dir
        self.default_config = default_config
        self.active_config = None
        self.configs = self.load_configs()

    def load_configs(self):
        configs = {}
        if not os.path.exists(self.config_dir):
            os.makedirs(self.config_dir)
        for filename in os.listdir(self.config_dir):
            if filename.endswith(".json"):
                config_name = filename[:-5]
                try:
                    with open(os.path.join(self.config_dir, filename), "r", encoding="utf-8") as f:
                        configs[config_name] = json.load(f)
                except Exception as e:
                    print(f"Error loading config {filename}: {e}")
        return configs

    def load_config(self, config_name):
        if config_name in self.configs:
            self.active_config = config_name
            return self.configs[config_name]
        else:
            return None

    def save_config(self, config_name, config_data):
        self.configs[config_name] = config_data
        filepath = os.path.join(self.config_dir, f"{config_name}.json")
        try:
            with open(filepath, "w", encoding="utf-8") as f:
                json.dump(config_data, f, indent=2, ensure_ascii=False)
            return True
        except Exception as e:
            print(f"Error saving config {config_name}: {e}")
            return False

    def create_config(self, config_name):
        if config_name in self.configs:
            return False
        else:
            # Копируем значения из текущей активной конфигурации или из default
            if self.active_config:
                new_config = self.configs[self.active_config].copy()
            elif self.default_config in self.configs:
                new_config = self.configs[self.default_config].copy()
            else:
                # Если нет ни активной, ни default, создаем пустую конфигурацию
                new_config = {
                  "name": config_name,
                  "NM_API_KEY": "",
                  "NM_API_URL": "",
                  "NM_API_MODEL": "",
                  "NM_API_REQ": False,
                  "GEMINI_CASE": False,
                  "gpt4free": True,
                  "gpt4free_model": "",
                  "MODEL_MESSAGE_LIMIT": 40,
                  "MODEL_MESSAGE_ATTEMPTS_COUNT": 3,
                  "MODEL_MESSAGE_ATTEMPTS_TIME": 0.20,
                  "TEXT_WAIT_TIME": 40,
                  "VOICE_WAIT_TIME": 40,
                  "USE_MODEL_MAX_RESPONSE_TOKENS": True,
                  "MODEL_MAX_RESPONSE_TOKENS": 2500,
                  "MODEL_TEMPERATURE": 0.5,
                  "USE_MODEL_TOP_K": True,
                  "MODEL_TOP_K": 0,
                  "USE_MODEL_TOP_P": True,
                  "MODEL_TOP_P": 1.0,
                  "USE_MODEL_THINKING_BUDGET": False,
                  "MODEL_THINKING_BUDGET": 0.0,
                  "USE_MODEL_PRESENCE_PENALTY": False,
                  "MODEL_PRESENCE_PENALTY": 0.0,
                  "USE_MODEL_FREQUENCY_PENALTY": False,
                  "MODEL_FREQUENCY_PENALTY": 0.0,
                  "USE_MODEL_LOG_PROBABILITY": False,
                  "MODEL_LOG_PROBABILITY": 0.0
                }
            new_config["name"] = config_name
            self.save_config(config_name, new_config)
            self.configs[config_name] = new_config
            return True

    def delete_config(self, config_name):
        if config_name not in self.configs:
            return False
        else:
            filepath = os.path.join(self.config_dir, f"{config_name}.json")
            try:
                os.remove(filepath)
                del self.configs[config_name]
                if self.active_config == config_name:
                    self.active_config = None
                return True
            except Exception as e:
                print(f"Error deleting config {config_name}: {e}")
                return False

    def set_active_config(self, config_name):
        if config_name in self.configs:
            self.active_config = config_name
            return True
        else:
            return False

    def get_active_config(self):
        if self.active_config:
            return self.configs[self.active_config]
        else:
            return None

class SettingsManager:
    instance = None

    def __init__(self, config_path):
        self.config_path = config_path
        self.settings = {}
        self.load_settings()
        SettingsManager.instance = self

    def load_settings(self):
        try:
            if os.path.exists(self.config_path):
                with open(self.config_path, "rb") as f:
                    encoded = f.read()
                decoded = base64.b64decode(encoded)
                self.settings = json.loads(decoded.decode("utf-8"))
        except Exception as e:
            logger.error(f"Error loading settings: {e}")
            self.settings = {}

    def save_settings(self):
        try:
            json_data = json.dumps(self.settings, ensure_ascii=False)
            encoded = base64.b64encode(json_data.encode("utf-8"))
            with open(self.config_path, "wb") as f:
                f.write(encoded)
        except Exception as e:
            logger.error(f"Error saving settings: {e}")

    def get(self, key, default=None):
        return self.settings.get(key, default)

    def set(self, key, value):
        self.settings[key] = value

    @staticmethod
    def get(key, default=None):
        return SettingsManager.instance.settings.get(key, default)

    @staticmethod
    def set(key, value):
        SettingsManager.instance.settings[key] = value


class CollapsibleSection(ttk.Frame):
    def __init__(self, parent, title, *args, **kwargs):
        super().__init__(parent, *args, **kwargs)
        self.parent = parent
        self.title = title
        self.is_collapsed = False
        self.content_frame = None
        self.init_ui()

    def init_ui(self):
        # Setup styles
        style = ttk.Style()
        
        # Adjusted color scheme for better contrast
        bg_color = "#1e1e1e"  # Main background
        fg_color = "#ffffff"  # Text color
        header_bg = "#333333"  # Header background (slightly lighter than content)
        content_bg = "#202020"  # Content background (darker than header)
        input_bg = "#202020"  # Фон комбобокса (сделаем темнее)
        border_color = "#000000"  # Border color for inputs
        
        # Base application theme - use 'alt' as a better starting point for dark themes
        style.theme_use('alt')
        
        # Configure base styles
        style.configure("Dark.TFrame", background=bg_color)
        style.configure("Dark.TLabel", background=bg_color, foreground=fg_color)
        
        # Header styles - slightly lighter than content
        style.configure("Header.TFrame", background=header_bg)
        style.configure("Header.TLabel", background=header_bg, foreground=fg_color)
        
        # Content area style - darker than header
        style.configure("Content.TFrame", background=content_bg)
        style.configure("Content.TLabel", background="#1e1e1e", foreground=fg_color)
        
        # Entry field style - with dark background and visible borders
        style.configure("Dark.TEntry", 
                    fieldbackground=input_bg,
                    foreground=fg_color,
                    bordercolor=border_color,
                    lightcolor=border_color,
                    darkcolor=border_color)
        
        # Настраиваем глобальный стиль для всех комбобоксов
        style.configure("TCombobox", 
                    background=input_bg,
                    fieldbackground=input_bg,
                    foreground=fg_color,
                    arrowcolor=fg_color,
                    selectbackground=input_bg,
                    selectforeground=fg_color)
        
        # Глобальные состояния для комбобокса
        style.map("TCombobox",
                fieldbackground=[("readonly", input_bg), ("disabled", "#303030")],
                selectbackground=[("readonly", input_bg)],
                selectforeground=[("readonly", fg_color)],
                background=[("readonly", input_bg), ("disabled", "#303030")],
                foreground=[("readonly", fg_color), ("disabled", "#888888")])
        
        # Глобальные настройки выпадающего списка
        try:
            self.master.option_add('*TCombobox*Listbox.background', input_bg)
            self.master.option_add('*TCombobox*Listbox.foreground', fg_color)
            self.master.option_add('*TCombobox*Listbox.selectBackground', "#404040")
            self.master.option_add('*TCombobox*Listbox.selectForeground', fg_color)
            self.master.tk.eval("""
                set myFont [font create -family "Segoe UI" -size 9]
                option add *TCombobox*Listbox.font $myFont
                option add *TCombobox*Listbox.relief solid
                option add *TCombobox*Listbox.highlightThickness 0
            """)
        except Exception as e:
            logger.info(f"Ошибка при настройке выпадающего списка: {e}")
        
        # Checkbox styling
        style.configure("Dark.TCheckbutton", 
                    background=content_bg,
                    foreground=fg_color)
        
        # Create header
        self.header = ttk.Frame(self, style="Header.TFrame")
        self.header.pack(fill=tk.X)
        
        # Collapse indicator
        self.arrow_label = ttk.Label(
            self.header,
            text="▼",
            style="Header.TLabel"
        )
        self.arrow_label.pack(side=tk.LEFT, padx=5, pady=3)
        
        # Header text
        self.title_label = ttk.Label(
            self.header,
            text=self.title,
            font=("Arial", 10, "bold"),
            style="Header.TLabel"
        )
        self.title_label.pack(side=tk.LEFT, pady=3)
        
        # Content area - now using Content style
        self.content_frame = ttk.Frame(self, style="Content.TFrame")
        self.content_frame.pack(fill=tk.X, expand=True, pady=(0, 5))
        
        # Bind events
        self.header.bind("<Button-1>", self.toggle)
        self.arrow_label.bind("<Button-1>", self.toggle)
        self.title_label.bind("<Button-1>", self.toggle)
        
        # Apply style to main frame
        self.configure(style="Dark.TFrame")

    def toggle(self, event=None):
        if self.is_collapsed:
            self.collapse()
        else:
            self.expand()
        self.is_collapsed = not self.is_collapsed

    def collapse(self):
        self.arrow_label.config(text="▶")
        self.content_frame.pack_forget()

    def expand(self):
        self.arrow_label.config(text="▼")
        self.content_frame.pack(fill=tk.X, expand=True, pady=(0, 5))

    def add_widget(self, widget):
        # Применение стилей в зависимости от типа виджета
        if isinstance(widget, ttk.Combobox):
            widget.configure(state="readonly")
        elif isinstance(widget, ttk.Entry):
            widget.configure(style="Dark.TEntry")
        elif isinstance(widget, ttk.Checkbutton):
            widget.configure(style="Dark.TCheckbutton")
        elif isinstance(widget, ttk.Label):
            widget.configure(style="Dark.TLabel")
        
        widget.pack(in_=self.content_frame, fill=tk.X, pady=2, padx=10)