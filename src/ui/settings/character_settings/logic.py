# File: src/ui/settings/character_settings/logic.py

import os

from PyQt6.QtWidgets import QMessageBox
from PyQt6.QtCore import QUrl, Qt
from PyQt6.QtGui import QDesktopServices

from utils import getTranslationVariant as _
from main_logger import logger
from core.events import get_event_bus, Events
from managers.prompt_catalogue_manager import list_prompt_sets, read_info_json


def _prompt_set_key(character_id: str) -> str:
    return f"PROMPT_SET_{character_id}"


def _default_prompt_set_for_character(character_id: str, options: list[str]) -> str:
    if not options:
        return ""
    if "Default" in options:
        return "Default"
    return options[0]


def _clear_prompt_info_fields(gui):
    labels = getattr(gui, "prompt_info_labels", None)
    if not isinstance(labels, dict) or not labels:
        return
    for lab in labels.values():
        try:
            lab.setText("—")
        except Exception:
            pass


def update_prompt_set_info(gui, character_id: str | None = None, set_name: str | None = None):
    labels = getattr(gui, "prompt_info_labels", None)
    if not isinstance(labels, dict) or not labels:
        return

    if character_id is None:
        character_id = gui.character_combobox.currentText().strip() if hasattr(gui, "character_combobox") else ""
    if set_name is None:
        set_name = gui.prompt_pack_combobox.currentText().strip() if hasattr(gui, "prompt_pack_combobox") else ""

    _clear_prompt_info_fields(gui)

    if not character_id or not set_name:
        return

    set_path = os.path.join("Prompts", character_id, set_name)
    info_data = read_info_json(set_path) or {}

    def _norm(v) -> str:
        s = str(v or "").replace("\r\n", "\n").strip()
        return s if s else "—"

    if "author" in labels:
        labels["author"].setText(_norm(info_data.get("author")))
    if "version" in labels:
        labels["version"].setText(_norm(info_data.get("version")))
    if "description" in labels:
        labels["description"].setText(_norm(info_data.get("description")))



def wire_character_settings_logic(self):
    event_bus = get_event_bus()

    all_characters = event_bus.emit_and_wait(Events.Character.GET_ALL, timeout=1.0)
    character_list = all_characters[0] if all_characters else ["Crazy"]

    self.character_combobox.blockSignals(True)
    self.character_combobox.clear()
    self.character_combobox.addItems(character_list if character_list else ["Crazy"])
    self.character_combobox.blockSignals(False)

    presets_meta = event_bus.emit_and_wait(Events.ApiPresets.GET_PRESET_LIST, timeout=1.0)
    provider_names = [_("Текущий", "Current")]
    if presets_meta and presets_meta[0]:
        all_presets = presets_meta[0].get('custom', [])
        for preset in all_presets:
            provider_names.append(preset.name)
    self.char_provider_combobox.clear()
    self.char_provider_combobox.addItems(provider_names)

    current_profile_res = event_bus.emit_and_wait(Events.Character.GET_CURRENT_PROFILE, timeout=1.0)
    current_profile = current_profile_res[0] if current_profile_res else {}
    current_char_id = current_profile.get('character_id', 'Crazy') if isinstance(current_profile, dict) else "Crazy"

    if current_char_id:
        idx = self.character_combobox.findText(current_char_id, Qt.MatchFlag.MatchFixedString)
        if idx >= 0:
            self.character_combobox.setCurrentIndex(idx)

    change_character_actions(self, current_char_id)

    if hasattr(self, 'prompt_pack_combobox'):
        self.prompt_pack_combobox.currentTextChanged.connect(lambda _text: on_prompt_set_changed(self))
    if hasattr(self, 'character_combobox'):
        self.character_combobox.currentTextChanged.connect(lambda _text: change_character_actions(self))
    if hasattr(self, 'char_provider_combobox'):
        self.char_provider_combobox.currentTextChanged.connect(lambda text: save_character_provider(self, text))

    if hasattr(self, 'btn_open_character_folder'):
        self.btn_open_character_folder.clicked.connect(lambda: open_character_folder(self))
    if hasattr(self, 'btn_reload_character_data'):
        self.btn_reload_character_data.clicked.connect(lambda: reload_character_data(self))
    if hasattr(self, 'btn_open_history_folder'):
        self.btn_open_history_folder.clicked.connect(lambda: open_character_history_folder(self))
    if hasattr(self, 'btn_clear_history'):
        self.btn_clear_history.clicked.connect(lambda: clear_history(self))
    if hasattr(self, 'btn_clear_all_histories'):
        self.btn_clear_all_histories.clicked.connect(lambda: clear_history_all(self))

    update_prompt_set_info(self)


