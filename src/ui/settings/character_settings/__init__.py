from .ui import build_character_settings_ui
from .logic import (
    wire_character_settings_logic,
    on_prompt_set_changed,
    change_character_actions,
    apply_prompt_set,
    open_character_folder,
    open_character_history_folder,
    clear_history,
    clear_history_all,
    reload_character_data,
    save_character_provider,
    migrate_to_db,
)


def setup_mita_controls(self, parent_layout):
    """
    Собирает UI и подключает логику.
    self — это ваш MainView (или аналог), передаётся извне.
    parent_layout — QVBoxLayout контейнера настроек для вкладки Персонажи.
    """
    build_character_settings_ui(self, parent_layout)
    wire_character_settings_logic(self)


__all__ = [
    "setup_mita_controls",
    "on_prompt_set_changed",
    "change_character_actions",
    "apply_prompt_set",
    "open_character_folder",
    "open_character_history_folder",
    "clear_history",
    "clear_history_all",
    "reload_character_data",
    "save_character_provider",
    "migrate_to_db"
]