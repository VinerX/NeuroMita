# File: src/ui/settings/character_settings/logic.py

import os

from PyQt6.QtWidgets import QMessageBox, QDialog
from PyQt6.QtCore import QUrl, Qt, QTimer
from PyQt6.QtGui import QDesktopServices

from controllers.gui.task_worker import TaskWorker
from utils import getTranslationVariant as _
from main_logger import logger
from core.events import get_event_bus, Events
from core.services import use
from services.contracts import ApiPresetService, CharacterRegistry
from managers.prompt_catalogue_manager import list_prompt_sets, read_info_json
from utils.history_migration import migrate_character_history
from utils.migrate_json_to_sqlite import migrate as run_json_migration
from utils.migrate_tags_to_structured_in_db import migrate as run_tags_to_structured_migration
from ui.dialogs.db_viewer import DbViewerDialog
from PyQt6.QtWidgets import QProgressDialog,QFileDialog
from ui.dialogs.db_export_dialog import DbExportDialog
from controllers.gui.async_runner import dispatch_to_gui
from controllers.gui.settings_data_prefetch import (
    API_PROVIDER_NAMES,
    CHARACTER_SETTINGS_SNAPSHOT,
    api_provider_names_from_result,
)


_CURRENT_PROVIDER_ITEM = ("Текущий", "Current", "Текущий")


def _create_reindex_worker(character_id: str, *, full: bool = False) -> TaskWorker:
    """Factory for single-character reindex workers."""
    character_id = str(character_id or "").strip()

    def _do_reindex(*, progress_callback=None):
        from managers.rag.rag_manager import RAGManager
        rag = RAGManager(character_id)
        method = rag.index_all if full else rag.index_all_missing
        return method(progress_callback=progress_callback)

    return TaskWorker(_do_reindex, use_progress=True)


class ReindexAllCharactersWorker(TaskWorker):
    """
    Fill missing embeddings for ALL characters.
    Returns total number of created embeddings (best-effort).
    """

    def __init__(self, character_ids: list[str]):
        character_ids = [str(c or "").strip() for c in (character_ids or []) if str(c or "").strip()]
        worker_ref = self  # capture for status emissions

        def _emit_status(text: str) -> None:
            try:
                worker_ref.status_signal.emit(str(text))
            except Exception:
                pass

        def _do_all(*, progress_callback=None):
            # NOTE: cooperative cancellation happens inside progress_callback (TaskWorker._emit_progress)
            from managers.database_manager import DatabaseManager
            from handlers.embedding_presets import resolve_full_config, resolve_model_settings
            from managers.rag.rag_manager import RAGManager

            db = DatabaseManager()
            cfg = resolve_full_config()
            model_name = str(cfg.get("db_model_key") or cfg.get("hf_name") or resolve_model_settings()["hf_name"])

            # Pre-count for a stable global progress bar (best-effort).
            _emit_status(_("Подсчёт отсутствующих записей...", "Counting missing records..."))
            totals: dict[str, int] = {}
            grand_total = 0
            for cid in character_ids:
                h_c, m_c = db.count_missing_embeddings(cid, model_name=model_name)
                t = int(h_c or 0) + int(m_c or 0)
                totals[cid] = t
                grand_total += t

            created_total = 0
            done_base = 0
            first_char = True

            # If nothing to do: still emit a progress tick so "Cancel" works predictably.
            if progress_callback:
                progress_callback(0, max(grand_total, 1))

            pending = [c for c in character_ids if int(totals.get(c, 0) or 0) > 0]
            for pos, cid in enumerate(pending, start=1):
                char_total = int(totals.get(cid, 0) or 0)

                # На первом персонаже модель эмбеддингов грузится лениво и может
                # занять 1-2 минуты — сообщаем об этом, иначе окно выглядит
                # зависшим (прогресс-тики придут только после загрузки).
                if first_char:
                    _emit_status(_(
                        "Загрузка модели эмбеддингов (первый запуск может занять 1-2 минуты)... [{c}/{t}] {cid}",
                        "Loading embedding model (first run may take 1-2 min)... [{c}/{t}] {cid}",
                    ).format(c=pos, t=len(pending), cid=cid))
                    first_char = False
                else:
                    _emit_status(_(
                        "Обработка [{c}/{t}] {cid}", "Processing [{c}/{t}] {cid}",
                    ).format(c=pos, t=len(pending), cid=cid))

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


def _current_character_id() -> str:
    """Текущий (активный) персонаж — единственный источник правды теперь в
    CharacterController. Выбирается ТОЛЬКО в песочнице."""
    return use(CharacterRegistry).current_id()