def reload_character_data(gui):
    event_bus = get_event_bus()

    if not hasattr(gui, "character_combobox") or not hasattr(gui, "prompt_pack_combobox"):
        event_bus.emit(Events.Character.RELOAD_DATA)
        return

    character_id = gui.character_combobox.currentText().strip()
    if not character_id:
        event_bus.emit(Events.Character.RELOAD_DATA)
        _clear_prompt_info_fields(gui)
        return

    options = list_prompt_sets("Prompts", character_id) or []

    current_selected = gui.prompt_pack_combobox.currentText().strip()
    saved_key = _prompt_set_key(character_id)
    try:
        saved_selected = str(gui.settings.get(saved_key, "") or "").strip()
    except Exception:
        saved_selected = ""

    if current_selected and current_selected in options:
        chosen = current_selected
    elif saved_selected and saved_selected in options:
        chosen = saved_selected
    else:
        chosen = _default_prompt_set_for_character(character_id, options)

    gui.prompt_pack_combobox.blockSignals(True)
    try:
        gui.prompt_pack_combobox.clear()
        gui.prompt_pack_combobox.addItems(options)
        if chosen:
            gui.prompt_pack_combobox.setCurrentText(chosen)
    finally:
        gui.prompt_pack_combobox.blockSignals(False)

    if chosen:
        try:
            gui.settings.set(saved_key, chosen)
            gui.settings.save_settings()
        except Exception:
            pass

    update_prompt_set_info(gui, character_id=character_id, set_name=chosen)

    event_bus.emit(Events.Character.RELOAD_DATA)

    if hasattr(gui, "update_debug_info"):
        try:
            gui.update_debug_info()
        except Exception:
            pass


def on_prompt_set_changed(gui):
    if not hasattr(gui, 'character_combobox') or not hasattr(gui, 'prompt_pack_combobox'):
        return

    character_id = gui.character_combobox.currentText().strip()
    set_name = gui.prompt_pack_combobox.currentText().strip()

    update_prompt_set_info(gui, character_id=character_id, set_name=set_name)

    if not character_id or not set_name:
        return

    gui.settings.set(_prompt_set_key(character_id), set_name)
    gui.settings.save_settings()

    event_bus = get_event_bus()
    event_bus.emit(Events.Character.RELOAD_DATA)


def change_character_actions(gui, character_id=None):
    event_bus = get_event_bus()

    if character_id:
        selected_character = character_id
    elif hasattr(gui, 'character_combobox'):
        selected_character = gui.character_combobox.currentText()
    else:
        return

    if selected_character:
        event_bus.emit(Events.Character.SET_CURRENT, {'character_id': selected_character})

    if hasattr(gui, 'char_provider_combobox'):
        provider_key = f"CHAR_PROVIDER_{selected_character}"
        current_provider = gui.settings.get(provider_key, _("Текущий", "Current"))
        gui.char_provider_combobox.blockSignals(True)
        gui.char_provider_combobox.setCurrentText(current_provider)
        gui.char_provider_combobox.blockSignals(False)

    if not selected_character:
        QMessageBox.warning(gui, _("Внимание", "Warning"), _("Персонаж не выбран.", "No character selected."))
        _clear_prompt_info_fields(gui)
        return

    chosen = ""
    if hasattr(gui, 'prompt_pack_combobox'):
        options = list_prompt_sets("Prompts", selected_character) or []

        gui.prompt_pack_combobox.blockSignals(True)
        gui.prompt_pack_combobox.clear()
        gui.prompt_pack_combobox.addItems(options)

        saved_key = _prompt_set_key(selected_character)
        saved_set = gui.settings.get(saved_key, "")

        chosen = saved_set if saved_set in options else _default_prompt_set_for_character(selected_character, options)

        if chosen:
            gui.prompt_pack_combobox.setCurrentText(chosen)
            gui.settings.set(saved_key, chosen)
            gui.settings.save_settings()

        gui.prompt_pack_combobox.blockSignals(False)

    update_prompt_set_info(gui, character_id=selected_character, set_name=chosen)

    event_bus.emit(Events.Character.RELOAD_DATA)


def apply_prompt_set(gui, force_apply=True):
    if not hasattr(gui, 'character_combobox') or not hasattr(gui, 'prompt_pack_combobox'):
        return

    character_id = gui.character_combobox.currentText()
    set_name = gui.prompt_pack_combobox.currentText()
    if not character_id or not set_name:
        return

    if force_apply:
        reply = QMessageBox.question(
            gui,
            _("Подтверждение", "Confirmation"),
            _("Применить набор промптов?", "Apply prompt set?"),
            QMessageBox.StandardButton.Ok | QMessageBox.StandardButton.Cancel
        )
        if reply == QMessageBox.StandardButton.Cancel:
            return

    gui.settings.set(_prompt_set_key(character_id), set_name)
    gui.settings.save_settings()

    event_bus = get_event_bus()
    event_bus.emit(Events.Character.RELOAD_DATA)

    if force_apply:
        QMessageBox.information(gui, _("Успех", "Success"),
                                _("Набор промптов применён.", "Prompt set applied."))


