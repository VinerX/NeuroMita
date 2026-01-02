import os
import hashlib

from PyQt6.QtWidgets import QMessageBox, QLabel
from PyQt6.QtCore import QUrl, Qt, QTimer
from PyQt6.QtGui import QDesktopServices

from utils import getTranslationVariant as _
from main_logger import logger
from core.events import get_event_bus, Events
from ui.settings.prompt_catalogue_settings import list_prompt_sets
from managers.prompt_catalogue_manager import copy_prompt_set, get_prompt_catalogue_folder_name
from utils.migrate_json_to_sqlite import migrate as run_json_migration
from ui.dialogs.db_viewer import DbViewerDialog
from PyQt6.QtWidgets import QProgressDialog

def _prompt_set_key(character_id: str) -> str:
    return f"PROMPT_SET_{character_id}"


def _dir_file_hashes(folder: str, exclude=None) -> dict:
    result = {}
    if not os.path.isdir(folder):
        return result

    base_exclude = {"info.json", ".DS_Store", "Thumbs.db", "desktop.ini"}
    if exclude:
        base_exclude |= set(exclude)

    for root, dirnames, files in os.walk(folder):
        dirnames.sort()
        for f in sorted(files):
            if f in base_exclude:
                continue
            path = os.path.join(root, f)
            rel = os.path.relpath(path, folder).replace(os.sep, "/")

            sha = hashlib.sha256()
            try:
                with open(path, "rb") as fp:
                    for chunk in iter(lambda: fp.read(8192), b""):
                        sha.update(chunk)
                result[rel] = sha.hexdigest()
            except Exception as e:
                logger.warning(f"Не удалось прочитать файл {path}: {e}")

    return result


def _prompts_match(character_id: str, set_name: str, gui=None) -> bool:
    show_logs = False
    try:
        if gui and hasattr(gui, "settings"):
            show_logs = bool(gui.settings.get("SHOW_PROMPT_SYNC_LOGS", False))
    except Exception:
        show_logs = False

    def notify(msg: str):
        if show_logs:
            try:
                logger.notify(msg)
            except Exception:
                logger.info(msg)

    if not character_id or not set_name:
        return False

    char_dir = os.path.join("Prompts", character_id)
    set_dir = os.path.join("PromptsCatalogue", set_name)

    if not os.path.isdir(char_dir) or not os.path.isdir(set_dir):
        parts = []
        if not os.path.isdir(char_dir):
            parts.append(f"нет папки персонажа: {os.path.abspath(char_dir)}")
        if not os.path.isdir(set_dir):
            parts.append(f"нет папки набора: {os.path.abspath(set_dir)}")
        notify("Промпты отличаются: " + "; ".join(parts))
        return False

    char_hashes = _dir_file_hashes(char_dir)
    set_hashes = _dir_file_hashes(set_dir)

    if "config.json" not in set_hashes:
        char_hashes.pop("config.json", None)

    char_keys = set(char_hashes.keys())
    set_keys = set(set_hashes.keys())

    if char_keys != set_keys:
        missing_in_char = sorted(set_keys - char_keys)
        extra_in_char = sorted(char_keys - set_keys)

        lines = ["Промпты отличаются: состав файлов не совпадает."]
        if missing_in_char:
            lines.append("Отсутствуют в Prompts/<char> (есть в наборе):")
            lines += [f"  - {p}" for p in missing_in_char]
        if extra_in_char:
            lines.append("Лишние в Prompts/<char> (нет в наборе):")
            lines += [f"  - {p}" for p in extra_in_char]
        notify("\n".join(lines))
        return False

    diffs = []
    for rel in sorted(char_keys):
        if char_hashes[rel] != set_hashes[rel]:
            diffs.append((rel, char_hashes[rel], set_hashes[rel]))

    if diffs:
        lines = ["Следующие файлы по хешу не совпадают:"]
        lines += [f"- {rel}: char={h1}, set={h2}" for rel, h1, h2 in diffs]
        notify("\n".join(lines))
        return False

    return True