def _configured_character_id(gui) -> str:
    """Персонаж, чей КОНФИГ сейчас редактируется в настройках (раскрытая секция
    аккордеона). Раньше эту роль играл скрытый character_combobox. К активному
    персонажу отношения не имеет — настройка одного не переключает того, с кем
    идёт чат."""
    cid = str(getattr(gui, "_configured_char_id", "") or "").strip()
    active = str(getattr(gui, "_active_character_id", "") or "").strip()
    return cid or active or _current_character_id()


def _selected_character_id(gui) -> str:
    for attr in ("_configured_char_id", "_active_character_id", "current_character_id", "_current_char_id"):
        value = str(getattr(gui, attr, "") or "").strip()
        if value:
            return value
    return ""


def update_prompt_set_info(gui, character_id: str | None = None, set_name: str | None = None):
    labels = getattr(gui, "prompt_info_labels", None)
    if not isinstance(labels, dict) or not labels:
        return

    if character_id is None:
        character_id = _configured_character_id(gui)
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


def _fallback_character_list(gui) -> list[str]:
    combo = getattr(gui, "chat_character_combobox", None)
    if combo is not None:
        try:
            values = [
                str(combo.itemText(i) or "").strip()
                for i in range(combo.count())
                if str(combo.itemText(i) or "").strip()
            ]
            if values:
                return values
        except Exception:
            pass
    return ["Crazy"]


def _fallback_current_character_id(gui, character_list: list[str] | None = None) -> str:
    for attr in ("_configured_char_id", "_active_character_id"):
        value = str(getattr(gui, attr, "") or "").strip()
        if value:
            return value

    combo = getattr(gui, "chat_character_combobox", None)
    if combo is not None:
        try:
            value = str(combo.currentText() or "").strip()
            if value:
                return value
        except Exception:
            pass

    candidates = character_list or _fallback_character_list(gui)
    return str(candidates[0] if candidates else "Crazy").strip() or "Crazy"


def _default_provider_items() -> list:
    return [_CURRENT_PROVIDER_ITEM]


def _provider_items_from_presets_result(presets_meta) -> list:
    items = _default_provider_items()
    meta = presets_meta[0] if presets_meta else None
    if not isinstance(meta, dict):
        return items

    seen = {"Текущий", "Current"}
    for preset in meta.get("custom", []) or []:
        name = str(getattr(preset, "name", "") or "").strip()
        if not name or name in seen:
            continue
        seen.add(name)
        items.append(name)
    return items


def _set_character_provider_items(gui, provider_items: list) -> None:
    combo = getattr(gui, "char_provider_combobox", None)
    if combo is None:
        return
    try:
        current = combo.current_value() if hasattr(combo, "current_value") else None
        combo.set_items(provider_items or _default_provider_items(), current=current)
    except Exception:
        logger.warning("[character_settings] Failed to update provider combo", exc_info=True)


def _populate_chat_character_combobox(gui, character_list: list[str], current_char_id: str) -> None:
    combo = getattr(gui, "chat_character_combobox", None)
    if combo is None:
        return

    values = [str(c or "").strip() for c in (character_list or []) if str(c or "").strip()]
    if not values:
        values = ["Crazy"]

    blocked = combo.blockSignals(True)
    try:
        combo.clear()
        combo.addItems(values)
        if current_char_id:
            index = combo.findText(str(current_char_id), Qt.MatchFlag.MatchFixedString)
            if index >= 0:
                combo.setCurrentIndex(index)
    finally:
        combo.blockSignals(blocked)


def _load_character_settings_snapshot_async(gui, settings_data) -> None:
    if bool(getattr(gui, "_character_settings_snapshot_loading", False)):
        return

    cached = settings_data.get(CHARACTER_SETTINGS_SNAPSHOT, None)
    if cached is not None:
        _apply_character_settings_snapshot(gui, cached)
        return

    gui._character_settings_snapshot_loading = True

    def _worker():
        registry = use(CharacterRegistry)
        character_list = registry.all_ids()
        current_char_id = registry.current_id()

        return {
            "character_list": [str(c or "").strip() for c in (character_list or []) if str(c or "").strip()],
            "current_char_id": current_char_id,
        }

    def _apply(snapshot: dict) -> None:
        gui._character_settings_snapshot_loading = False
        _apply_character_settings_snapshot(gui, snapshot)

    def _error(_exc: Exception) -> None:
        gui._character_settings_snapshot_loading = False
        logger.warning(f"[character_settings] Failed to load character settings snapshot: {_exc}")
        _apply_character_settings_snapshot(gui, {
            "character_list": _fallback_character_list(gui),
            "provider_items": _default_provider_items(),
            "current_char_id": _fallback_current_character_id(gui),
        })

    settings_data.request(
        gui,
        CHARACTER_SETTINGS_SNAPSHOT,
        _worker,
        _apply,
        _error,
        name="character-settings-snapshot",
    )


