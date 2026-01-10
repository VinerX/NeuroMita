# File: src/ui/settings/character_settings/logic.py

import os

from PyQt6.QtWidgets import QMessageBox
from PyQt6.QtCore import QUrl, Qt, QTimer
from PyQt6.QtGui import QDesktopServices

from utils import getTranslationVariant as _
from main_logger import logger
from core.events import get_event_bus, Events
from managers.prompt_catalogue_manager import list_prompt_sets, read_info_json
from utils.migrate_json_to_sqlite import migrate as run_json_migration
from ui.dialogs.db_viewer import DbViewerDialog
from PyQt6.QtWidgets import QProgressDialog
from PyQt6.QtCore import QThread, pyqtSignal

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
    if hasattr(self, 'btn_migrate_db'):
        self.btn_migrate_db.clicked.connect(lambda: migrate_to_db(self))
    if hasattr(self, 'btn_db_viewer'):
        self.btn_db_viewer.clicked.connect(lambda: open_db_viewer(self))
    if hasattr(self, 'btn_dedupe_history'):
        self.btn_dedupe_history.clicked.connect(lambda: run_history_dedup(self))
    if hasattr(self, 'btn_reindex'):
        self.btn_reindex.clicked.connect(lambda: run_reindexing(self))
    if hasattr(self, 'btn_reindex_all'):
        self.btn_reindex_all.clicked.connect(lambda: run_full_reindexing(self))


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

def migrate_to_db(gui):
    """Логика миграции JSON -> SQLite"""
    if run_json_migration is None:
        QMessageBox.critical(gui, _("Ошибка", "Error"),
                             _("Скрипт миграции не найден (utils.migrate_to_sql).",
                               "Migration script not found (utils.migrate_to_sql)."))
        return

    title = _("Миграция в базу данных", "Database Migration")
    text = _("Вы хотите перенести историю из JSON файлов в базу данных SQLite (Histories/world.db)?\n\n"
             "Дубликаты могут быть пропущены. Старые файлы не удаляются.",
             "Do you want to migrate history from JSON files to SQLite database (Histories/world.db)?\n\n"
             "Duplicates might be skipped. Old files are not deleted.")

    reply = QMessageBox.question(gui, title, text,
                                 QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)

    if reply != QMessageBox.StandardButton.Yes:
        return

    if hasattr(gui, '_show_loading_popup'):
        gui._show_loading_popup(_("Миграция данных...", "Migrating data..."))

    # Запускаем с задержкой, чтобы отрисовался попап
    QTimer.singleShot(100, lambda: _execute_migration(gui))

def _execute_migration(gui):
    try:
        run_json_migration()

        # Перезагружаем данные текущего персонажа
        event_bus = get_event_bus()
        event_bus.emit(Events.Character.RELOAD_DATA)

        if hasattr(gui, '_hide_loading_popup'):
            gui._hide_loading_popup()

        QMessageBox.information(gui, _("Успех", "Success"),
                                _("Миграция завершена успешно.", "Migration completed successfully."))

        # Обновляем дебаг инфо если открыто
        if hasattr(gui, 'update_debug_info'):
            gui.update_debug_info()

    except Exception as e:
        if hasattr(gui, '_hide_loading_popup'):
            gui._hide_loading_popup()
        logger.error(f"Migration failed: {e}", exc_info=True)
        QMessageBox.critical(gui, _("Ошибка", "Error"), f"Migration failed: {e}")


def open_db_viewer(gui):
    event_bus = get_event_bus()
    res = event_bus.emit_and_wait(Events.Character.GET_CURRENT_PROFILE, timeout=1.0)
    char_id = res[0].get("character_id") if res else None

    dialog = DbViewerDialog(gui, character_id=char_id)
    dialog.exec()

