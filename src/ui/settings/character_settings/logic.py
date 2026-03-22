# File: src/ui/settings/character_settings/logic.py

import os

from PyQt6.QtWidgets import QMessageBox, QDialog
from PyQt6.QtCore import QUrl, Qt, QTimer
from PyQt6.QtGui import QDesktopServices

from ui.task_worker import TaskWorker
from utils import getTranslationVariant as _
from main_logger import logger
from core.events import get_event_bus, Events
from managers.prompt_catalogue_manager import list_prompt_sets, read_info_json
from utils.migrate_json_to_sqlite import migrate as run_json_migration
from ui.dialogs.db_viewer import DbViewerDialog
from PyQt6.QtWidgets import QProgressDialog,QFileDialog
from ui.dialogs.db_export_dialog import DbExportDialog
def _create_reindex_worker(character_id: str, *, full: bool = False) -> TaskWorker:
    """Factory for single-character reindex workers."""
    character_id = str(character_id or "").strip()

    def _do_reindex(*, progress_callback=None):
        from managers.rag.rag_manager import RAGManager
        rag = RAGManager(character_id)
        method = rag.index_all if full else rag.index_all_missing
        return method(progress_callback=progress_callback)

    return TaskWorker(_do_reindex, use_progress=True)


# Backward-compatible aliases
def ReindexWorker(character_id: str) -> TaskWorker:
    return _create_reindex_worker(character_id, full=False)

def FullReindexWorker(character_id: str) -> TaskWorker:
    return _create_reindex_worker(character_id, full=True)


class ReindexAllCharactersWorker(TaskWorker):
    """
    Fill missing embeddings for ALL characters.
    Returns total number of created embeddings (best-effort).
    """

    def __init__(self, character_ids: list[str]):
        character_ids = [str(c or "").strip() for c in (character_ids or []) if str(c or "").strip()]

        def _do_all(*, progress_callback=None):
            # NOTE: cooperative cancellation happens inside progress_callback (TaskWorker._emit_progress)
            from managers.database_manager import DatabaseManager
            from managers.rag.rag_manager import RAGManager

            db = DatabaseManager()

            # Pre-count for a stable global progress bar (best-effort).
            totals: dict[str, int] = {}
            grand_total = 0
            for cid in character_ids:
                h_c, m_c = db.count_missing_embeddings(cid)
                t = int(h_c or 0) + int(m_c or 0)
                totals[cid] = t
                grand_total += t

            created_total = 0
            done_base = 0

            # If nothing to do: still emit a progress tick so "Cancel" works predictably.
            if progress_callback:
                progress_callback(0, max(grand_total, 1))

            for cid in character_ids:
                char_total = int(totals.get(cid, 0) or 0)
                if char_total <= 0:
                    continue

                rag = RAGManager(cid)

                def _cb(curr, total):
                    # total may differ across implementations; prefer our pre-count.
                    t = grand_total if grand_total > 0 else (done_base + int(total or 0) or 1)
                    progress_callback(done_base + int(curr or 0), t)

                created = rag.index_all_missing(progress_callback=_cb)
                try:
                    created_total += int(created or 0)
                except Exception:
                    pass
                done_base += char_total

            if progress_callback:
                progress_callback(done_base, max(grand_total, 1))
            return created_total

        super().__init__(_do_all, use_progress=True)


class FullReindexAllCharactersWorker(TaskWorker):
    """
    Regenerate ALL embeddings for ALL characters.
    Returns total number of processed rows (best-effort).
    """

    def __init__(self, character_ids: list[str]):
        character_ids = [str(c or "").strip() for c in (character_ids or []) if str(c or "").strip()]
        worker_ref = self  # capture for closure

        def _do_all_full(*, progress_callback=None):
            from managers.rag.rag_manager import RAGManager

            processed_total = 0
            global_done = 0
            global_total = 0
            num_chars = len(character_ids)

            if progress_callback:
                progress_callback(0, 1)

            for char_idx, cid in enumerate(character_ids):
                # Emit status with character name and overall progress
                try:
                    status = f"[{char_idx + 1}/{num_chars}] {cid}"
                    worker_ref.status_signal.emit(status)
                except Exception:
                    pass

                rag = RAGManager(cid)

                def _cb(curr, total):
                    nonlocal global_total
                    est = global_done + int(total or 0)
                    if est > global_total:
                        global_total = est
                    progress_callback(global_done + int(curr or 0), max(global_total, 1))

                processed = rag.index_all(progress_callback=_cb)
                try:
                    processed_total += int(processed or 0)
                except Exception:
                    pass
                global_done = max(global_done, global_total)

            progress_callback(global_done, max(global_total, 1))
            return processed_total

        super().__init__(_do_all_full, use_progress=True)