def _load_character_provider_items_async(gui, settings_data) -> None:
    cached = settings_data.get(API_PROVIDER_NAMES, None)
    if cached is not None:
        _set_character_provider_items(gui, [*_default_provider_items(), *cached])
        return

    def _worker():
        return api_provider_names_from_result([use(ApiPresetService).list_meta()])

    def _apply(provider_names: list[str]) -> None:
        _set_character_provider_items(gui, [*_default_provider_items(), *(provider_names or [])])

    settings_data.request(
        gui,
        API_PROVIDER_NAMES,
        _worker,
        _apply,
        name="character-provider-options",
    )


def _apply_character_settings_snapshot(gui, snapshot: dict) -> None:
    character_list = list(snapshot.get("character_list") or []) or _fallback_character_list(gui)
    current_char_id = str(snapshot.get("current_char_id") or "").strip()
    if not current_char_id:
        current_char_id = _fallback_current_character_id(gui, character_list)

    gui._active_character_id = current_char_id
    gui._configured_char_id = current_char_id

    _populate_chat_character_combobox(gui, character_list, current_char_id)
    provider_items = snapshot.get("provider_items")
    if provider_items is None:
        provider_names = snapshot.get("provider_names")
        if provider_names is not None:
            provider_items = [*_default_provider_items(), *(provider_names or [])]
    if provider_items is not None:
        _set_character_provider_items(gui, list(provider_items or _default_provider_items()))
    expand_initial = (
        getattr(gui, "current_main_page", None) == "settings"
        and getattr(getattr(gui, "settings_page", None), "current_settings_category", None) == "characters"
    )
    _build_character_accordion(gui, character_list, current_char_id, expand_initial=expand_initial)
    update_prompt_set_info(gui)



def wire_character_settings_logic(self, *, settings_data):

    initial_characters = _fallback_character_list(self)
    initial_char_id = _fallback_current_character_id(self, initial_characters)
    self._configured_char_id = initial_char_id
    self._active_character_id = initial_char_id
    _set_character_provider_items(self, _default_provider_items())

    if hasattr(self, 'prompt_pack_combobox'):
        self.prompt_pack_combobox.currentTextChanged.connect(lambda _text: on_prompt_set_changed(self))
    # Индикатор активного персонажа в аккордеоне синхронизируем с песочницей.
    try:
        def _on_active_character_changed(event=None):
            data = getattr(event, "data", None) or {}
            character_id = ""
            if isinstance(data, dict):
                character_id = str(data.get("character_id", "") or "").strip()
            if not character_id:
                return

            def _apply():
                self._active_character_id = character_id
                _refresh_active_character_indicator(self, character_id)

            dispatch_to_gui(self, _apply)

        get_event_bus().subscribe(
            Events.Character.CURRENT_CHANGED,
            _on_active_character_changed,
            weak=False,
        )
    except Exception:
        pass
    if hasattr(self, 'char_provider_combobox'):
        self.char_provider_combobox.currentIndexChanged.connect(
            lambda _i: save_character_provider(self, self.char_provider_combobox.current_value()))
    if hasattr(self, 'btn_open_character_folder'):
        self.btn_open_character_folder.clicked.connect(lambda: open_character_folder(self))
    if hasattr(self, 'btn_reload_character_data'):
        self.btn_reload_character_data.clicked.connect(lambda: reload_character_data(self))
    if hasattr(self, 'btn_open_history_folder'):
        self.btn_open_history_folder.clicked.connect(lambda: open_character_history_folder(self))

    # --- Единый набор действий: маршрутизируем по выбранной области ---
    def _scope():
        return getattr(self, "_char_history_scope", "current")

    if hasattr(self, 'btn_history_view'):
        self.btn_history_view.clicked.connect(
            lambda: open_db_viewer(self) if _scope() == "current" else open_db_viewer_global(self))
    if hasattr(self, 'btn_history_export'):
        self.btn_history_export.clicked.connect(
            lambda: export_db_for_character(self) if _scope() == "current" else export_db_for_all(self))
    if hasattr(self, 'btn_history_import'):
        self.btn_history_import.clicked.connect(
            lambda: import_db_for_character(self) if _scope() == "current" else import_db_for_all(self))
    if hasattr(self, 'btn_history_reset'):
        self.btn_history_reset.clicked.connect(
            lambda: clear_history(self) if _scope() == "current" else clear_history_all(self))

    if hasattr(self, 'btn_maint_files_db'):
        self.btn_maint_files_db.clicked.connect(
            lambda: migrate_to_db(self) if _scope() == "current" else migrate_to_db_all(self))
    if hasattr(self, 'btn_maint_tags'):
        self.btn_maint_tags.clicked.connect(
            lambda: migrate_db_to_structured(self, "current" if _scope() == "current" else None))
    if hasattr(self, 'btn_maint_index_new'):
        self.btn_maint_index_new.clicked.connect(
            lambda: run_reindexing(self) if _scope() == "current" else run_reindexing_all(self))
    if hasattr(self, 'btn_maint_reindex'):
        self.btn_maint_reindex.clicked.connect(
            lambda: run_full_reindexing(self) if _scope() == "current" else run_full_reindexing_all(self))
    if hasattr(self, 'btn_maint_dedupe'):
        self.btn_maint_dedupe.clicked.connect(
            lambda: run_history_dedup(self) if _scope() == "current" else run_history_dedup_all(self))

    # «Обновить формат» — всегда для выбранного персонажа.
    if hasattr(self, 'btn_maint_update_format'):
        self.btn_maint_update_format.clicked.connect(lambda: migrate_history(self))

    # --- Опасная зона (все персонажи) — вне секций (#17) ---
    if hasattr(self, 'btn_all_files_db'):
        self.btn_all_files_db.clicked.connect(lambda: migrate_to_db_all(self))
    if hasattr(self, 'btn_all_dedupe'):
        self.btn_all_dedupe.clicked.connect(lambda: run_history_dedup_all(self))
    if hasattr(self, 'btn_all_index_new'):
        self.btn_all_index_new.clicked.connect(lambda: run_reindexing_all(self))
    if hasattr(self, 'btn_all_reindex'):
        self.btn_all_reindex.clicked.connect(lambda: run_full_reindexing_all(self))
    if hasattr(self, 'btn_all_reset_history'):
        self.btn_all_reset_history.clicked.connect(lambda: clear_history_all(self))
    if hasattr(self, 'btn_all_purge'):
        self.btn_all_purge.clicked.connect(lambda: purge_deleted_data(self))

    _load_character_settings_snapshot_async(self, settings_data)
    _load_character_provider_items_async(self, settings_data)
    update_prompt_set_info(self)