def run_history_dedup(gui):
    # Берём ID персонажа через EventBus (как в run_reindexing)
    event_bus = get_event_bus()
    res = event_bus.emit_and_wait(Events.Character.GET_CURRENT_PROFILE, timeout=1.0)

    if not res or not res[0]:
        QMessageBox.warning(gui, _("Ошибка", "Error"), _("Персонаж не найден.", "Character not found."))
        return

    character_id = res[0].get("character_id")
    if not character_id:
        QMessageBox.warning(gui, _("Ошибка", "Error"), _("Некорректный ID персонажа.", "Invalid character ID."))
        return

    title = _("Подтверждение", "Confirmation")
    text = _(
        "Удалить дубли в истории для персонажа '{cid}'?\n\n"
        "Критерий: совпадают content + timestamp (и character_id).\n"
        "Будет оставлена запись с минимальным id.",
        "Remove duplicate history rows for character '{cid}'?\n\n"
        "Criteria: same content + timestamp (and character_id).\n"
        "Row with minimal id will be kept."
    ).format(cid=str(character_id))

    reply = QMessageBox.question(gui, title, text,
                                 QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
    if reply != QMessageBox.StandardButton.Yes:
        return

    gui._dedupe_worker = DedupeHistoryWorker(str(character_id))

    progress = QProgressDialog(_("Очистка дублей...", "Removing duplicates..."),
                               _("Отмена", "Cancel"),
                               0, 0, gui)
    progress.setWindowModality(Qt.WindowModality.WindowModal)
    progress.setMinimumDuration(0)
    progress.setAutoClose(False)
    progress.setAutoReset(False)

    def on_finished(deleted_count: int):
        progress.close()
        QMessageBox.information(
            gui,
            _("Готово", "Done"),
            _("Удалено дублей: {n}", "Duplicates removed: {n}").format(n=int(deleted_count))
        )
        gui._dedupe_worker = None
        # по желанию можно обновить UI/данные
        try:
            event_bus.emit(Events.Character.RELOAD_DATA)
        except Exception:
            pass
        if hasattr(gui, 'update_debug_info'):
            gui.update_debug_info()

    def on_error(msg: str):
        progress.close()
        QMessageBox.critical(gui, _("Ошибка", "Error"), msg)
        gui._dedupe_worker = None

    def on_cancel():
        # Отмену потока без cooperative cancel не делаем (как и в reindex), просто закрываем UI
        gui._dedupe_worker = None
        progress.close()

    gui._dedupe_worker.finished_signal.connect(on_finished)
    gui._dedupe_worker.error_signal.connect(on_error)
    progress.canceled.connect(on_cancel)

    progress.show()
    gui._dedupe_worker.start()


class DedupeHistoryWorker(QThread):
    finished_signal = pyqtSignal(int)  # deleted count
    error_signal = pyqtSignal(str)

    def __init__(self, character_id: str):
        super().__init__()
        self.character_id = str(character_id or "").strip()

    def run(self):
        try:
            # ВАЖНО: DB-логика живёт в менеджерах, UI-поток не трогаем.
            from managers.history_manager import HistoryManager

            hm = HistoryManager(character_id=self.character_id)
            deleted = hm.dedupe_history()
            self.finished_signal.emit(int(deleted))
        except Exception as e:
            logger.error(f"Dedupe thread error: {e}", exc_info=True)
            self.error_signal.emit(str(e))

def run_reindexing(gui):
    # Получаем ID персонажа через EventBus, а не через контроллер
    event_bus = get_event_bus()
    res = event_bus.emit_and_wait(Events.Character.GET_CURRENT_PROFILE, timeout=1.0)

    if not res or not res[0]:
        QMessageBox.warning(gui, _("Ошибка", "Error"), _("Персонаж не найден.", "Character not found."))
        return

    character_id = res[0].get("character_id")
    if not character_id:
        QMessageBox.warning(gui, _("Ошибка", "Error"), _("Некорректный ID персонажа.", "Invalid character ID."))
        return

    # Предварительная проверка (создаем временный RAGManager для чтения)
    try:
        from managers.rag.rag_manager import RAGManager
        # Создаем легковесный инстанс, это безопасно
        rag = RAGManager(character_id)

        # Ручной SQL запрос через connection
        conn = rag.db.get_connection()
        c = conn.cursor()
        c.execute(f"SELECT COUNT(*) FROM history WHERE character_id=? AND embedding IS NULL AND content != ''",
                  (character_id,))
        h_c = c.fetchone()[0]
        c.execute(f"SELECT COUNT(*) FROM memories WHERE character_id=? AND embedding IS NULL", (character_id,))
        m_c = c.fetchone()[0]
        conn.close()

        if (h_c + m_c) == 0:
            QMessageBox.information(gui, _("Инфо", "Info"),
                                    _("Все записи уже проиндексированы.", "All records are already indexed."))
            return

    except Exception as e:
        logger.warning(f"Skipping pre-check due to error: {e}")

    # Запуск воркера
    gui._reindex_worker = ReindexWorker(character_id)

    progress = QProgressDialog(_("Генерация векторов...", "Generating embeddings..."), _("Отмена", "Cancel"), 0, 100,
                               gui)
    progress.setWindowModality(Qt.WindowModality.WindowModal)
    progress.setMinimumDuration(0)
    progress.setValue(0)
    progress.setAutoClose(False)
    progress.setAutoReset(False)

    def on_progress(curr, total):
        progress.setMaximum(total)
        progress.setValue(curr)

    def on_finished(count):
        progress.close()
        QMessageBox.information(gui, _("Готово", "Done"), f"Векторов создано: {count}")
        gui._reindex_worker = None

    def on_error(msg):
        progress.close()
        QMessageBox.critical(gui, _("Ошибка", "Error"), msg)
        gui._reindex_worker = None

    def on_cancel():
        # В идеале нужно слать сигнал отмены в worker, но пока просто закроем UI
        gui._reindex_worker = None

    gui._reindex_worker.progress_signal.connect(on_progress)
    gui._reindex_worker.finished_signal.connect(on_finished)
    gui._reindex_worker.error_signal.connect(on_error)
    progress.canceled.connect(on_cancel)

    progress.show()
    gui._reindex_worker.start()

class ReindexWorker(QThread):
    progress_signal = pyqtSignal(int, int)  # current, total
    finished_signal = pyqtSignal(int)  # count processed
    error_signal = pyqtSignal(str)

    def __init__(self, character_id):
        super().__init__()
        self.character_id = character_id

    def run(self):
        try:
            # Импортируем внутри потока
            from managers.rag.rag_manager import RAGManager

            # Создаем экземпляр RAGManager в этом потоке
            # Это создаст новое подключение к SQLite (thread-safe)
            rag = RAGManager(self.character_id)

            def callback(curr, tot):
                self.progress_signal.emit(curr, tot)

            updated_count = rag.index_all_missing(progress_callback=callback)
            self.finished_signal.emit(updated_count)

        except Exception as e:
            logger.error(f"Reindexing thread error: {e}", exc_info=True)
            self.error_signal.emit(str(e))

class FullReindexWorker(QThread):
    """Воркер для полной переиндексации (пересоздаёт ВСЕ вектора)"""
    progress_signal = pyqtSignal(int, int)  # current, total
    finished_signal = pyqtSignal(int)       # count processed
    error_signal = pyqtSignal(str)

    def __init__(self, character_id: str):
        super().__init__()
        self.character_id = character_id

    def run(self):
        try:
            from managers.rag.rag_manager import RAGManager

            rag = RAGManager(self.character_id)

            def callback(curr, tot):
                self.progress_signal.emit(curr, tot)

            updated_count = rag.index_all(progress_callback=callback)
            self.finished_signal.emit(updated_count)

        except Exception as e:
            logger.error(f"Full reindexing thread error: {e}", exc_info=True)
            self.error_signal.emit(str(e))


def run_full_reindexing(gui):
    """Полная переиндексация - пересоздаёт вектора для ВСЕХ записей"""
    event_bus = get_event_bus()
    res = event_bus.emit_and_wait(Events.Character.GET_CURRENT_PROFILE, timeout=1.0)

    if not res or not res[0]:
        QMessageBox.warning(gui, _("Ошибка", "Error"), _("Персонаж не найден.", "Character not found."))
        return

    character_id = res[0].get("character_id")
    if not character_id:
        QMessageBox.warning(gui, _("Ошибка", "Error"), _("Некорректный ID персонажа.", "Invalid character ID."))
        return

    # Предупреждение - это долгая операция
    title = _("Полная переиндексация", "Full Re-indexing")
    text = _(
        "Пересоздать ВСЕ вектора для персонажа '{cid}'?\n\n"
        "Это перезапишет существующие эмбеддинги и может занять много времени.\n"
        "Используйте только если данные повреждены или модель эмбеддингов изменилась.",
        "Regenerate ALL embeddings for character '{cid}'?\n\n"
        "This will overwrite existing embeddings and may take a long time.\n"
        "Use only if data is corrupted or embedding model has changed."
    ).format(cid=str(character_id))

    reply = QMessageBox.question(gui, title, text,
                                 QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
    if reply != QMessageBox.StandardButton.Yes:
        return

    # Подсчёт общего количества
    try:
        from managers.rag.rag_manager import RAGManager
        rag = RAGManager(character_id)
        conn = rag.db.get_connection()
        c = conn.cursor()

        hist_where = "character_id=? AND content != '' AND content IS NOT NULL"
        c.execute(f"SELECT COUNT(*) FROM history WHERE {hist_where}", (character_id,))
        h_c = c.fetchone()[0]

        c.execute("SELECT COUNT(*) FROM memories WHERE character_id=? AND is_deleted=0", (character_id,))
        m_c = c.fetchone()[0]
        conn.close()

        total_count = h_c + m_c
        if total_count == 0:
            QMessageBox.information(gui, _("Инфо", "Info"),
                                    _("Нет записей для индексации.", "No records to index."))
            return

    except Exception as e:
        logger.warning(f"Skipping count check: {e}")
        total_count = 0

    # Запуск воркера
    gui._full_reindex_worker = FullReindexWorker(character_id)

    progress = QProgressDialog(
        _("Полная переиндексация...", "Full re-indexing..."),
        _("Отмена", "Cancel"),
        0, 100, gui
    )
    progress.setWindowModality(Qt.WindowModality.WindowModal)
    progress.setMinimumDuration(0)
    progress.setValue(0)
    progress.setAutoClose(False)
    progress.setAutoReset(False)

    def on_progress(curr, total):
        progress.setMaximum(total)
        progress.setValue(curr)
        progress.setLabelText(
            _("Обработано: {c} / {t}", "Processed: {c} / {t}").format(c=curr, t=total)
        )

    def on_finished(count):
        progress.close()
        QMessageBox.information(
            gui,
            _("Готово", "Done"),
            _("Переиндексировано записей: {n}", "Records re-indexed: {n}").format(n=count)
        )
        gui._full_reindex_worker = None

    def on_error(msg):
        progress.close()
        QMessageBox.critical(gui, _("Ошибка", "Error"), msg)
        gui._full_reindex_worker = None

    def on_cancel():
        gui._full_reindex_worker = None

    gui._full_reindex_worker.progress_signal.connect(on_progress)
    gui._full_reindex_worker.finished_signal.connect(on_finished)
    gui._full_reindex_worker.error_signal.connect(on_error)
    progress.canceled.connect(on_cancel)

    progress.show()
    gui._full_reindex_worker.start()