def _update_sync_indicator(gui):
    if not hasattr(gui, "prompt_sync_label"):
        gui.prompt_sync_label = QLabel("●")
        gui.prompt_sync_label.setToolTip(_("Индикатор соответствия промптов", "Prompts sync indicator"))

        if hasattr(gui, 'prompt_pack_combobox'):
            parent = gui.prompt_pack_combobox.parent()
            if parent and parent.layout():
                parent.layout().addWidget(gui.prompt_sync_label)

    if not hasattr(gui, 'character_combobox') or not hasattr(gui, 'prompt_pack_combobox'):
        return

    character_id = gui.character_combobox.currentText()
    set_name = gui.prompt_pack_combobox.currentText()

    ok = _prompts_match(character_id, set_name, gui=gui)
    color = "#2ecc71" if ok else "#e74c3c"
    gui.prompt_sync_label.setStyleSheet(f"color: {color}; font-size: 16px;")

    tooltip = _("Промпты синхронизированы", "Prompts are synchronized") if ok else _(
        "Промпты отличаются от выбранного набора", "Prompts differ from selected set")
    gui.prompt_sync_label.setToolTip(tooltip)


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

    if hasattr(self, "show_prompt_sync_logs_check"):
        self.show_prompt_sync_logs_check.setChecked(bool(self.settings.get("SHOW_PROMPT_SYNC_LOGS", False)))
        self.show_prompt_sync_logs_check.stateChanged.connect(
            lambda state: self.settings.set("SHOW_PROMPT_SYNC_LOGS", bool(state))
        )

    current_profile_res = event_bus.emit_and_wait(Events.Character.GET_CURRENT_PROFILE, timeout=1.0)
    current_profile = current_profile_res[0] if current_profile_res else {}
    current_char_id = current_profile.get('character_id', 'Crazy') if isinstance(current_profile, dict) else "Crazy"

    if current_char_id:
        idx = self.character_combobox.findText(current_char_id, Qt.MatchFlag.MatchFixedString)
        if idx >= 0:
            self.character_combobox.setCurrentIndex(idx)

    change_character_actions(self, current_char_id)

    if hasattr(self, 'prompt_pack_combobox'):
        self.prompt_pack_combobox.currentTextChanged.connect(lambda: on_prompt_set_changed(self))
    if hasattr(self, 'character_combobox'):
        self.character_combobox.currentTextChanged.connect(lambda _: change_character_actions(self))
    if hasattr(self, 'char_provider_combobox'):
        self.char_provider_combobox.currentTextChanged.connect(lambda text: save_character_provider(self, text))

    if hasattr(self, 'btn_open_character_folder'):
        self.btn_open_character_folder.clicked.connect(lambda: open_character_folder(self))
    if hasattr(self, 'btn_open_history_folder'):
        self.btn_open_history_folder.clicked.connect(lambda: open_character_history_folder(self))
    if hasattr(self, 'btn_clear_history'):
        self.btn_clear_history.clicked.connect(lambda: clear_history(self))
    if hasattr(self, 'btn_clear_all_histories'):
        self.btn_clear_all_histories.clicked.connect(lambda: clear_history_all(self))
    if hasattr(self, 'btn_reload_prompts'):
        self.btn_reload_prompts.clicked.connect(lambda: reload_prompts(self))
    if hasattr(self, 'btn_migrate_db'):
        self.btn_migrate_db.clicked.connect(lambda: migrate_to_db(self))
    if hasattr(self, 'btn_db_viewer'):
        self.btn_db_viewer.clicked.connect(lambda: open_db_viewer(self))
    if hasattr(self, 'btn_reindex'):
        self.btn_reindex.clicked.connect(lambda: run_reindexing(self))

    _update_sync_indicator(self)
    QTimer.singleShot(300, lambda: _update_sync_indicator(self))


def on_prompt_set_changed(gui):
    _update_sync_indicator(gui)

    if not hasattr(gui, 'character_combobox') or not hasattr(gui, 'prompt_pack_combobox'):
        return

    character_id = gui.character_combobox.currentText()
    set_ = gui.prompt_pack_combobox.currentText()

    if not character_id or not set_:
        return

    if not _prompts_match(character_id, set_, gui=gui):
        reply = QMessageBox.question(
            gui,
            _("Несоответствие промптов", "Prompts differ"),
            _("Промпты персонажа отличаются от выбранного набора.\nЗаменить?",
              "Character prompts differ from selected set.\nReplace?"),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        )
        if reply == QMessageBox.StandardButton.Yes:
            apply_prompt_set(gui)
    else:
        gui.settings.set(_prompt_set_key(character_id), set_)
        gui.settings.save_settings()