def _build_character_accordion(self, character_list, current_char_id, *, expand_initial: bool = True):
    """Построить аккордеон персонажей (#17): по секции на каждую Миту.

    Раскрытие секции: сворачивает соседние, переносит в неё общую панель
    настроек (`_char_config_panel`) и загружает КОНФИГ этого персонажа для
    редактирования. Активного персонажа (с кем идёт чат) секция НЕ переключает —
    это делается только в песочнице. На активном персонаже — визуальный
    индикатор (#4, по решению Винера).
    """
    from ui.widgets.settings_sections import InnerCollapsibleSection

    layout = getattr(self, "_char_accordion_layout", None)
    if layout is None:
        return

    _park_character_config_panel(self)
    while layout.count():
        item = layout.takeAt(0)
        widget = item.widget()
        if widget is not None:
            widget.setParent(None)
            widget.deleteLater()

    self._char_sections = {}
    for cid in (character_list or []):
        cid = str(cid or "").strip()
        if not cid:
            continue
        section = InnerCollapsibleSection(cid, parent=self)
        # Иконка-аватар персонажа слева от заголовка секции (#6).
        # resolve_character_avatar понимает id-формат ("KindMita"), а не только
        # display-имя ("Kind Mita") — иначе у части персонажей была плашка.
        try:
            from ui.chat.message_widget import resolve_character_avatar
            section.set_header_pixmap(resolve_character_avatar(cid, 22))
        except Exception:
            pass
        self._char_sections[cid] = section

        def _make_handler(_cid, _section):
            orig_toggle = _section.toggle

            def _wrapped(event=None):
                orig_toggle()
                if not _section.is_collapsed:
                    _on_character_section_expanded(self, _cid, _section)
            return _wrapped

        handler = _make_handler(cid, section)
        section.toggle = handler
        section.header.mousePressEvent = handler
        layout.addWidget(section)

    # Индикатор активного (выбранного в песочнице) персонажа.
    _refresh_active_character_indicator(self)

    # Раскрываем секцию редактируемого персонажа (переносит панель + грузит конфиг).
    target = current_char_id if current_char_id in self._char_sections else None
    if target is None and self._char_sections:
        target = next(iter(self._char_sections))
    if expand_initial and target is not None:
        self._char_sections[target].toggle()


def _park_character_config_panel(self) -> None:
    panel = getattr(self, "_char_config_panel", None)
    holder = getattr(self, "_char_config_holder", None)
    if panel is None or holder is None:
        return
    layout = holder.layout()
    if layout is None:
        return
    try:
        panel.setVisible(False)
        if panel.parent() is not holder:
            panel.setParent(holder)
        if layout.indexOf(panel) < 0:
            layout.addWidget(panel)
    except Exception:
        pass


