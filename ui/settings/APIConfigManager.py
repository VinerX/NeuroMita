import os
import json

class APIConfigManager:
    CONFIG_DIR = "Settings/API_Configs"
    DEFAULT_CONFIG_FILE = "default.json"
    ACTIVE_CONFIG_KEY = "active_api_config"

    def __init__(self, settings_manager):
        self.settings_manager = settings_manager
        self.configs = {}
        self.active_config_name = None
        self._ensure_config_dir()
        self._load_configs()
        self._set_initial_active_config()

    def _ensure_config_dir(self):
        os.makedirs(self.CONFIG_DIR, exist_ok=True)

    def _load_configs(self):
        self.configs = {}
        for filename in os.listdir(self.CONFIG_DIR):
            if filename.endswith(".json"):
                config_name = os.path.splitext(filename)[0]
                filepath = os.path.join(self.CONFIG_DIR, filename)
                try:
                    with open(filepath, 'r', encoding='utf-8') as f:
                        config_data = json.load(f)
                        self.configs[config_name] = config_data
                except json.JSONDecodeError:
                    print(f"Ошибка чтения файла конфигурации: {filepath}")
                except Exception as e:
                    print(f"Неизвестная ошибка при загрузке конфигурации {filepath}: {e}")

    def _set_initial_active_config(self):
        # Попытка загрузить активную конфигурацию из общих настроек
        stored_active_config = self.settings_manager.get(self.ACTIVE_CONFIG_KEY)
        if stored_active_config and stored_active_config in self.configs:
            self.active_config_name = stored_active_config
        elif self.DEFAULT_CONFIG_FILE.replace(".json", "") in self.configs:
            self.active_config_name = self.DEFAULT_CONFIG_FILE.replace(".json", "")
        elif self.configs:
            self.active_config_name = next(iter(self.configs)) # Берем первую доступную
        else:
            # Если нет ни одной конфигурации, создаем дефолтную
            self.create_config(self.DEFAULT_CONFIG_FILE.replace(".json", ""), self._get_default_config_template())
            self.active_config_name = self.DEFAULT_CONFIG_FILE.replace(".json", "")
        
        if self.active_config_name:
            self.settings_manager.set(self.ACTIVE_CONFIG_KEY, self.active_config_name)
            self.settings_manager.save_settings()


    def _get_default_config_template(self):
        # Шаблон для новой конфигурации, включая gpt4free по умолчанию
        return {
            "name": "default",
            "NM_API_KEY": "",
            "NM_API_URL": "",
            "NM_API_MODEL": "",
            "NM_API_REQ": False,
            "GEMINI_CASE": False,
            "gpt4free": True,
            "gpt4free_model": "",
            "SEPARATE_PROMPTS": True,
            "MODEL_MESSAGE_LIMIT": 40,
            "GPT4FREE_LAST_ATTEMPT": False,
            "MODEL_MESSAGE_ATTEMPTS_COUNT": 3,
            "MODEL_MESSAGE_ATTEMPTS_TIME": 0.20,
            "ENABLE_STREAMING": False,
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
            "MODEL_LOG_PROBABILITY": 0.0,
        }

    def _save_config_to_file(self, name, config_data):
        filepath = os.path.join(self.CONFIG_DIR, f"{name}.json")
        with open(filepath, 'w', encoding='utf-8') as f:
            json.dump(config_data, f, indent=4, ensure_ascii=False)

    def get_config(self, name):
        return self.configs.get(name)

    def get_active_config(self):
        if self.active_config_name:
            return self.configs.get(self.active_config_name)
        return None

    def set_active_config(self, name):
        if name in self.configs:
            self.active_config_name = name
            self.settings_manager.set(self.ACTIVE_CONFIG_KEY, name)
            self.settings_manager.save_settings()
            return True
        return False

    def create_config(self, name, initial_data=None):
        if name in self.configs:
            return False # Конфигурация с таким именем уже существует

        if initial_data is None:
            initial_data = self._get_default_config_template()
            initial_data["name"] = name # Обновляем имя в шаблоне

        self.configs[name] = initial_data
        self._save_config_to_file(name, initial_data)
        self._load_configs() # Перезагружаем, чтобы обновить список
        return True

    def save_config(self, name, config_data):
        if name in self.configs:
            self.configs[name] = config_data
            self._save_config_to_file(name, config_data)
            return True
        return False

    def delete_config(self, name):
        if name == self.DEFAULT_CONFIG_FILE.replace(".json", ""):
            return False # Нельзя удалить дефолтную конфигурацию

        if name in self.configs:
            filepath = os.path.join(self.CONFIG_DIR, f"{name}.json")
            if os.path.exists(filepath):
                os.remove(filepath)
            del self.configs[name]
            
            # Если удалена активная конфигурация, переключаемся на дефолтную или первую доступную
            if self.active_config_name == name:
                if self.DEFAULT_CONFIG_FILE.replace(".json", "") in self.configs:
                    self.set_active_config(self.DEFAULT_CONFIG_FILE.replace(".json", ""))
                elif self.configs:
                    self.set_active_config(next(iter(self.configs)))
                else:
                    self.active_config_name = None # Нет доступных конфигураций
                    self.settings_manager.delete_setting(self.ACTIVE_CONFIG_KEY)
                    self.settings_manager.save_settings()
            self._load_configs() # Перезагружаем, чтобы обновить список
            return True
        return False

    def get_config_names(self):
        return list(self.configs.keys())