class DedupeHistoryWorker(TaskWorker):
    def __init__(self, character_id: str):
        from managers.database_manager import DatabaseManager
        db = DatabaseManager()
        super().__init__(db.dedupe_history, kwargs={"character_id": str(character_id or "").strip()})


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
    if hasattr(self, 'btn_migrate_db_all'):
        self.btn_migrate_db_all.clicked.connect(lambda: migrate_to_db_all(self))
    if hasattr(self, 'btn_db_viewer'):
        self.btn_db_viewer.clicked.connect(lambda: open_db_viewer(self))
    if hasattr(self, 'btn_db_viewer_global'):
        self.btn_db_viewer_global.clicked.connect(lambda: open_db_viewer_global(self))
    if hasattr(self, 'btn_dedupe_history'):
        self.btn_dedupe_history.clicked.connect(lambda: run_history_dedup(self))
    if hasattr(self, 'btn_reindex'):
        self.btn_reindex.clicked.connect(lambda: run_reindexing(self))
    if hasattr(self, 'btn_reindex_all'):
        self.btn_reindex_all.clicked.connect(lambda: run_full_reindexing(self))
    if hasattr(self, 'btn_reindex_global'):
        self.btn_reindex_global.clicked.connect(lambda: run_reindexing_all(self))
    if hasattr(self, 'btn_reindex_all_global'):
        self.btn_reindex_all_global.clicked.connect(lambda: run_full_reindexing_all(self))
    if hasattr(self, 'btn_dedupe_all'):
        self.btn_dedupe_all.clicked.connect(lambda: run_history_dedup_all(self))
    if hasattr(self, 'btn_export_db'):
        self.btn_export_db.clicked.connect(lambda: export_db_for_character(self))
    if hasattr(self, 'btn_import_db'):
        self.btn_import_db.clicked.connect(lambda: import_db_for_character(self))

    if hasattr(self, 'btn_export_db_global'):
        self.btn_export_db_global.clicked.connect(lambda: export_db_for_all(self))
    if hasattr(self, 'btn_import_db_global'):
        self.btn_import_db_global.clicked.connect(lambda: import_db_for_all(self))

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
    """Миграция JSON -> SQLite для ВЫБРАННОГО персонажа."""
    if run_json_migration is None:
        QMessageBox.critical(gui, _("Ошибка", "Error"),
                             _("Скрипт миграции не найден (utils.migrate_to_sql).",
                               "Migration script not found (utils.migrate_to_sql)."))
        return

    event_bus = get_event_bus()
    current_profile_res = event_bus.emit_and_wait(Events.Character.GET_CURRENT_PROFILE, timeout=1.0)
    profile = current_profile_res[0] if current_profile_res else {}
    character_id = profile.get("character_id") if isinstance(profile, dict) else None

    if not character_id:
        QMessageBox.information(gui, _("Информация", "Information"),
                                _("Персонаж не выбран или его имя недоступно.", "No character selected or its name is not available."))
        return

    title = _("Миграция в базу данных", "Database Migration")
    text = _("Вы хотите перенести историю персонажа '{cid}' из JSON файлов в базу данных SQLite (Histories/world.db)?\n\n"
             "Дубликаты могут быть пропущены. Старые файлы не удаляются.",
             "Do you want to migrate history for character '{cid}' from JSON files to SQLite database (Histories/world.db)?\n\n"
             "Duplicates might be skipped. Old files are not deleted.")
    text = text.format(cid=str(character_id))

    reply = QMessageBox.question(gui, title, text,
                                 QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)

    if reply != QMessageBox.StandardButton.Yes:
        return

    _start_migration_worker(gui, character_id=str(character_id))