def _refresh_active_character_indicator(self, active_character_id: str | None = None):
    """Пометить в аккордеоне секцию активного персонажа (того, с кем сейчас
    идёт чат — из CharacterController). Остальные — без пометки."""
    sections = getattr(self, "_char_sections", None)
    if not sections:
        return
    active = str(active_character_id or getattr(self, "_active_character_id", "") or "").strip()
    if not active:
        return
    for cid, sec in sections.items():
        title = getattr(sec, "title_label", None)
        if title is None:
            continue
        is_active = (cid == active)
        try:
            title.setStyleSheet(
                "color:#77d188; font-weight:600;" if is_active else ""
            )
            tip = _("Сейчас выбран в песочнице", "Currently selected in sandbox")
            title.setToolTip(tip if is_active else "")
        except Exception:
            pass


def _on_character_section_expanded(self, character_id, section):
    # Свернуть остальные секции — открыт только один персонаж за раз.
    for cid, sec in getattr(self, "_char_sections", {}).items():
        if sec is not section and not sec.is_collapsed:
            try:
                sec.collapse()
            except Exception:
                pass

    # Перенести общую панель настроек в раскрытую секцию.
    panel = getattr(self, "_char_config_panel", None)
    if panel is not None:
        section.content_layout.addWidget(panel)
        panel.setVisible(True)

    # Загрузить КОНФИГ этого персонажа в панель для редактирования. Активного
    # персонажа НЕ трогаем (SET_CURRENT тут больше нет) — переключение только
    # из песочницы.
    self._configured_char_id = character_id
    change_character_actions(self, character_id)


def reload_character_data(gui):

    if not hasattr(gui, "prompt_pack_combobox"):
        get_event_bus().emit(Events.Character.RELOAD_DATA)
        return

    character_id = _configured_character_id(gui)
    if not character_id:
        get_event_bus().emit(Events.Character.RELOAD_DATA)
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

    gui.prompt_pack_combobox.set_data_items(options, current=chosen)

    if chosen:
        try:
            gui.settings.set(saved_key, chosen)
        except Exception:
            pass

    update_prompt_set_info(gui, character_id=character_id, set_name=chosen)

    get_event_bus().emit(Events.Character.RELOAD_DATA)

    if hasattr(gui, "update_debug_info"):
        try:
            gui.update_debug_info()
        except Exception:
            pass


def on_prompt_set_changed(gui):
    if not hasattr(gui, 'prompt_pack_combobox'):
        return

    character_id = _configured_character_id(gui)
    set_name = gui.prompt_pack_combobox.currentText().strip()

    update_prompt_set_info(gui, character_id=character_id, set_name=set_name)

    if not character_id or not set_name:
        return

    gui.settings.set(_prompt_set_key(character_id), set_name)

    get_event_bus().emit(Events.Character.RELOAD_DATA)


def change_character_actions(gui, character_id=None):
    """Загрузить конфиг персонажа (набор промптов, провайдер, инфо) в панель
    настроек. НЕ переключает активного персонажа — выбор только в песочнице."""

    selected_character = str(character_id or "").strip() or _configured_character_id(gui)

    if hasattr(gui, 'char_provider_combobox'):
        provider_key = f"CHAR_PROVIDER_{selected_character}"
        current_provider = gui.settings.get(provider_key, "Текущий")
        gui.char_provider_combobox.set_current_value(current_provider)

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

        gui.prompt_pack_combobox.blockSignals(False)

    update_prompt_set_info(gui, character_id=selected_character, set_name=chosen)

    get_event_bus().emit(Events.Character.RELOAD_DATA)


def apply_prompt_set(gui, force_apply=True):
    if not hasattr(gui, 'prompt_pack_combobox'):
        return

    character_id = _configured_character_id(gui)
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

    get_event_bus().emit(Events.Character.RELOAD_DATA)

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
    character_id = _selected_character_id(gui)
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
    character_id = _selected_character_id(gui)
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