def set_default_prompt_pack(gui, combobox):
    character_id = gui.character_combobox.currentText()
    character_prompts_path = os.path.join("Prompts", character_id)
    folder_name = get_prompt_catalogue_folder_name(character_prompts_path)
    combobox.setCurrentText(folder_name)


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
        return

    if hasattr(gui, 'prompt_pack_combobox'):
        new_options = list_prompt_sets("PromptsCatalogue", selected_character)
        gui.prompt_pack_combobox.blockSignals(True)
        gui.prompt_pack_combobox.clear()
        gui.prompt_pack_combobox.addItems(new_options)

        saved_key = _prompt_set_key(selected_character)
        saved_prompt = gui.settings.get(saved_key, "")
        if saved_prompt and saved_prompt in new_options:
            gui.prompt_pack_combobox.setCurrentText(saved_prompt)
        else:
            set_default_prompt_pack(gui, gui.prompt_pack_combobox)

        gui.prompt_pack_combobox.blockSignals(False)
        _update_sync_indicator(gui)


def apply_prompt_set(gui, force_apply=True):
    event_bus = get_event_bus()

    chat_to = gui.prompt_pack_combobox.currentText()
    char_from = gui.character_combobox.currentText()
    if not chat_to:
        if force_apply:
            QMessageBox.warning(gui, _("Внимание", "Warning"), _("Набор промптов не выбран.", "No prompt set selected."))
        return

    if force_apply:
        reply = QMessageBox.question(gui, _("Подтверждение", "Confirmation"),
                                     _("Применить набор промптов?", "Apply prompt set?"),
                                     QMessageBox.StandardButton.Ok | QMessageBox.StandardButton.Cancel)
        if reply == QMessageBox.StandardButton.Cancel:
            set_default_prompt_pack(gui, gui.prompt_pack_combobox)
            return

    catalogue_path = "PromptsCatalogue"
    set_path = os.path.join(catalogue_path, chat_to)

    if char_from:
        character_prompts_path = os.path.join("Prompts", char_from)
        if copy_prompt_set(set_path, character_prompts_path, clean_target=True):
            gui.settings.set(_prompt_set_key(char_from), chat_to)
            gui.settings.save_settings()
            _update_sync_indicator(gui)

            if force_apply:
                QMessageBox.information(gui, _("Успех", "Success"),
                                        _("Набор промптов успешно применен.", "Prompt set applied successfully."))
            event_bus.emit(Events.Character.RELOAD_DATA)
    else:
        if force_apply:
            QMessageBox.warning(gui, _("Внимание", "Warning"), _("Персонаж не выбран.", "No character selected."))


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
    if character_id:
        character_folder_path = os.path.join("Prompts", character_id)
        if os.path.exists(character_folder_path):
            open_folder(character_folder_path)
        else:
            QMessageBox.warning(gui, _("Внимание", "Warning"),
                                _("Папка персонажа не найдена: ", "Character folder not found: ") + character_folder_path)
    else:
        QMessageBox.information(gui, _("Информация", "Information"),
                                _("Персонаж не выбран или его имя недоступно.", "No character selected or its name is not available."))


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