def migrate_to_db_all(gui):
    """Миграция JSON -> SQLite для ВСЕХ персонажей."""
    if run_json_migration is None:
        QMessageBox.critical(gui, _("Ошибка", "Error"),
                             _("Скрипт миграции не найден (utils.migrate_to_sql).",
                               "Migration script not found (utils.migrate_to_sql)."))
        return

    title = _("Миграция в базу данных", "Database Migration")
    text = _("Вы хотите перенести историю ВСЕХ персонажей из JSON файлов в базу данных SQLite (Histories/world.db)?\n\n"
             "Дубликаты могут быть пропущены. Старые файлы не удаляются.",
             "Do you want to migrate history for ALL characters from JSON files to SQLite database (Histories/world.db)?\n\n"
             "Duplicates might be skipped. Old files are not deleted.")

    reply = QMessageBox.question(gui, title, text,
                                 QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
    if reply != QMessageBox.StandardButton.Yes:
        return

    _start_migration_worker(gui, character_id=None)


def _start_migration_worker(gui, character_id: str | None):
    """
    Background migration with progress + cancel.
    `character_id=None` means "all characters".
    """
    gui._migration_cancelled = False

    # Keep strong reference
    kwargs = {"character_id": character_id} if character_id else {"character_id": None}
    gui._migration_worker = TaskWorker(run_json_migration, kwargs=kwargs, use_progress=True)

    progress = QProgressDialog(
        _("Миграция данных...", "Migrating data..."),
        _("Отмена", "Cancel"),
        0, 100,
        gui
    )
    progress.setWindowModality(Qt.WindowModality.WindowModal)
    progress.setMinimumDuration(0)
    progress.setValue(0)
    progress.setAutoClose(False)
    progress.setAutoReset(False)

    def on_progress(curr, total):
        # total can be 0 if unknown; QProgressDialog treats it as busy when max==0.
        try:
            t = int(total or 0)
            c = int(curr or 0)
            if t <= 0:
                progress.setRange(0, 0)
            else:
                progress.setRange(0, t)
                progress.setValue(min(c, t))
                progress.setLabelText(
                    _("Миграция: {c} / {t}", "Migration: {c} / {t}").format(c=c, t=t)
                )
        except Exception:
            pass

    def _format_migration_result(res) -> str:
        if not isinstance(res, dict):
            return str(res or "")
        parts = []
        # keep it compact
        if "characters_processed" in res:
            parts.append(_("Персонажей: {n}", "Characters: {n}").format(n=res.get("characters_processed")))
        if "history_inserted" in res:
            parts.append(_("История добавлено: {n}", "History inserted: {n}").format(n=res.get("history_inserted")))
        if "history_skipped" in res:
            parts.append(_("История пропущено: {n}", "History skipped: {n}").format(n=res.get("history_skipped")))
        if "memories_inserted" in res:
            parts.append(_("Память добавлено: {n}", "Memories inserted: {n}").format(n=res.get("memories_inserted")))
        if "memories_skipped" in res:
            parts.append(_("Память пропущено: {n}", "Memories skipped: {n}").format(n=res.get("memories_skipped")))
        if "variables_written" in res:
            parts.append(_("Переменные записано: {n}", "Variables written: {n}").format(n=res.get("variables_written")))
        if "errors" in res and res.get("errors"):
            parts.append(_("Ошибок: {n}", "Errors: {n}").format(n=len(res.get("errors") or [])))
        return "\n".join(parts).strip()

    def on_finished(result):
        if getattr(gui, "_migration_cancelled", False):
            gui._migration_worker = None
            gui._migration_cancelled = False
            return
        progress.close()

        # reload data
        try:
            get_event_bus().emit(Events.Character.RELOAD_DATA)
        except Exception:
            pass

        msg = _format_migration_result(result)
        if msg:
            QMessageBox.information(gui, _("Успех", "Success"),
                                    _("Миграция завершена успешно.\n\n{msg}", "Migration completed successfully.\n\n{msg}").format(msg=msg))
        else:
            QMessageBox.information(gui, _("Успех", "Success"),
                                    _("Миграция завершена успешно.", "Migration completed successfully."))

        if hasattr(gui, "update_debug_info"):
            try:
                gui.update_debug_info()
            except Exception:
                pass

        gui._migration_worker = None
        gui._migration_cancelled = False

    def on_error(msg: str):
        if getattr(gui, "_migration_cancelled", False):
            gui._migration_worker = None
            gui._migration_cancelled = False
            return
        progress.close()
        QMessageBox.critical(gui, _("Ошибка", "Error"), msg)
        gui._migration_worker = None
        gui._migration_cancelled = False

    def on_cancel():
        gui._migration_cancelled = True
        try:
            gui._migration_worker.requestInterruption()
        except Exception:
            pass
        progress.close()

    def on_cancelled():
        gui._migration_worker = None
        gui._migration_cancelled = False

    gui._migration_worker.progress_signal.connect(on_progress)
    gui._migration_worker.finished_signal.connect(on_finished)
    gui._migration_worker.error_signal.connect(on_error)
    gui._migration_worker.cancelled_signal.connect(on_cancelled)
    progress.canceled.connect(on_cancel)

    progress.show()
    # Let dialog paint before heavy work starts
    QTimer.singleShot(0, gui._migration_worker.start)


def open_db_viewer(gui):
    event_bus = get_event_bus()
    res = event_bus.emit_and_wait(Events.Character.GET_CURRENT_PROFILE, timeout=1.0)
    char_id = res[0].get("character_id") if res else None

    dialog = DbViewerDialog(gui, character_id=char_id)
    dialog.exec()

def open_db_viewer_global(gui):
    dialog = DbViewerDialog(gui, character_id=None)
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

    gui._dedupe_cancelled = False
    from managers.database_manager import DatabaseManager
    db = DatabaseManager()

    gui._dedupe_worker = TaskWorker(db.dedupe_history, kwargs={"character_id": str(character_id)})

    progress = QProgressDialog(_("Очистка дублей...", "Removing duplicates..."),
                               _("Отмена", "Cancel"),
                               0, 0, gui)
    progress.setWindowModality(Qt.WindowModality.WindowModal)
    progress.setMinimumDuration(0)
    progress.setAutoClose(False)
    progress.setAutoReset(False)

    def on_finished(result):
        # If user already closed the dialog, don't show popups.
        if getattr(gui, "_dedupe_cancelled", False):
            gui._dedupe_worker = None
            gui._dedupe_cancelled = False
            return
        progress.close()
        QMessageBox.information(
            gui,
            _("Готово", "Done"),
            _("Удалено дублей: {n}", "Duplicates removed: {n}").format(n=int(result or 0))
        )
        gui._dedupe_worker = None
        gui._dedupe_cancelled = False
        # по желанию можно обновить UI/данные
        try:
            event_bus.emit(Events.Character.RELOAD_DATA)
        except Exception:
            pass
        if hasattr(gui, 'update_debug_info'):
            gui.update_debug_info()

    def on_error(msg: str):
        if getattr(gui, "_dedupe_cancelled", False):
            gui._dedupe_worker = None
            gui._dedupe_cancelled = False
            return
        progress.close()
        QMessageBox.critical(gui, _("Ошибка", "Error"), msg)
        gui._dedupe_worker = None
        gui._dedupe_cancelled = False

    def on_cancel():
        # Важно: НЕ роняем ссылку на поток пока он работает (это может крашить процесс в PyQt).
        gui._dedupe_cancelled = True
        try:
            gui._dedupe_worker.requestInterruption()
        except Exception:
            pass
        progress.close()

    def on_cancelled():
        # Поток завершился по cooperative cancel (если операция поддерживает cancel)
        gui._dedupe_worker = None
        gui._dedupe_cancelled = False

    gui._dedupe_worker.finished_signal.connect(on_finished)
    gui._dedupe_worker.error_signal.connect(on_error)
    gui._dedupe_worker.cancelled_signal.connect(on_cancelled)
    progress.canceled.connect(on_cancel)

    progress.show()
    gui._dedupe_worker.start()

def run_history_dedup_all(gui):
    title = _("Подтверждение", "Confirmation")
    text = _(
        "Удалить дубли в истории ДЛЯ ВСЕХ персонажей?\n\n"
        "Критерий: совпадают content + timestamp (и character_id).\n"
        "Будет оставлена запись с минимальным id.\n\n"
        "Операция может занять время.",
        "Remove duplicate history rows FOR ALL characters?\n\n"
        "Criteria: same content + timestamp (and character_id).\n"
        "Row with minimal id will be kept.\n\n"
        "This operation may take some time."
    )
    reply = QMessageBox.question(gui, title, text,
                                 QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
    if reply != QMessageBox.StandardButton.Yes:
        return

    gui._dedupe_all_cancelled = False
    from managers.database_manager import DatabaseManager
    db = DatabaseManager()

    gui._dedupe_all_worker = TaskWorker(db.dedupe_history, kwargs={"character_id": None})

    progress = QProgressDialog(_("Очистка дублей (все персонажи)...", "Removing duplicates (all characters)..."),
                               _("Отмена", "Cancel"),
                               0, 0, gui)
    progress.setWindowModality(Qt.WindowModality.WindowModal)
    progress.setMinimumDuration(0)
    progress.setAutoClose(False)
    progress.setAutoReset(False)

    def on_finished(result):
        if getattr(gui, "_dedupe_all_cancelled", False):
            gui._dedupe_all_worker = None
            gui._dedupe_all_cancelled = False
            return
        progress.close()
        QMessageBox.information(
            gui,
            _("Готово", "Done"),
            _("Удалено дублей: {n}", "Duplicates removed: {n}").format(n=int(result or 0))
        )
        gui._dedupe_all_worker = None
        gui._dedupe_all_cancelled = False
        try:
            get_event_bus().emit(Events.Character.RELOAD_DATA)
        except Exception:
            pass
        if hasattr(gui, 'update_debug_info'):
            gui.update_debug_info()

    def on_error(msg: str):
        if getattr(gui, "_dedupe_all_cancelled", False):
            gui._dedupe_all_worker = None
            gui._dedupe_all_cancelled = False
            return
        progress.close()
        QMessageBox.critical(gui, _("Ошибка", "Error"), msg)
        gui._dedupe_all_worker = None
        gui._dedupe_all_cancelled = False

    def on_cancel():
        gui._dedupe_all_cancelled = True
        try:
            gui._dedupe_all_worker.requestInterruption()
        except Exception:
            pass
        progress.close()

    def on_cancelled():
        gui._dedupe_all_worker = None
        gui._dedupe_all_cancelled = False

    gui._dedupe_all_worker.finished_signal.connect(on_finished)
    gui._dedupe_all_worker.error_signal.connect(on_error)
    gui._dedupe_all_worker.cancelled_signal.connect(on_cancelled)
    progress.canceled.connect(on_cancel)

    progress.show()
    gui._dedupe_all_worker.start()

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

    logger.info(f"Starting reindexing for character_id: {character_id}")

    # Предварительная проверка (создаем временный RAGManager для чтения)
    try:
        from managers.database_manager import DatabaseManager
        db = DatabaseManager()
        h_c, m_c = db.count_missing_embeddings(character_id)

        if (h_c + m_c) == 0:
            QMessageBox.information(gui, _("Инфо", "Info"),
                                    _("Все записи уже проиндексированы.", "All records are already indexed."))
            return

    except Exception as e:
        logger.warning(f"Skipping pre-check due to error: {e}")

    # Запуск воркера
    gui._reindex_worker = ReindexWorker(character_id)
    gui._reindex_cancelled = False

    progress = QProgressDialog(_("Генерация векторов...", "Generating embeddings..."), _("Отмена", "Cancel"), 0, 100,
                               gui)
    progress.setWindowModality(Qt.WindowModality.WindowModal)
    progress.setMinimumDuration(0)
    progress.setValue(0)
    progress.setAutoClose(False)
    progress.setAutoReset(False)


    def on_cancel():
        # Важно: НЕ обнуляем ссылку на поток пока он работает (может крашить процесс).
        gui._reindex_cancelled = True
        try:
            gui._reindex_worker.requestInterruption()
        except Exception:
            pass
        progress.close()

    progress.rejected.connect(on_cancel)

    def on_progress(curr, total):
        progress.setMaximum(total)
        progress.setValue(curr)

    def on_finished(count):
        if getattr(gui, "_reindex_cancelled", False):
            gui._reindex_worker = None
            gui._reindex_cancelled = False
            return
        progress.close()
        QMessageBox.information(
            gui,
            _("Готово", "Done"),
            _("Векторов создано: {n}", "Embeddings created: {n}").format(n=int(count or 0))
        )
        gui._reindex_worker = None

    def on_error(msg):
        if getattr(gui, "_reindex_cancelled", False):
            gui._reindex_worker = None
            gui._reindex_cancelled = False
            return
        progress.close()
        QMessageBox.critical(gui, _("Ошибка", "Error"), msg)
        gui._reindex_worker = None



    def on_cancelled():
        gui._reindex_worker = None
        gui._reindex_cancelled = False

    gui._reindex_worker.progress_signal.connect(on_progress)
    gui._reindex_worker.finished_signal.connect(on_finished)
    gui._reindex_worker.error_signal.connect(on_error)
    gui._reindex_worker.cancelled_signal.connect(on_cancelled)
    progress.canceled.connect(on_cancel)

    progress.show()
    gui._reindex_worker.start()


def _get_all_character_ids() -> list[str]:
    event_bus = get_event_bus()
    all_characters = event_bus.emit_and_wait(Events.Character.GET_ALL, timeout=1.0)
    character_list = all_characters[0] if all_characters else []
    return [str(c or "").strip() for c in (character_list or []) if str(c or "").strip()]


def run_reindexing_all(gui):
    """Fill missing embeddings for ALL characters."""
    character_ids = _get_all_character_ids()
    if not character_ids:
        QMessageBox.warning(gui, _("Ошибка", "Error"), _("Персонажи не найдены.", "No characters found."))
        return

    title = _("Подтверждение", "Confirmation")
    text = _(
        "Заполнить отсутствующие вектора для RAG для ВСЕХ персонажей?\n\n"
        "Операция может занять время.",
        "Fill missing embeddings for RAG for ALL characters?\n\n"
        "This operation may take some time."
    )
    reply = QMessageBox.question(gui, title, text,
                                 QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
    if reply != QMessageBox.StandardButton.Yes:
        return

    gui._reindex_all_worker = ReindexAllCharactersWorker(character_ids)
    gui._reindex_all_cancelled = False

    progress = QProgressDialog(
        _("Генерация векторов (все персонажи)...", "Generating embeddings (all characters)..."),
        _("Отмена", "Cancel"),
        0, 100,
        gui
    )
    progress.setWindowModality(Qt.WindowModality.WindowModal)
    progress.setMinimumDuration(0)
    progress.setValue(0)
    progress.setAutoClose(False)
    progress.setAutoReset(False)

    def on_progress(curr, total):
        try:
            t = int(total or 0)
            c = int(curr or 0)
            progress.setRange(0, max(t, 1))
            progress.setValue(min(c, max(t, 1)))
            progress.setLabelText(
                _("Обработано: {c} / {t}", "Processed: {c} / {t}").format(c=c, t=t if t else "?")
            )
        except Exception:
            pass

    def on_finished(count):
        if getattr(gui, "_reindex_all_cancelled", False):
            gui._reindex_all_worker = None
            gui._reindex_all_cancelled = False
            return
        progress.close()
        QMessageBox.information(
            gui,
            _("Готово", "Done"),
            _("Векторов создано: {n}", "Embeddings created: {n}").format(n=int(count or 0))
        )
        gui._reindex_all_worker = None
        gui._reindex_all_cancelled = False
        try:
            get_event_bus().emit(Events.Character.RELOAD_DATA)
        except Exception:
            pass
        if hasattr(gui, 'update_debug_info'):
            try:
                gui.update_debug_info()
            except Exception:
                pass

    def on_error(msg):
        if getattr(gui, "_reindex_all_cancelled", False):
            gui._reindex_all_worker = None
            gui._reindex_all_cancelled = False
            return
        progress.close()
        QMessageBox.critical(gui, _("Ошибка", "Error"), msg)
        gui._reindex_all_worker = None
        gui._reindex_all_cancelled = False

    def on_cancel():
        gui._reindex_all_cancelled = True
        try:
            gui._reindex_all_worker.requestInterruption()
        except Exception:
            pass
        progress.close()

    def on_cancelled():
        gui._reindex_all_worker = None
        gui._reindex_all_cancelled = False

    gui._reindex_all_worker.progress_signal.connect(on_progress)
    gui._reindex_all_worker.finished_signal.connect(on_finished)
    gui._reindex_all_worker.error_signal.connect(on_error)
    gui._reindex_all_worker.cancelled_signal.connect(on_cancelled)
    progress.canceled.connect(on_cancel)

    progress.show()
    gui._reindex_all_worker.start()


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

    # Best-effort count (avoid broken DB helper)
    try:
        from managers.database_manager import DatabaseManager
        db = DatabaseManager()
        conn = db.get_connection()
        cur = conn.cursor()
        cur.execute(
            "SELECT COUNT(*) FROM history WHERE character_id=? AND content IS NOT NULL AND TRIM(content) != ''",
            (str(character_id),),
        )
        h_c = int((cur.fetchone() or [0])[0] or 0)
        cur.execute(
            "SELECT COUNT(*) FROM memories WHERE character_id=? AND is_deleted=0",
            (str(character_id),),
        )
        m_c = int((cur.fetchone() or [0])[0] or 0)
        try:
            conn.close()
        except Exception:
            pass
        total_count = int(h_c or 0) + int(m_c or 0)
    except Exception as e:
        logger.warning(f"Skipping count check (full reindex): {e}")
        total_count = 0  # unknown; proceed

    # Запуск воркера
    gui._full_reindex_worker = FullReindexWorker(character_id)
    gui._full_reindex_cancelled = False

    progress = QProgressDialog(
        _("Полная переиндексация...", "Full re-indexing..."),
        _("Отмена", "Cancel"),
        0, 100, gui
    )
    progress.setWindowModality(Qt.WindowModality.WindowModal)
    progress.setMinimumDuration(0)
    if total_count > 0:
        progress.setRange(0, total_count)
    else:
        progress.setRange(0, 0)  # unknown -> busy indicator
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
        if getattr(gui, "_full_reindex_cancelled", False):
            gui._full_reindex_worker = None
            gui._full_reindex_cancelled = False
            return
        progress.close()
        QMessageBox.information(
            gui,
            _("Готово", "Done"),
            _("Переиндексировано записей: {n}", "Records re-indexed: {n}").format(n=count)
        )
        gui._full_reindex_worker = None
        gui._full_reindex_cancelled = False
        try:
            event_bus.emit(Events.Character.RELOAD_DATA)
        except Exception:
            pass
        if hasattr(gui, 'update_debug_info'):
            try:
                gui.update_debug_info()
            except Exception:
                pass

    def on_error(msg):
        if getattr(gui, "_full_reindex_cancelled", False):
            gui._full_reindex_worker = None
            gui._full_reindex_cancelled = False
            return
        progress.close()
        QMessageBox.critical(gui, _("Ошибка", "Error"), msg)
        gui._full_reindex_worker = None

    def on_cancel():
        gui._full_reindex_cancelled = True
        try:
            gui._full_reindex_worker.requestInterruption()
        except Exception:
            pass
        progress.close()

    def on_cancelled():
        gui._full_reindex_worker = None
        gui._full_reindex_cancelled = False

    gui._full_reindex_worker.progress_signal.connect(on_progress)
    gui._full_reindex_worker.finished_signal.connect(on_finished)
    gui._full_reindex_worker.error_signal.connect(on_error)
    gui._full_reindex_worker.cancelled_signal.connect(on_cancelled)
    progress.canceled.connect(on_cancel)

    progress.show()
    gui._full_reindex_worker.start()


def run_full_reindexing_all(gui):
    """Full re-indexing for ALL characters (regenerate embeddings for all rows)."""
    character_ids = _get_all_character_ids()
    if not character_ids:
        QMessageBox.warning(gui, _("Ошибка", "Error"), _("Персонажи не найдены.", "No characters found."))
        return

    title = _("Полная переиндексация", "Full Re-indexing")
    text = _(
        "Пересоздать ВСЕ вектора для ВСЕХ персонажей?\n\n"
        "Это перезапишет существующие эмбеддинги и может занять много времени.\n"
        "Используйте только если данные повреждены или модель эмбеддингов изменилась.",
        "Regenerate ALL embeddings for ALL characters?\n\n"
        "This will overwrite existing embeddings and may take a long time.\n"
        "Use only if data is corrupted or embedding model has changed."
    )
    reply = QMessageBox.question(gui, title, text,
                                 QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
    if reply != QMessageBox.StandardButton.Yes:
        return

    gui._full_reindex_all_worker = FullReindexAllCharactersWorker(character_ids)
    gui._full_reindex_all_cancelled = False

    progress = QProgressDialog(
        _("Полная переиндексация (все персонажи)...", "Full re-indexing (all characters)..."),
        _("Отмена", "Cancel"),
        0, 100, gui
    )
    progress.setWindowModality(Qt.WindowModality.WindowModal)
    progress.setMinimumDuration(0)
    progress.setRange(0, 0)  # unknown total -> will be adjusted by callbacks if possible
    progress.setValue(0)
    progress.setAutoClose(False)
    progress.setAutoReset(False)

    def on_progress(curr, total):
        try:
            t = int(total or 0)
            c = int(curr or 0)
            if t <= 0:
                progress.setRange(0, 0)
            else:
                progress.setRange(0, t)
                progress.setValue(min(c, t))
            progress.setLabelText(
                _("Обработано: {c} / {t}", "Processed: {c} / {t}").format(c=c, t=t if t else "?")
            )
        except Exception:
            pass

    def on_finished(count):
        if getattr(gui, "_full_reindex_all_cancelled", False):
            gui._full_reindex_all_worker = None
            gui._full_reindex_all_cancelled = False
            return
        progress.close()
        QMessageBox.information(
            gui,
            _("Готово", "Done"),
            _("Переиндексировано записей: {n}", "Records re-indexed: {n}").format(n=int(count or 0))
        )
        gui._full_reindex_all_worker = None
        gui._full_reindex_all_cancelled = False
        try:
            get_event_bus().emit(Events.Character.RELOAD_DATA)
        except Exception:
            pass
        if hasattr(gui, 'update_debug_info'):
            try:
                gui.update_debug_info()
            except Exception:
                pass

    def on_error(msg):
        if getattr(gui, "_full_reindex_all_cancelled", False):
            gui._full_reindex_all_worker = None
            gui._full_reindex_all_cancelled = False
            return
        progress.close()
        QMessageBox.critical(gui, _("Ошибка", "Error"), msg)
        gui._full_reindex_all_worker = None

def export_db_for_character(gui):
    event_bus = get_event_bus()
    res = event_bus.emit_and_wait(Events.Character.GET_CURRENT_PROFILE, timeout=1.0)
    profile = res[0] if res else {}
    cid = profile.get("character_id") if isinstance(profile, dict) else None
    if not cid:
        QMessageBox.warning(gui, _("Ошибка", "Error"), _("Персонаж не выбран.", "No character selected."))
        return

    dlg = DbExportDialog(gui, character_id=str(cid))
    if dlg.exec() != QDialog.DialogCode.Accepted:
        return
    settings = dlg.get_settings()

    _start_export_worker(gui, settings)


def export_db_for_all(gui):
    dlg = DbExportDialog(gui, character_id=None)
    if dlg.exec() != QDialog.DialogCode.Accepted:
        return
    settings = dlg.get_settings()
    _start_export_worker(gui, settings)


def _start_export_worker(gui, settings: dict):
    from managers.database_manager import DatabaseManager
    db = DatabaseManager()

    gui._export_cancelled = False
    gui._export_worker = TaskWorker(db.export_to_json_file, kwargs=settings, use_progress=True)

    progress = QProgressDialog(
        _("Выгрузка данных...", "Exporting data..."),
        _("Отмена", "Cancel"),
        0, 100,
        gui
    )
    progress.setWindowModality(Qt.WindowModality.WindowModal)
    progress.setMinimumDuration(0)
    progress.setValue(0)
    progress.setAutoClose(False)
    progress.setAutoReset(False)

    def on_progress(curr, total):
        try:
            t = int(total or 0)
            c = int(curr or 0)
            if t <= 0:
                progress.setRange(0, 0)
            else:
                progress.setRange(0, t)
                progress.setValue(min(c, t))
                progress.setLabelText(_("Выгрузка: {c}/{t}", "Export: {c}/{t}").format(c=c, t=t))
        except Exception:
            pass

    def on_finished(result):
        if getattr(gui, "_export_cancelled", False):
            gui._export_worker = None
            gui._export_cancelled = False
            return
        progress.close()

        msg = str(result or "")
        QMessageBox.information(gui, _("Успех", "Success"),
                                _("Выгрузка завершена.\n\n{msg}", "Export completed.\n\n{msg}").format(msg=msg))

        gui._export_worker = None
        gui._export_cancelled = False

    def on_error(msg: str):
        if getattr(gui, "_export_cancelled", False):
            gui._export_worker = None
            gui._export_cancelled = False
            return
        progress.close()
        QMessageBox.critical(gui, _("Ошибка", "Error"), msg)
        gui._export_worker = None
        gui._export_cancelled = False

    def on_cancel():
        gui._export_cancelled = True
        try:
            gui._export_worker.requestInterruption()
        except Exception:
            pass
        progress.close()

    def on_cancelled():
        gui._export_worker = None
        gui._export_cancelled = False

    gui._export_worker.progress_signal.connect(on_progress)
    gui._export_worker.finished_signal.connect(on_finished)
    gui._export_worker.error_signal.connect(on_error)
    gui._export_worker.cancelled_signal.connect(on_cancelled)
    progress.canceled.connect(on_cancel)

    progress.show()
    QTimer.singleShot(0, gui._export_worker.start)


def import_db_for_character(gui):
    # “просто выбрать путь”, но импорт мапим в текущего персонажа (override character_id)
    event_bus = get_event_bus()
    res = event_bus.emit_and_wait(Events.Character.GET_CURRENT_PROFILE, timeout=1.0)
    profile = res[0] if res else {}
    cid = profile.get("character_id") if isinstance(profile, dict) else None
    if not cid:
        QMessageBox.warning(gui, _("Ошибка", "Error"), _("Персонаж не выбран.", "No character selected."))
        return

    path, _flt = QFileDialog.getOpenFileName(gui, _("Выберите файл", "Select file"), os.getcwd(), "JSON (*.json)")
    if not path:
        return

    _start_import_worker(gui, path, override_character_id=str(cid))


def import_db_for_all(gui):
    path, _flt = QFileDialog.getOpenFileName(gui, _("Выберите файл", "Select file"), os.getcwd(), "JSON (*.json)")
    if not path:
        return
    _start_import_worker(gui, path, override_character_id=None)


def _start_import_worker(gui, path: str, override_character_id: str | None):
    from managers.database_manager import DatabaseManager
    db = DatabaseManager()

    gui._import_cancelled = False
    gui._import_worker = TaskWorker(
        db.import_from_json_file,
        kwargs={"path": path, "override_character_id": override_character_id},
        use_progress=True
    )

    progress = QProgressDialog(
        _("Загрузка данных...", "Importing data..."),
        _("Отмена", "Cancel"),
        0, 0,
        gui
    )
    progress.setWindowModality(Qt.WindowModality.WindowModal)
    progress.setMinimumDuration(0)
    progress.setAutoClose(False)
    progress.setAutoReset(False)

    def on_progress(curr, total):
        # импорт может не иметь точного total — оставляем busy
        try:
            t = int(total or 0)
            if t > 0:
                progress.setRange(0, t)
                progress.setValue(min(int(curr or 0), t))
        except Exception:
            pass

    def on_finished(result):
        if getattr(gui, "_import_cancelled", False):
            gui._import_worker = None
            gui._import_cancelled = False
            return
        progress.close()
        QMessageBox.information(gui, _("Успех", "Success"),
                                _("Загрузка завершена.\n\n{msg}", "Import completed.\n\n{msg}").format(msg=str(result or "")))
        gui._import_worker = None
        gui._import_cancelled = False
        try:
            get_event_bus().emit(Events.Character.RELOAD_DATA)
        except Exception:
            pass

    def on_error(msg: str):
        if getattr(gui, "_import_cancelled", False):
            gui._import_worker = None
            gui._import_cancelled = False
            return
        progress.close()
        QMessageBox.critical(gui, _("Ошибка", "Error"), msg)
        gui._import_worker = None
        gui._import_cancelled = False

    def on_cancel():
        gui._import_cancelled = True
        try:
            gui._import_worker.requestInterruption()
        except Exception:
            pass
        progress.close()

    def on_cancelled():
        gui._import_worker = None
        gui._import_cancelled = False

    gui._import_worker.progress_signal.connect(on_progress)
    gui._import_worker.finished_signal.connect(on_finished)
    gui._import_worker.error_signal.connect(on_error)
    gui._import_worker.cancelled_signal.connect(on_cancelled)
    progress.canceled.connect(on_cancel)

    progress.show()
    QTimer.singleShot(0, gui._import_worker.start)


def cleanup_character_workers(gui):
    """Stop and clean up any running background workers. Call from closeEvent."""
    _WORKER_ATTRS = (
        "_reindex_worker",
        "_migration_worker",
        "_dedupe_worker",
        "_export_worker",
        "_import_worker",
    )
    for attr in _WORKER_ATTRS:
        worker = getattr(gui, attr, None)
        if worker is None:
            continue
        try:
            worker.requestInterruption()
            worker.wait(2000)
        except Exception:
            pass
        try:
            setattr(gui, attr, None)
        except Exception:
            pass