def purge_deleted_data(gui):
    """Physically delete is_deleted=1 records for ALL characters, with JSON backup."""
    import os
    from managers.character_resource_manager import get_character_resource_manager
    from managers.database_manager import DatabaseManager

    character_ids = _get_all_character_ids()
    if not character_ids:
        QMessageBox.warning(gui, _("Ошибка", "Error"),
                            _("Персонажи не найдены.", "No characters found."))
        return

    db = DatabaseManager()
    character_resources = get_character_resource_manager()
    db_size_before = os.path.getsize(db.db_path) if os.path.exists(db.db_path) else 0

    reply = QMessageBox.question(
        gui,
        _("Удалить помеченные записи?", "Purge deleted records?"),
        _(
            f"Физически удалить все записи is_deleted=1 для {len(character_ids)} персонажей?\n"
            "Резервная копия будет создана для каждого автоматически.",
            f"Physically delete all is_deleted=1 records for {len(character_ids)} characters?\n"
            "A backup will be created for each automatically."
        ),
        QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        QMessageBox.StandardButton.No,
    )
    if reply != QMessageBox.StandardButton.Yes:
        return

    total_memories = 0
    total_history = 0
    backups = []
    errors = []

    for char_id in character_ids:
        try:
            mm = character_resources.memory_for(char_id)
            r = mm.purge_deleted(backup=True)
            total_memories += r["purged_memories"]
            if r.get("backed_up"):
                backups.append(r["backed_up"])
        except Exception as e:
            errors.append(f"{char_id} memories: {e}")

        try:
            hm = character_resources.history_for(char_id)
            r = hm.purge_deleted(backup=True)
            total_history += r["purged_history"]
            if r.get("backed_up"):
                backups.append(r["backed_up"])
        except Exception as e:
            errors.append(f"{char_id} history: {e}")

    # VACUUM compacts the SQLite file and actually releases disk space
    try:
        db.vacuum()
    except Exception as e:
        errors.append(f"VACUUM: {e}")

    db_size_after = os.path.getsize(db.db_path) if os.path.exists(db.db_path) else 0
    freed_mb = (db_size_before - db_size_after) / (1024 * 1024)

    lines = [
        _("Память удалено: {n}", "Memories purged: {n}").format(n=total_memories),
        _("История удалено: {n}", "History purged: {n}").format(n=total_history),
        _("Освобождено: {mb:.1f} МБ", "Freed: {mb:.1f} MB").format(mb=freed_mb),
    ]
    if backups:
        lines.append(_("Бэкапов создано: {n}", "Backups created: {n}").format(n=len(backups)))
        lines.append(backups[0] + (" ..." if len(backups) > 1 else ""))
    if errors:
        lines.append(_("Ошибки:", "Errors:") + "\n" + "\n".join(errors))

    QMessageBox.information(gui, _("Готово", "Done"), "\n".join(lines))


