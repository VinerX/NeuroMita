import os
from PyQt6.QtWidgets import QMessageBox
from PyQt6.QtCore import QUrl
from PyQt6.QtGui import QDesktopServices

from utils import getTranslationVariant as _
from managers.prompt_catalogue_manager import (
    list_prompt_sets, read_info_json, write_info_json, delete_prompt_set
)


def wire_prompt_catalogue_logic(self):
    root_path = "Prompts"

    def update_prompt_set_combobox():
        current_text = self.prompt_set_combobox.currentText()
        self.prompt_set_combobox.blockSignals(True)
        try:
            self.prompt_set_combobox.clear()
            sets = list_prompt_sets(root_path)
            if sets:
                self.prompt_set_combobox.addItems(sets)
                if current_text in sets:
                    self.prompt_set_combobox.setCurrentText(current_text)
                else:
                    self.prompt_set_combobox.setCurrentIndex(0)
        finally:
            self.prompt_set_combobox.blockSignals(False)
        on_prompt_set_selected(self.prompt_set_combobox.currentText())

    def on_prompt_set_selected(selected_set_rel: str):
        if selected_set_rel:
            set_path = os.path.join(root_path, selected_set_rel)
            load_info_json(set_path, selected_set_rel)

    def load_info_json(set_path: str, selected_rel: str):
        info_data = read_info_json(set_path)
        clear_info_json_fields()
        if info_data:
            for key, entry in self.info_json_entries.items():
                entry.setText(info_data.get(key, ""))
        self.info_json_entries["folder"].setText(selected_rel)

    def clear_info_json_fields():
        for entry in self.info_json_entries.values():
            entry.clear()

    def save_info_json_action():
        selected_rel = self.prompt_set_combobox.currentText()
        if not selected_rel:
            QMessageBox.warning(self, _("Внимание", "Warning"),
                                _("Набор промптов не выбран для сохранения.", "No prompt set selected for saving."))
            return

        current_set_path = os.path.join(root_path, selected_rel)
        new_rel = self.info_json_entries["folder"].text().strip() or selected_rel

        if new_rel != selected_rel:
            new_set_path = os.path.join(root_path, new_rel)
            if os.path.exists(new_set_path):
                QMessageBox.critical(self, _("Ошибка", "Error"),
                                     _(f"Путь '{new_rel}' уже существует.",
                                       f"Path '{new_rel}' already exists."))
                return
            try:
                os.makedirs(os.path.dirname(new_set_path), exist_ok=True)
                os.rename(current_set_path, new_set_path)
                current_set_path = new_set_path
            except OSError as e:
                QMessageBox.critical(self, _("Ошибка", "Error"),
                                     _(f"Не удалось переименовать папку: {e}", f"Failed to rename folder: {e}"))
                return

        info_data = {key: entry.text() for key, entry in self.info_json_entries.items() if key != 'folder'}
        if write_info_json(current_set_path, info_data):
            QMessageBox.information(self, _("Успех", "Success"),
                                    _("Информация о наборе сохранена.", "Set information saved."))
            update_prompt_set_combobox()

    def open_set_folder_action():
        selected_rel = self.prompt_set_combobox.currentText()
        if selected_rel:
            set_path = os.path.join(root_path, selected_rel)
            if os.path.exists(set_path):
                QDesktopServices.openUrl(QUrl.fromLocalFile(os.path.abspath(set_path)))
            else:
                QMessageBox.warning(self, _("Внимание", "Warning"),
                                    _("Папка набора не найдена.", "Set folder not found."))
        else:
            QMessageBox.warning(self, _("Внимание", "Warning"),
                                _("Набор промптов не выбран.", "No prompt set selected."))

    def delete_set_action():
        selected_rel = self.prompt_set_combobox.currentText()
        if selected_rel:
            set_path = os.path.join(root_path, selected_rel)
            if delete_prompt_set(set_path):
                QMessageBox.information(self, _("Успех", "Success"),
                                        _("Набор промптов успешно удален.", "Prompt set deleted successfully."))
                update_prompt_set_combobox()
        else:
            QMessageBox.warning(self, _("Внимание", "Warning"),
                                _("Набор промптов не выбран.", "No prompt set selected."))

    self.prompt_set_combobox.currentTextChanged.connect(on_prompt_set_selected)
    self.prompt_refresh_button.clicked.connect(update_prompt_set_combobox)
    self.pc_open_folder_button.clicked.connect(open_set_folder_action)
    self.pc_delete_button.clicked.connect(delete_set_action)
    self.pc_save_info_button.clicked.connect(save_info_json_action)

    update_prompt_set_combobox()