def open_folder(path):
    if not os.path.exists(path):
        logger.error(f"Path does not exist: {path}")
        return
    url = QUrl.fromLocalFile(os.path.abspath(path))
    QDesktopServices.openUrl(url)


def open_character_folder(gui):
    event_bus = get_event_bus()
    current_profile_res = event_bus.emit_and_wait(Events.Character.GET_CURRENT_PROFILE, timeout=1.0)
    profile = current_profile_res[0] if current_profile_res else {}

    character_id = profile.get("character_id") if isinstance(profile, dict) else None
    if not character_id:
        QMessageBox.information(gui, _("Информация", "Information"),
                                _("Персонаж не выбран или его имя недоступно.", "No character selected or its name is not available."))
        return

    options = list_prompt_sets("Prompts", character_id)
    if not options:
        QMessageBox.warning(gui, _("Внимание", "Warning"),
                            _("Не найден ни один набор промптов для персонажа.", "No prompt sets found for character."))
        return

    key = _prompt_set_key(character_id)
    selected_set = gui.settings.get(key, "") if hasattr(gui, "settings") else ""
    if selected_set not in options:
        selected_set = _default_prompt_set_for_character(character_id, options)

    folder_path = os.path.join("Prompts", character_id, selected_set)
    if os.path.exists(folder_path):
        open_folder(folder_path)
    else:
        QMessageBox.warning(gui, _("Внимание", "Warning"),
                            _("Папка набора не найдена: ", "Prompt set folder not found: ") + folder_path)


def open_character_history_folder(gui):
    event_bus = get_event_bus()
    current_profile_res = event_bus.emit_and_wait(Events.Character.GET_CURRENT_PROFILE, timeout=1.0)
    profile = current_profile_res[0] if current_profile_res else {}

    character_id = profile.get("character_id") if isinstance(profile, dict) else None
    if character_id:
        history_folder_path = os.path.join("Histories", character_id)
        if os.path.exists(history_folder_path):
            open_folder(history_folder_path)
        else:
            QMessageBox.warning(gui, _("Внимание", "Warning"),
                                _("Папка истории персонажа не найдена: ", "Character history folder not found: ") + history_folder_path)
    else:
        QMessageBox.information(gui, _("Информация", "Information"),
                                _("Персонаж не выбран или его имя недоступно.", "No character selected or its name is not available."))


def clear_history(gui):
    event_bus = get_event_bus()
    current_profile_res = event_bus.emit_and_wait(Events.Character.GET_CURRENT_PROFILE, timeout=1.0)
    profile = current_profile_res[0] if current_profile_res else {}
    char_id = profile.get("character_id") if isinstance(profile, dict) else None
    char_name_for_text = char_id or _("(не выбран)", "(not selected)")

    title = _("Подтверждение удаления", "Confirm deletion")
    text = _("Очистить историю для персонажа '{name}'? Это действие нельзя отменить.",
             "Clear history for character '{name}'? This action cannot be undone.").format(name=char_name_for_text)
    reply = QMessageBox.question(gui, title, text,
                                 QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
    if reply != QMessageBox.StandardButton.Yes:
        return

    event_bus.emit(Events.Character.CLEAR_HISTORY)
    if hasattr(gui, 'clear_chat_display'):
        gui.clear_chat_display()
    if hasattr(gui, 'update_debug_info'):
        gui.update_debug_info()


def clear_history_all(gui):
    title = _("Подтвердите удаление всех историй", "Confirm deleting all histories")
    text = _("Это удалит историю всех персонажей без возможности восстановления. Продолжить?",
             "This will delete the history of all characters and cannot be undone. Continue?")
    reply = QMessageBox.question(gui, title, text,
                                 QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
    if reply != QMessageBox.StandardButton.Yes:
        return

    event_bus = get_event_bus()
    event_bus.emit(Events.Character.CLEAR_ALL_HISTORIES)
    if hasattr(gui, 'clear_chat_display'):
        gui.clear_chat_display()
    if hasattr(gui, 'update_debug_info'):
        gui.update_debug_info()


def save_character_provider(gui, provider: str):
    selected_character = gui.character_combobox.currentText() if hasattr(gui, 'character_combobox') else None
    if not selected_character:
        QMessageBox.warning(gui, _("Внимание", "Warning"), _("Персонаж не выбран.", "No character selected."))
        return
    provider_key = f"CHAR_PROVIDER_{selected_character}"
    gui.settings.set(provider_key, provider)
    try:
        gui.settings.save_settings()
    except Exception:
        pass
    logger.info(f"Saved provider '{provider}' for character '{selected_character}'")