def clear_history(gui):
    char_id = _selected_character_id(gui)
    char_name_for_text = char_id or _("(не выбран)", "(not selected)")

    title = _("Подтверждение удаления", "Confirm deletion")
    text = _("Очистить историю для персонажа '{name}'? Это действие нельзя отменить.",
             "Clear history for character '{name}'? This action cannot be undone.").format(name=char_name_for_text)
    reply = QMessageBox.question(gui, title, text,
                                 QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
    if reply != QMessageBox.StandardButton.Yes:
        return

    get_event_bus().emit(Events.Character.CLEAR_HISTORY)
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

    get_event_bus().emit(Events.Character.CLEAR_ALL_HISTORIES)
    if hasattr(gui, 'clear_chat_display'):
        gui.clear_chat_display()
    if hasattr(gui, 'update_debug_info'):
        gui.update_debug_info()


def migrate_history(gui):
    char_id = _selected_character_id(gui)
    char_name_for_text = char_id or _("(не выбран)", "(not selected)")

    if not char_id:
        QMessageBox.information(gui, _("Информация", "Information"),
                                _("Персонаж не выбран.", "No character selected."))
        return

    title = _("Миграция истории", "History migration")
    text = _("Мигрировать историю персонажа '{name}' в structured формат?\nБудет создана резервная копия файла.",
             "Migrate history for '{name}' to structured format?\nA backup of the file will be created.").format(name=char_name_for_text)
    reply = QMessageBox.question(gui, title, text,
                                 QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
    if reply != QMessageBox.StandardButton.Yes:
        return

    success, count = migrate_character_history(char_id)

    if not success:
        QMessageBox.critical(gui, _("Ошибка", "Error"),
                             _("Не удалось выполнить миграцию. Проверьте лог.",
                               "Migration failed. Check the log."))
        return

    if count == 0:
        QMessageBox.information(gui, title,
                                _("Нечего мигрировать — история уже в новом формате.",
                                  "Nothing to migrate — history is already in the new format."))
    else:
        QMessageBox.information(gui, title,
                                _("Готово! Смигрировано сообщений: {n}. Резервная копия сохранена рядом с файлом истории.",
                                  "Done! Messages migrated: {n}. Backup saved next to the history file.").format(n=count))


def save_character_provider(gui, provider: str):
    selected_character = _configured_character_id(gui)
    if not selected_character:
        QMessageBox.warning(gui, _("Внимание", "Warning"), _("Персонаж не выбран.", "No character selected."))
        return
    provider_key = f"CHAR_PROVIDER_{selected_character}"
    gui.settings.set(provider_key, provider)
    logger.info(f"Saved provider '{provider}' for character '{selected_character}'")

def migrate_to_db(gui):
    """Миграция JSON -> SQLite для ВЫБРАННОГО персонажа."""
    if run_json_migration is None:
        QMessageBox.critical(gui, _("Ошибка", "Error"),
                             _("Скрипт миграции не найден (utils.migrate_to_sql).",
                               "Migration script not found (utils.migrate_to_sql)."))
        return

    character_id = _selected_character_id(gui)

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


def migrate_db_to_structured(gui, character_id: str | None = "current"):
    """
    Мигрирует историю в БД: теги/meta_data.structured_data → колонка structured_data.
    character_id='current' — текущий персонаж, None — все персонажи.
    """

    if character_id == "current":
        character_id = _selected_character_id(gui)
        if not character_id:
            QMessageBox.information(gui, _("Информация", "Information"),
                                    _("Персонаж не выбран.", "No character selected."))
            return

    title = _("Миграция в structured формат", "Migrate to structured format")
    if character_id:
        text = _(
            "Перенести историю персонажа '{cid}' в structured_data колонку?\n"
            "(теги из content будут вынесены в отдельное поле, текст очистится)",
            "Migrate history for '{cid}' to structured_data column?\n"
            "(tags from content will be moved to a separate field, text will be cleaned)"
        ).format(cid=character_id)
    else:
        text = _(
            "Перенести историю ВСЕХ персонажей в structured_data колонку?\n"
            "(теги из content будут вынесены в отдельное поле, текст очистится)",
            "Migrate history for ALL characters to structured_data column?\n"
            "(tags from content will be moved to a separate field, text will be cleaned)"
        )

    reply = QMessageBox.question(gui, title, text,
                                 QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
    if reply != QMessageBox.StandardButton.Yes:
        return

    progress = QProgressDialog(
        _("Миграция structured данных...", "Migrating structured data..."),
        _("Отмена", "Cancel"),
        0, 100,
        gui
    )
    from PyQt6.QtCore import Qt
    progress.setWindowModality(Qt.WindowModality.WindowModal)
    progress.setMinimumDuration(0)
    progress.setValue(0)
    progress.setAutoClose(False)
    progress.setAutoReset(False)

    kwargs = {"character_id": character_id}
    gui._struct_migration_worker = TaskWorker(run_tags_to_structured_migration, kwargs=kwargs, use_progress=True)

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
                    _("Обработано: {c} / {t}", "Processed: {c} / {t}").format(c=c, t=t)
                )
        except Exception:
            pass

    def on_finished(result):
        progress.close()
        gui._struct_migration_worker = None
        res = result if isinstance(result, dict) else {}
        updated = res.get("rows_updated", "?")
        skipped = res.get("rows_skipped", "?")
        errors = len(res.get("errors") or [])
        msg = _(
            "Готово!\nОбновлено строк: {u}\nПропущено: {s}\nОшибок: {e}",
            "Done!\nRows updated: {u}\nSkipped: {s}\nErrors: {e}"
        ).format(u=updated, s=skipped, e=errors)
        QMessageBox.information(gui, title, msg)

    def on_error(err):
        progress.close()
        gui._struct_migration_worker = None
        QMessageBox.critical(gui, _("Ошибка", "Error"), str(err))

    def on_cancel():
        try:
            gui._struct_migration_worker.requestInterruption()
        except Exception:
            pass
        progress.close()

    gui._struct_migration_worker.progress_signal.connect(on_progress)
    gui._struct_migration_worker.finished_signal.connect(on_finished)
    gui._struct_migration_worker.error_signal.connect(on_error)
    progress.canceled.connect(on_cancel)

    progress.show()
    from PyQt6.QtCore import QTimer
    QTimer.singleShot(0, gui._struct_migration_worker.start)


def open_db_viewer(gui):
    char_id = _selected_character_id(gui) or None

    dialog = DbViewerDialog(gui, character_id=char_id)
    dialog.exec()

def open_db_viewer_global(gui):
    dialog = DbViewerDialog(gui, character_id=None)
    dialog.exec()

def run_history_dedup(gui):
    character_id = _selected_character_id(gui)
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
            get_event_bus().emit(Events.Character.RELOAD_DATA)
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
    character_id = _selected_character_id(gui)
    if not character_id:
        QMessageBox.warning(gui, _("Ошибка", "Error"), _("Некорректный ID персонажа.", "Invalid character ID."))
        return

    logger.info(f"Starting reindexing for character_id: {character_id}")

    # Предварительная проверка (создаем временный RAGManager для чтения)
    try:
        from managers.database_manager import DatabaseManager
        from handlers.embedding_presets import resolve_full_config, resolve_model_settings
        db = DatabaseManager()
        cfg = resolve_full_config()
        model_name = str(cfg.get("db_model_key") or cfg.get("hf_name") or resolve_model_settings()["hf_name"])
        h_c, m_c = db.count_missing_embeddings(character_id, model_name=model_name)

        if (h_c + m_c) == 0:
            QMessageBox.information(gui, _("Инфо", "Info"),
                                    _("Все записи уже проиндексированы.", "All records are already indexed."))
            return

    except Exception as e:
        logger.warning(f"Skipping pre-check due to error: {e}")

    # Запуск воркера
    gui._reindex_worker = _create_reindex_worker(character_id, full=False)
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
    ids: list[str] = []
    ids.extend(str(c or "").strip() for c in use(CharacterRegistry).all_ids() if str(c or "").strip())
    try:
        from managers.database_manager import DatabaseManager
        db = DatabaseManager()
        conn = db.get_connection()
        cur = conn.cursor()
        for table in ("history", "memories"):
            try:
                cur.execute(f"SELECT DISTINCT character_id FROM {table} WHERE character_id IS NOT NULL AND character_id != ''")
                ids.extend(str(r[0] or "").strip() for r in cur.fetchall() if str(r[0] or "").strip())
            except Exception:
                pass
        conn.close()
    except Exception:
        pass
    seen = set()
    result = []
    for cid in ids:
        if cid not in seen:
            seen.add(cid)
            result.append(cid)
    return result


def run_reindexing_all(gui):
    """Fill missing embeddings for ALL characters."""
    # Уже запущено — не плодим второй воркер, а возвращаем (возможно скрытое)
    # окно прогресса. Это же даёт «показать снова» после кнопки «Скрыть».
    existing = getattr(gui, "_reindex_all_worker", None)
    if existing is not None and existing.isRunning():
        dlg = getattr(gui, "_reindex_all_dialog", None)
        if dlg is not None:
            dlg.show()
            dlg.raise_()
            dlg.activateWindow()
        return

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

    from ui.dialogs.background_task_dialog import BackgroundTaskDialog

    gui._reindex_all_worker = ReindexAllCharactersWorker(character_ids)
    gui._reindex_all_cancelled = False

    progress = BackgroundTaskDialog(
        gui,
        title=_("Генерация векторов (все персонажи)", "Generating embeddings (all characters)"),
        eyebrow="RAG REINDEX",
        hint=_(
            "Окно можно скрыть — переиндексация продолжится в фоне. "
            "Кнопка «Индекс нового (все)» откроет его снова.",
            "You can hide this window — reindexing continues in the background. "
            "The \"Index new (all)\" button reopens it.",
        ),
    )
    gui._reindex_all_dialog = progress

    def on_progress(curr, total):
        try:
            t = int(total or 0)
            c = int(curr or 0)
            progress.set_range(0, max(t, 1))
            progress.set_value(min(c, max(t, 1)))
            progress.set_detail(
                _("Обработано: {c} / {t}", "Processed: {c} / {t}").format(c=c, t=t if t else "?")
            )
        except Exception:
            pass

    def _cleanup():
        gui._reindex_all_worker = None
        gui._reindex_all_cancelled = False
        gui._reindex_all_dialog = None

    def on_finished(count):
        if getattr(gui, "_reindex_all_cancelled", False):
            _cleanup()
            return
        progress.finish()
        QMessageBox.information(
            gui,
            _("Готово", "Done"),
            _("Векторов создано: {n}", "Embeddings created: {n}").format(n=int(count or 0))
        )
        _cleanup()
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
            _cleanup()
            return
        progress.finish()
        QMessageBox.critical(gui, _("Ошибка", "Error"), msg)
        _cleanup()

    def on_stop():
        gui._reindex_all_cancelled = True
        try:
            gui._reindex_all_worker.requestInterruption()
        except Exception:
            pass
        progress.finish()

    def on_cancelled():
        _cleanup()

    gui._reindex_all_worker.progress_signal.connect(on_progress)
    gui._reindex_all_worker.status_signal.connect(progress.set_status)
    gui._reindex_all_worker.finished_signal.connect(on_finished)
    gui._reindex_all_worker.error_signal.connect(on_error)
    gui._reindex_all_worker.cancelled_signal.connect(on_cancelled)
    progress.stopRequested.connect(on_stop)

    progress.show()
    gui._reindex_all_worker.start()


def run_full_reindexing(gui):
    """Полная переиндексация - пересоздаёт вектора для ВСЕХ записей"""
    character_id = _selected_character_id(gui)
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
    gui._full_reindex_worker = _create_reindex_worker(character_id, full=True)
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
            get_event_bus().emit(Events.Character.RELOAD_DATA)
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
    cid = _selected_character_id(gui)
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
    cid = _selected_character_id(gui)
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