def reload_prompts(gui):
    title = _("Подтверждение", "Confirmation")
    text = _("Перекачать промпты из каталога? Текущие файлы промптов будут удалены и заменены.",
             "Reload prompts from catalogue? Current prompt files will be deleted and replaced.")
    reply = QMessageBox.question(gui, title, text,
                                 QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
    if reply != QMessageBox.StandardButton.Yes:
        return

    if hasattr(gui, '_show_loading_popup'):
        gui._show_loading_popup(_("Загрузка промптов...", "Downloading prompts..."))

    event_bus = get_event_bus()
    event_bus.emit(Events.Model.RELOAD_PROMPTS_ASYNC)


def save_character_provider(gui, provider: str):
    selected_character = gui.character_combobox.currentText() if hasattr(gui, 'character_combobox') else None
    if not selected_character:
        QMessageBox.warning(gui, _("Внимание", "Warning"), _("Персонаж не выбран.", "No character selected."))
        return
    provider_key = f"CHAR_PROVIDER_{selected_character}"
    gui.settings.set(provider_key, provider)
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
    # Получаем ID текущего персонажа для фильтрации
    event_bus = get_event_bus()
    current_profile_res = event_bus.emit_and_wait(Events.Character.GET_CURRENT_PROFILE, timeout=1.0)
    profile = current_profile_res[0] if current_profile_res else {}
    char_id = profile.get("character_id")

    # Открываем диалог. Используем WindowManager если он есть, или напрямую
    # Для простоты можно модально, так как это инструмент отладки
    dialog = DbViewerDialog(gui, character_id=char_id)
    dialog.exec()


def run_reindexing(gui):
    event_bus = get_event_bus()

    # Сначала проверим, есть ли что индексировать
    # Получаем доступ к текущему персонажу
    # (Это немного хак, лучше через событие, но допустим у нас есть доступ к controller.character_manager через gui.main_controller)
    # Используем EventBus для вызова логики, если возможно, или прямой вызов если мы внутри GUI логики.

    # Но проще всего - запросить это действие у системы.
    # Так как логика в logic.py, а RAG внутри Character, нам нужно добраться до инстанса.

    # Вариант: отправить событие
    # gui.event_bus.emit(Events.RAG.REINDEX, ...)
    # Но давай сделаем проще, через CharacterRef, так как мы в UI Logic

    char_ref = gui.main_controller.character_controller.get_current_ref()
    if not char_ref:
        return

    rag = char_ref.rag_manager if hasattr(char_ref, "rag_manager") else None

    # Если rag не инициализирован в Character (а он сейчас в MemoryManager), надо достать его.
    # В Character.py: self.memory_system = MemoryManager(...) -> self.rag = RAGManager(...)
    if hasattr(char_ref, "memory_system") and hasattr(char_ref.memory_system, "rag"):
        rag = char_ref.memory_system.rag
    else:
        # Fallback если rag_manager прямо в character (как в твоем snippet в Character.get_relevant_context)
        rag = getattr(char_ref, "rag_manager", None)

    if not rag:
        QMessageBox.warning(gui, "Error", "RAG Manager not found for this character.")
        return

    # Считаем сколько пропущено
    # (Мы добавили get_missing_embeddings_count в HistoryManager, но логичнее было в RAGManager)
    # Давай используем метод из history_manager, так как он там уже есть в моем примере выше?
    # Нет, в RAGManager логичнее.
    # Предположим мы добавили count метод в RAGManager тоже (аналогично коду выше).

    # Запускаем прогресс бар
    count_missing = 0
    # SQL count (можно вынести в метод RAGManager.count_missing())
    try:
        conn = rag.db.get_connection()
        c = conn.cursor()
        c.execute(
            f"SELECT COUNT(*) FROM history WHERE character_id='{char_ref.char_id}' AND embedding IS NULL AND content != ''")
        h_c = c.fetchone()[0]
        c.execute(f"SELECT COUNT(*) FROM memories WHERE character_id='{char_ref.char_id}' AND embedding IS NULL")
        m_c = c.fetchone()[0]
        conn.close()
        count_missing = h_c + m_c
    except:
        pass

    if count_missing == 0:
        QMessageBox.information(gui, _("Инфо", "Info"),
                                _("Все записи уже проиндексированы.", "All records are already indexed."))
        return

    progress = QProgressDialog(_("Генерация векторов...", "Generating embeddings..."), _("Отмена", "Cancel"), 0,
                               count_missing, gui)
    progress.setWindowModality(Qt.WindowModality.WindowModal)
    progress.show()

    def update_progress(current, total):
        progress.setValue(current)
        if progress.wasCanceled():
            return

    # Запускаем в потоке UI (синхронно) или через worker.
    # Так как embedding на CPU может фризить, лучше бы асинхронно,
    # но пока сделаем просто processEvents внутри колбэка

    from PyQt6.QtWidgets import QApplication
    def safe_callback(curr, tot):
        progress.setValue(curr)
        QApplication.processEvents()

    updated = rag.index_all_missing(progress_callback=safe_callback)

    progress.close()
    QMessageBox.information(gui, "Done", f"Re-indexed {updated} records.")
