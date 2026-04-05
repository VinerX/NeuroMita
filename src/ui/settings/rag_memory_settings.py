import json
import os
import threading

from PyQt6.QtWidgets import (
    QLineEdit, QCheckBox, QComboBox, QInputDialog, QMessageBox,
    QProgressDialog, QLabel, QHBoxLayout, QWidget, QPushButton,
)
from PyQt6.QtCore import Qt

from ui.gui_templates import create_settings_section
from utils import getTranslationVariant as _
from core.events import get_event_bus, Events
from managers.rag.pipeline.config import RAG_DEFAULTS
from managers.rag.pipeline.config import list_ce_preset_names, CE_PRESETS
from managers.rag.pipeline.config import (
    RAG_PIPELINE_PRESETS, list_pipeline_preset_names, get_pipeline_preset_settings,
)
from handlers.embedding_presets import list_preset_names, resolve_model_settings

# Module-level state for the running extraction (survives dialog close).
_extr_state: dict = {'worker': None, 'stop': None, 'total': 0, 'last_status': ''}


# ---------------------------------------------------------------------------
# Status helpers
# ---------------------------------------------------------------------------

def _get_embed_status_text() -> str:
    """Check if current model has missing embeddings."""
    try:
        from managers.database_manager import DatabaseManager
        ms = resolve_model_settings()
        model = ms["hf_name"]
        db = DatabaseManager()
        conn = db.get_connection()
        cur = conn.cursor()

        cur.execute(
            """SELECT COUNT(*) FROM history h
               LEFT JOIN embeddings e
                 ON e.source_table='history' AND e.source_id=h.id
                 AND e.character_id=h.character_id AND e.model_name=?
               WHERE h.content != '' AND h.content IS NOT NULL AND e.id IS NULL""",
            (model,),
        )
        missing_hist = cur.fetchone()[0] or 0

        cur.execute(
            """SELECT COUNT(*) FROM memories m
               LEFT JOIN embeddings e
                 ON e.source_table='memories' AND e.source_id=m.eternal_id
                 AND e.character_id=m.character_id AND e.model_name=?
               WHERE m.is_deleted=0 AND e.id IS NULL""",
            (model,),
        )
        missing_mem = cur.fetchone()[0] or 0
        conn.close()

        total_missing = missing_hist + missing_mem
        if total_missing > 0:
            return _("Нужна переиндексация ({n} записей)", "Reindex needed ({n} records)").format(n=total_missing)
        return _("Актуально", "Up to date")
    except Exception:
        return "?"


def _get_model_download_status() -> str:
    """Check if current model is cached locally."""
    try:
        import sys
        ms = resolve_model_settings()
        hf_name = ms["hf_name"]
        script_dir = os.path.dirname(sys.executable)
        checkpoints_dir = os.path.join(script_dir, "checkpoints")
        cache_dir_name = "models--" + hf_name.replace("/", "--")
        if os.path.isdir(os.path.join(checkpoints_dir, cache_dir_name)):
            return _("Скачана", "Downloaded")
        return _("Не скачана", "Not downloaded")
    except Exception:
        return "?"


def _get_ce_download_status() -> str:
    """Check if the selected cross-encoder model is cached locally."""
    try:
        import sys
        from managers.rag.pipeline.config import resolve_ce_model
        hf_name = resolve_ce_model()
        if not hf_name:
            return _("Не выбрана", "Not selected")
        script_dir = os.path.dirname(sys.executable)
        checkpoints_dir = os.path.join(script_dir, "checkpoints")
        cache_dir_name = "models--" + hf_name.replace("/", "--")
        if os.path.isdir(os.path.join(checkpoints_dir, cache_dir_name)):
            return _("Скачана", "Downloaded") + f" ({hf_name})"
        return _("Не скачана", "Not downloaded") + f" ({hf_name})"
    except Exception:
        return "?"


def _get_ce_loaded_status() -> str:
    """Check if the cross-encoder is currently loaded in memory."""
    try:
        from managers.rag.pipeline.cross_encoder import CrossEncoderReranker
        from managers.rag.pipeline.config import resolve_ce_model
        hf_name = resolve_ce_model()
        inst = CrossEncoderReranker._instances.get(hf_name)
        if inst and inst._model is not None:
            return _("Загружена в память", "Loaded in memory")
        return _("Не загружена", "Not loaded")
    except Exception:
        return "?"


def _refresh_ce_status(gui) -> None:
    """Refresh cross-encoder status labels."""
    try:
        if hasattr(gui, '_ce_dl_label'):
            gui._ce_dl_label.setText(_("Модель:", "Model:") + " " + _get_ce_download_status())
        if hasattr(gui, '_ce_loaded_label'):
            gui._ce_loaded_label.setText(_("Статус:", "Status:") + " " + _get_ce_loaded_status())
        if hasattr(gui, '_ce_dl_btn'):
            gui._ce_dl_btn.setVisible(not _is_ce_model_downloaded())
    except Exception:
        pass


def _refresh_embed_status(gui) -> None:
    """Refresh embedding status labels."""
    try:
        if hasattr(gui, '_embed_dl_label'):
            gui._embed_dl_label.setText(_("Модель:", "Model:") + " " + _get_model_download_status())
        if hasattr(gui, '_embed_status_label'):
            gui._embed_status_label.setText(_("Индекс:", "Index:") + " " + _get_embed_status_text())
        if hasattr(gui, '_embed_dl_btn'):
            gui._embed_dl_btn.setVisible(not _is_embed_model_downloaded())
    except Exception:
        pass


# ---------------------------------------------------------------------------
# Download helpers
# ---------------------------------------------------------------------------

def _is_embed_model_downloaded() -> bool:
    try:
        import sys
        ms = resolve_model_settings()
        hf_name = ms["hf_name"]
        script_dir = os.path.dirname(sys.executable)
        checkpoints_dir = os.path.join(script_dir, "checkpoints")
        cache_dir_name = "models--" + hf_name.replace("/", "--")
        return os.path.isdir(os.path.join(checkpoints_dir, cache_dir_name))
    except Exception:
        return True  # assume downloaded on error to avoid spurious button


def _is_ce_model_downloaded() -> bool:
    try:
        import sys
        from managers.rag.pipeline.config import resolve_ce_model
        hf_name = resolve_ce_model()
        if not hf_name:
            return True
        script_dir = os.path.dirname(sys.executable)
        checkpoints_dir = os.path.join(script_dir, "checkpoints")
        cache_dir_name = "models--" + hf_name.replace("/", "--")
        return os.path.isdir(os.path.join(checkpoints_dir, cache_dir_name))
    except Exception:
        return True


def _download_model_bg(gui, hf_name: str, on_done) -> None:
    """Download *hf_name* in a background thread via HuggingFace Hub."""
    from ui.task_worker import TaskWorker

    def _do_download(*, progress_callback=None):
        import sys
        from huggingface_hub import snapshot_download
        from managers.settings_manager import SettingsManager
        token = str(SettingsManager.get("HF_TOKEN", "") or "").strip() or None
        script_dir = os.path.dirname(sys.executable)
        checkpoints_dir = os.path.join(script_dir, "checkpoints")
        snapshot_download(repo_id=hf_name, cache_dir=checkpoints_dir, token=token)
        return hf_name

    worker = TaskWorker(_do_download)

    def _on_finished(r):
        on_done(success=True)

    def _on_error(msg):
        QMessageBox.critical(gui, _("Ошибка", "Error"),
                             _("Не удалось скачать модель:\n{e}", "Failed to download model:\n{e}").format(e=msg))
        on_done(success=False)

    worker.finished_signal.connect(_on_finished)
    worker.error_signal.connect(_on_error)
    if not hasattr(gui, '_download_workers'):
        gui._download_workers = []
    gui._download_workers.append(worker)
    worker.start()


def _download_embed_model(gui) -> None:
    ms = resolve_model_settings()
    hf_name = ms["hf_name"]
    if hasattr(gui, '_embed_dl_btn'):
        gui._embed_dl_btn.setEnabled(False)
        gui._embed_dl_btn.setText(_("Скачивание...", "Downloading..."))

    def _done(*, success):
        _refresh_embed_status(gui)
        if hasattr(gui, '_embed_dl_btn'):
            gui._embed_dl_btn.setEnabled(True)
            if _is_embed_model_downloaded():
                gui._embed_dl_btn.setVisible(False)
            else:
                gui._embed_dl_btn.setText(_("Скачать модель", "Download model"))

    _download_model_bg(gui, hf_name, _done)


def _download_ce_model(gui) -> None:
    from managers.rag.pipeline.config import resolve_ce_model
    hf_name = resolve_ce_model()
    if not hf_name:
        QMessageBox.warning(gui, _("Ошибка", "Error"), _("Модель не выбрана.", "No model selected."))
        return
    if hasattr(gui, '_ce_dl_btn'):
        gui._ce_dl_btn.setEnabled(False)
        gui._ce_dl_btn.setText(_("Скачивание...", "Downloading..."))

    def _done(*, success):
        _refresh_ce_status(gui)
        if hasattr(gui, '_ce_dl_btn'):
            gui._ce_dl_btn.setEnabled(True)
            if _is_ce_model_downloaded():
                gui._ce_dl_btn.setVisible(False)
            else:
                gui._ce_dl_btn.setText(_("Скачать модель", "Download model"))

    _download_model_bg(gui, hf_name, _done)


# ---------------------------------------------------------------------------
# Reindex / entity extraction / GC / reset
# ---------------------------------------------------------------------------

def _reindex_embeddings(gui) -> None:
    """Run full reindex of embeddings for all characters with progress dialog."""
    from ui.settings.character_settings.logic import FullReindexAllCharactersWorker
    from managers.database_manager import DatabaseManager

    db = DatabaseManager()
    conn = db.get_connection()
    cur = conn.cursor()
    cur.execute("SELECT DISTINCT character_id FROM history")
    cids = [r[0] for r in cur.fetchall() if r[0]]
    conn.close()

    if not cids:
        QMessageBox.information(gui, _("Готово", "Done"), _("Нет персонажей для переиндексации.", "No characters to reindex."))
        return

    worker = FullReindexAllCharactersWorker(cids)

    progress = QProgressDialog(
        _("Переиндексация эмбеддингов...", "Reindexing embeddings..."),
        _("Отмена", "Cancel"), 0, 100, gui,
    )
    progress.setWindowModality(Qt.WindowModality.WindowModal)
    progress.setMinimumDuration(0)
    progress.setMinimumWidth(400)
    progress.setValue(0)

    def on_progress(curr, total):
        try:
            progress.setRange(0, max(int(total), 1))
            progress.setValue(min(int(curr), max(int(total), 1)))
        except Exception:
            pass

    def on_status(status_text):
        try:
            base = _("Переиндексация эмбеддингов", "Reindexing embeddings")
            progress.setLabelText(f"{base}\n{status_text}")
        except Exception:
            pass

    def on_finished(count):
        progress.close()
        QMessageBox.information(
            gui, _("Готово", "Done"),
            _("Переиндексировано: {n}", "Reindexed: {n}").format(n=int(count or 0)),
        )
        _refresh_embed_status(gui)

    def on_error(msg):
        progress.close()
        QMessageBox.critical(gui, _("Ошибка", "Error"), str(msg))

    def on_cancel():
        try:
            worker.requestInterruption()
        except Exception:
            pass
        progress.close()

    worker.progress_signal.connect(on_progress)
    worker.status_signal.connect(on_status)
    worker.finished_signal.connect(on_finished)
    worker.error_signal.connect(on_error)
    progress.canceled.connect(on_cancel)

    gui._embed_reindex_worker = worker
    progress.show()
    worker.start()


def _extract_entities(gui, *, mode: str = "all", skip_existing: bool = True) -> None:
    """Run entity extraction. mode='current'|'all'. skip_existing skips already-processed messages."""
    from managers.database_manager import DatabaseManager
    from managers.rag.graph.graph_store import GraphStore
    from managers.rag.graph.entity_extractor import parse_extraction_response, store_extraction
    from ui.task_worker import TaskWorker

    db = DatabaseManager()
    eb = get_event_bus()

    if mode == "current":
        try:
            res = eb.emit_and_wait(Events.Character.GET_CURRENT_PROFILE, timeout=1.0)
            profile = res[0] if res else {}
            current_cid = (profile or {}).get("character_id", "")
        except Exception:
            current_cid = ""
        if not current_cid:
            QMessageBox.warning(gui, _("Нет персонажа", "No character"),
                                _("Текущий персонаж не выбран.", "No current character selected."))
            return
        cids = [current_cid]
    else:
        conn = db.get_connection()
        cur = conn.cursor()
        cur.execute("SELECT DISTINCT character_id FROM history")
        cids = [r[0] for r in cur.fetchall() if r[0]]
        conn.close()
        if not cids:
            QMessageBox.information(gui, _("Готово", "Done"), _("Нет персонажей.", "No characters."))
            return

    def _do_extract(*, progress_callback=None, status_callback=None, stop_event=None):
        from concurrent.futures import ThreadPoolExecutor, as_completed

        eb2 = get_event_bus()

        def _resolve_graph_preset():
            try:
                res = eb2.emit_and_wait(
                    Events.Settings.GET_SETTING,
                    {"key": "GRAPH_PROVIDER", "default": "Current"},
                    timeout=1.0,
                )
                label = str(res[0] if res else "Current")
            except Exception:
                label = "Current"
            if not label or label in ("Current", "Текущий"):
                return None
            try:
                return int(label)
            except ValueError:
                pass
            try:
                meta_res = eb2.emit_and_wait(Events.ApiPresets.GET_PRESET_LIST, timeout=1.0)
                meta = meta_res[0] if meta_res else None
                if meta:
                    for bucket in ("custom", "builtin"):
                        for pm in (meta.get(bucket) or []):
                            if getattr(pm, "name", None) == label:
                                pid = getattr(pm, "id", None)
                                if isinstance(pid, int):
                                    return pid
            except Exception:
                pass
            return None

        def _get_workers() -> int:
            try:
                res = eb2.emit_and_wait(
                    Events.Settings.GET_SETTING,
                    {"key": "GRAPH_EXTRACTION_WORKERS", "default": 1},
                    timeout=1.0,
                )
                return max(1, int(res[0] if res else 1))
            except Exception:
                return 1

        def _load_prompt_template() -> str:
            """Load extraction prompt from Prompts/Common or return hardcoded default."""
            import os
            try:
                # Try Prompts/Common relative to current working dir.
                for base in ("Prompts", os.path.join("..", "Prompts")):
                    path = os.path.join(base, "System", "graph_extraction_prompt.txt")
                    if os.path.isfile(path):
                        with open(path, "r", encoding="utf-8") as f:
                            return f.read().strip()
            except Exception:
                pass
            from controllers.graph_controller import _DEFAULT_EXTRACTION_PROMPT
            return _DEFAULT_EXTRACTION_PROMPT

        graph_preset_id = _resolve_graph_preset()
        n_workers = _get_workers()
        prompt_template = _load_prompt_template()

        grand_total = 0
        counter_lock = threading.Lock()
        total_processed = 0

        # When skip_existing: filter out messages already processed.
        _skip_sql = """
            AND h.id NOT IN (
                SELECT message_id FROM graph_processed_messages WHERE character_id = ?
                UNION
                SELECT source_message_id FROM graph_relations
                WHERE character_id = ? AND source_message_id IS NOT NULL
            )
        """ if skip_existing else ""

        # Count total work.
        for cid in cids:
            params_extra = (cid, cid) if skip_existing else ()
            with db.connection() as c:
                grand_total += c.execute(
                    f"SELECT COUNT(*) FROM history h WHERE h.character_id=?"
                    f" AND h.content IS NOT NULL AND h.content != '' {_skip_sql}",
                    (cid,) + params_extra,
                ).fetchone()[0] or 0

        # Build flat list of work items: (cid, gs, hid, text)
        work_items = []
        for cid in cids:
            gs = GraphStore(db, cid)
            params_extra = (cid, cid) if skip_existing else ()
            with db.connection() as c:
                rows = c.execute(
                    f"SELECT h.id, h.role, h.content FROM history h"
                    f" WHERE h.character_id=? AND h.content IS NOT NULL AND h.content != ''"
                    f" {_skip_sql} ORDER BY h.id",
                    (cid,) + params_extra,
                ).fetchall() or []

            i = 0
            while i < len(rows):
                hid, role, content = rows[i]
                user_text = assistant_text = ""
                if role == "user":
                    user_text = content.strip()
                    if i + 1 < len(rows) and rows[i + 1][1] != "user":
                        assistant_text = rows[i + 1][2].strip()
                        i += 1
                else:
                    assistant_text = content.strip()
                text = ""
                if user_text:
                    text += f"Player: {user_text}\n"
                if assistant_text:
                    text += f"Character: {assistant_text}\n"
                work_items.append((cid, gs, hid, text.strip()))
                i += 1

        def _process_item(cid, gs, hid, text):
            if not text:
                return
            if stop_event and stop_event.is_set():
                return
            prompt = prompt_template.replace("{text}", text)
            try:
                res = eb2.emit_and_wait(
                    Events.Model.GENERATE_RESPONSE,
                    {
                        "user_input": "",
                        "system_input": prompt,
                        "image_data": [],
                        "stream_callback": None,
                        "message_id": None,
                        "event_type": "graph_extract",
                        "preset_id": graph_preset_id,
                    },
                    timeout=60.0,
                )
                if res and res[0]:
                    parsed = parse_extraction_response(str(res[0]))
                    if parsed:
                        store_extraction(gs, parsed, hid)
            except Exception:
                pass
            try:
                gs.mark_messages_processed([hid])
            except Exception:
                pass

        if n_workers <= 1:
            for cid, gs, hid, text in work_items:
                with counter_lock:
                    idx = total_processed
                    total_processed += 1
                remaining = grand_total - idx
                if status_callback:
                    try:
                        status_callback(_(
                            f"[{cid}] История • {idx + 1}/{grand_total} | Осталось: {remaining}",
                            f"[{cid}] History • {idx + 1}/{grand_total} | Remaining: {remaining}",
                        ))
                    except Exception:
                        pass
                if progress_callback:
                    try:
                        progress_callback(idx, grand_total)
                    except Exception:
                        pass
                _process_item(cid, gs, hid, text)
        else:
            futures = {}
            with ThreadPoolExecutor(max_workers=n_workers) as pool:
                for item in work_items:
                    cid, gs, hid, text = item
                    f = pool.submit(_process_item, cid, gs, hid, text)
                    futures[f] = cid
                for f in as_completed(futures):
                    cid = futures[f]
                    with counter_lock:
                        total_processed += 1
                        idx = total_processed
                    remaining = grand_total - idx
                    if status_callback:
                        try:
                            status_callback(_(
                                f"[{cid}] История • {idx}/{grand_total} | Осталось: {remaining} | Воркеры: {n_workers}",
                                f"[{cid}] History • {idx}/{grand_total} | Remaining: {remaining} | Workers: {n_workers}",
                            ))
                        except Exception:
                            pass
                    if progress_callback:
                        try:
                            progress_callback(idx, grand_total)
                        except Exception:
                            pass

        return total_processed, 0

    global _extr_state

    # If already running — re-open the progress dialog, do NOT start a second worker.
    existing_worker = _extr_state.get('worker')
    if existing_worker and existing_worker.isRunning():
        _attach_extraction_dialog(gui, existing_worker, _extr_state)
        return

    stop_event = threading.Event()
    worker = TaskWorker(_do_extract, use_progress=True)
    worker._kwargs["status_callback"] = worker.status_signal.emit
    worker._kwargs["stop_event"] = stop_event

    _extr_state = {'worker': worker, 'stop': stop_event, 'total': 0, 'last_status': ''}

    def on_status(s):
        _extr_state['last_status'] = s

    def on_finished(result):
        _extr_state['worker'] = None
        processed, skipped = result if isinstance(result, tuple) else (result or 0, 0)
        from managers.settings_manager import SettingsManager
        if SettingsManager.get("GRAPH_GC_AUTO", False):
            _run_entity_gc(gui)
        else:
            QMessageBox.information(
                gui, _("Готово", "Done"),
                _("Обработано: {n}", "Processed: {n}").format(n=int(processed or 0)),
            )

    def on_error(msg):
        _extr_state['worker'] = None
        QMessageBox.critical(gui, _("Ошибка", "Error"), str(msg))

    worker.status_signal.connect(on_status)
    worker.finished_signal.connect(on_finished)
    worker.error_signal.connect(on_error)

    _attach_extraction_dialog(gui, worker, _extr_state)
    worker.start()


def _attach_extraction_dialog(gui, worker, state: dict) -> None:
    """Create (or re-create) a non-modal progress dialog connected to *worker*."""
    progress = QProgressDialog(
        _("Извлечение сущностей...", "Extracting entities..."),
        _("Остановить", "Stop"), 0, 100, gui,
    )
    progress.setWindowModality(Qt.WindowModality.NonModal)
    progress.setMinimumDuration(0)
    progress.setWindowTitle(_("Граф: извлечение", "Graph: extraction"))

    # Restore last known status.
    last = state.get('last_status', '')
    if last:
        progress.setLabelText(last)

    def on_progress(curr, total):
        try:
            progress.setRange(0, max(int(total), 1))
            progress.setValue(min(int(curr), max(int(total), 1)))
        except Exception:
            pass

    def on_finished(_result):
        try:
            progress.close()
        except Exception:
            pass

    def on_cancelled():
        try:
            progress.close()
        except Exception:
            pass

    def on_stop():
        stop = state.get('stop')
        if stop:
            stop.set()
        worker.requestInterruption()
        progress.close()

    worker.progress_signal.connect(on_progress)
    worker.status_signal.connect(progress.setLabelText)
    worker.finished_signal.connect(on_finished)
    worker.cancelled_signal.connect(on_cancelled)
    progress.canceled.connect(on_stop)

    progress.show()


def _run_ttl_cleanup(gui) -> None:
    """Apply TTL cleanup for the current character's memories."""
    try:
        from core.events import get_event_bus, Events
        bus = get_event_bus()
        char_id = getattr(gui, 'current_character_id', None) or getattr(gui, '_current_char_id', None)
        if not char_id:
            try:
                res = bus.emit_and_wait(Events.Character.GET_CURRENT_PROFILE, timeout=1.0)
                char_id = ((res[0] if res else None) or {}).get("character_id", "")
            except Exception:
                char_id = ""
        if not char_id:
            QMessageBox.warning(
                gui,
                _("TTL очистка", "TTL Cleanup"),
                _("Не удалось определить текущего персонажа.", "Could not determine the current character."),
            )
            return
        from managers.memory_manager import MemoryManager
        mm = MemoryManager(char_id)
        count = mm.apply_ttl_cleanup()
        QMessageBox.information(
            gui,
            _("TTL очистка", "TTL Cleanup"),
            _( f"Забыто {count} воспоминаний (is_forgotten=1).",
               f"Forgotten {count} memories (is_forgotten=1)."),
        )
    except Exception as e:
        QMessageBox.critical(
            gui,
            _("Ошибка TTL", "TTL Error"),
            str(e),
        )


def _run_entity_gc(gui, dry_run: bool = False) -> None:
    """Run entity GC for all characters (dry-run shows plan, apply executes it)."""
    from managers.database_manager import DatabaseManager
    from managers.rag.graph.entity_gc import EntityGC
    from ui.task_worker import TaskWorker

    db = DatabaseManager()
    with db.connection() as conn:
        table_exists = conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='graph_entities'"
        ).fetchone()
        if not table_exists:
            QMessageBox.information(gui, _("Готово", "Done"),
                                    _("Нет персонажей с сущностями в графе.", "No characters with entities in graph."))
            return
        cids = [r[0] for r in conn.execute("SELECT DISTINCT character_id FROM graph_entities").fetchall() if r[0]]

    if not cids:
        QMessageBox.information(gui, _("Готово", "Done"),
                                _("Нет персонажей с сущностями в графе.", "No characters with entities in graph."))
        return

    def _do_gc(*, progress_callback=None):
        results = {}
        for i, cid in enumerate(cids):
            gc = EntityGC(db, cid)
            plan = gc.analyze()
            if not dry_run:
                counts = gc.apply(plan)
                results[cid] = counts
            else:
                results[cid] = {"plan": plan.summary()}
            if progress_callback:
                try:
                    progress_callback(i + 1, len(cids))
                except Exception:
                    pass
        return results

    worker = TaskWorker(_do_gc, use_progress=True)

    progress = QProgressDialog(
        _("GC графа сущностей...", "Entity graph GC..."),
        _("Отмена", "Cancel"), 0, len(cids), gui,
    )
    progress.setWindowModality(Qt.WindowModality.WindowModal)
    progress.setMinimumDuration(0)
    progress.setValue(0)

    def on_progress(curr, total):
        try:
            progress.setValue(min(int(curr), max(int(total), 1)))
        except Exception:
            pass

    def on_finished(results):
        progress.close()
        if dry_run:
            lines = [info.get("plan", "") for info in results.values()]
            QMessageBox.information(gui, _("GC — предпросмотр", "GC — dry run"),
                                    "\n\n".join(lines) or _("Нечего чистить.", "Nothing to clean."))
        else:
            summary = "\n".join(
                f"{cid}: del={v.get('delete', 0)} merge={v.get('merge', 0)} rename={v.get('rename', 0)}"
                for cid, v in results.items()
            )
            QMessageBox.information(gui, _("GC завершён", "GC done"), summary)

    def on_error(msg):
        progress.close()
        QMessageBox.critical(gui, _("Ошибка", "Error"), str(msg))

    worker.progress_signal.connect(on_progress)
    worker.finished_signal.connect(on_finished)
    worker.error_signal.connect(on_error)
    progress.canceled.connect(lambda: worker.requestInterruption())

    gui._entity_gc_worker = worker
    progress.show()
    worker.start()


def _delete_all_graph_data(gui) -> None:
    """Delete all graph entities and relations for all characters after confirmation."""
    from managers.database_manager import DatabaseManager

    db = DatabaseManager()
    with db.connection() as conn:
        entity_count = 0
        relation_count = 0
        for tbl, col in (("graph_entities", None), ("graph_relations", None)):
            exists = conn.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (tbl,)
            ).fetchone()
            if exists:
                cnt = conn.execute(f"SELECT COUNT(*) FROM {tbl}").fetchone()[0]
                if tbl == "graph_entities":
                    entity_count = cnt
                else:
                    relation_count = cnt

    if entity_count == 0 and relation_count == 0:
        QMessageBox.information(
            gui, _("Граф", "Graph"),
            _("Граф пуст, удалять нечего.", "Graph is already empty.")
        )
        return

    answer = QMessageBox.question(
        gui,
        _("Удалить весь граф?", "Delete all graph data?"),
        _(
            f"Будет удалено {entity_count} сущностей и {relation_count} связей для всех персонажей.\n"
            "Это действие необратимо. Продолжить?",
            f"This will delete {entity_count} entities and {relation_count} relations for all characters.\n"
            "This action cannot be undone. Continue?"
        ),
        QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        QMessageBox.StandardButton.No,
    )
    if answer != QMessageBox.StandardButton.Yes:
        return

    with db.connection() as conn:
        for tbl in ("graph_relations", "graph_entity_aliases", "graph_entities"):
            exists = conn.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (tbl,)
            ).fetchone()
            if exists:
                conn.execute(f"DELETE FROM {tbl}")
        conn.commit()

    QMessageBox.information(
        gui, _("Готово", "Done"),
        _(
            f"Удалено {entity_count} сущностей и {relation_count} связей.",
            f"Deleted {entity_count} entities and {relation_count} relations."
        )
    )


# ---------------------------------------------------------------------------
# Config builders — each returns a list of setting descriptors
# ---------------------------------------------------------------------------

# ─────────────────────────────────────────────────────────────────
# Pipeline preset helpers
# ─────────────────────────────────────────────────────────────────

def _load_user_presets() -> dict:
    from managers.settings_manager import SettingsManager
    try:
        raw = SettingsManager.get("RAG_PIPELINE_USER_PRESETS", "{}") or "{}"
        return json.loads(raw)
    except Exception:
        return {}


def _save_user_presets(presets: dict) -> None:
    from managers.settings_manager import SettingsManager
    SettingsManager.set("RAG_PIPELINE_USER_PRESETS", json.dumps(presets, ensure_ascii=False))


def _update_preset_delete_btn(gui, name: str) -> None:
    btn = getattr(gui, '_preset_delete_btn', None)
    if btn is not None:
        btn.setEnabled(name not in RAG_PIPELINE_PRESETS and name != "Custom")


def _refresh_preset_combo(gui) -> None:
    combo = getattr(gui, 'RAG_PIPELINE_PRESET', None)
    if combo is None:
        return
    user_presets = _load_user_presets()
    current = combo.currentText()
    combo.blockSignals(True)
    combo.clear()
    combo.addItems(list_pipeline_preset_names(user_presets))
    if combo.findText(current) >= 0:
        combo.setCurrentText(current)
    else:
        combo.setCurrentText("Custom")
    combo.blockSignals(False)
    _update_preset_delete_btn(gui, combo.currentText())


def _on_apply_preset(gui) -> None:
    combo = getattr(gui, 'RAG_PIPELINE_PRESET', None)
    if combo is None:
        return
    name = combo.currentText()
    if name == "Custom":
        return

    msg = QMessageBox(gui)
    msg.setWindowTitle(_("Применить пресет", "Apply preset"))
    msg.setText(
        _("Применить пресет «{n}»?\nТекущие настройки RAG будут заменены.",
          "Apply preset «{n}»?\nCurrent RAG settings will be replaced.").format(n=name)
    )
    save_btn   = msg.addButton(
        _("Сохранить текущие и применить", "Save current & Apply"),
        QMessageBox.ButtonRole.AcceptRole,
    )
    apply_btn  = msg.addButton(_("Применить", "Apply"), QMessageBox.ButtonRole.DestructiveRole)
    cancel_btn = msg.addButton(_("Отмена", "Cancel"), QMessageBox.ButtonRole.RejectRole)
    msg.setDefaultButton(cancel_btn)
    msg.exec()

    clicked = msg.clickedButton()
    if clicked is cancel_btn:
        return
    if clicked is save_btn:
        if not _on_save_preset(gui):
            return  # user cancelled save

    user_presets = _load_user_presets()
    settings = get_pipeline_preset_settings(name, user_presets)
    if settings is None:
        return
    for k, v in settings.items():
        gui._save_setting(k, v)
        widget = getattr(gui, k, None)
        if widget is None:
            continue
        if isinstance(widget, QCheckBox):
            widget.setChecked(bool(v))
        elif isinstance(widget, QComboBox):
            widget.setCurrentText(str(v))
        elif isinstance(widget, QLineEdit):
            widget.setText(str(v))


def _on_save_preset(gui) -> bool:
    """Save current RAG settings as a named preset. Returns True if saved."""
    name, ok = QInputDialog.getText(
        gui,
        _("Сохранить пресет", "Save preset"),
        _("Название пресета:", "Preset name:"),
    )
    if not ok or not str(name or "").strip():
        return False
    name = str(name).strip()

    if name in RAG_PIPELINE_PRESETS:
        QMessageBox.warning(
            gui,
            _("Ошибка", "Error"),
            _("Нельзя перезаписать встроенный пресет «{n}».",
              "Cannot overwrite built-in preset «{n}».").format(n=name),
        )
        return False

    snapshot = {k: gui.settings.get(k, RAG_DEFAULTS[k]) for k in RAG_DEFAULTS}
    user_presets = _load_user_presets()
    user_presets[name] = snapshot
    _save_user_presets(user_presets)
    gui._save_setting("RAG_PIPELINE_PRESET", name)
    _refresh_preset_combo(gui)
    combo = getattr(gui, 'RAG_PIPELINE_PRESET', None)
    if combo is not None:
        combo.blockSignals(True)
        combo.setCurrentText(name)
        combo.blockSignals(False)
    return True


def _on_delete_preset(gui) -> None:
    combo = getattr(gui, 'RAG_PIPELINE_PRESET', None)
    if combo is None:
        return
    name = combo.currentText()
    if name in RAG_PIPELINE_PRESETS or name == "Custom":
        return

    reply = QMessageBox.question(
        gui,
        _("Удалить пресет", "Delete preset"),
        _("Удалить пресет «{n}»?", "Delete preset «{n}»?").format(n=name),
        QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
    )
    if reply != QMessageBox.StandardButton.Yes:
        return

    user_presets = _load_user_presets()
    user_presets.pop(name, None)
    _save_user_presets(user_presets)
    gui._save_setting("RAG_PIPELINE_PRESET", "Custom")
    _refresh_preset_combo(gui)
    combo = getattr(gui, 'RAG_PIPELINE_PRESET', None)
    if combo is not None:
        combo.blockSignals(True)
        combo.setCurrentText("Custom")
        combo.blockSignals(False)


def _build_pipeline_preset_config(gui) -> list:
    user_presets = _load_user_presets()
    return [
        {'label': _('Пресет пайплайна', 'Pipeline Preset'), 'type': 'subsection'},
        {'label': _('Пресет', 'Preset'),
         'key': 'RAG_PIPELINE_PRESET', 'type': 'combobox',
         'options': list_pipeline_preset_names(user_presets),
         'default': 'Custom',
         'command': lambda text: _update_preset_delete_btn(gui, text),
         'tooltip': _(
             'Выберите пресет и нажмите «Применить». Custom — ручная настройка.',
             'Select a preset and click «Apply». Custom — manual configuration.',
         )},
        {'type': 'button_group', 'buttons': [
            {'label': _('Применить', 'Apply'),
             'command': lambda: _on_apply_preset(gui)},
            {'label': _('Сохранить как...', 'Save as...'),
             'command': lambda: _on_save_preset(gui)},
            {'label': _('Удалить', 'Delete'),
             'command': lambda: _on_delete_preset(gui),
             'widget_name': '_preset_delete_btn'},
        ]},
        {'type': 'end'},
    ]


def _build_memory_limits_config(self) -> list:
    return [
        {'label': _('Лимит сообщений', 'Message limit'), 'key': 'MODEL_MESSAGE_LIMIT',
         'type': 'entry', 'default': 40,
         'tooltip': _('Сколько сообщений будет помнить мита', 'How much messages Mita will remember')},
        {'label': _('Лимит воспоминаний', 'Active memory limit (MEMORY_CAPACITY)'),
         'key': 'MEMORY_CAPACITY', 'type': 'entry', 'default': 75,
         'validation': self.validate_positive_integer,
         'tooltip': _(
             'Максимум активных воспоминаний (не удалённых и не забытых). При превышении система помечает одно как is_forgotten=1.',
             'Maximum number of active memories (not deleted and not forgotten). When exceeded, the system marks one as is_forgotten=1.')},

        {'label': _('TTL-забывание памяти', 'Memory TTL (auto-forget)'), 'type': 'subsection'},
        {'label': _('Включить TTL-забывание', 'Enable memory TTL'),
         'key': 'MEMORY_TTL_ENABLED', 'type': 'checkbutton', 'default_checkbutton': False,
         'tooltip': _(
             'Автоматически помечать старые воспоминания низкого/обычного приоритета как забытые (is_forgotten=1). '
             'Они не попадают в промпт, но всё ещё доступны через RAG.',
             'Automatically mark old low/normal-priority memories as forgotten (is_forgotten=1). '
             'They are excluded from the prompt but still searchable via RAG.')},
        {'label': _('TTL для Low-приоритета (дней)', 'TTL for Low priority (days)'),
         'key': 'MEMORY_TTL_LOW_DAYS', 'type': 'entry', 'default': 30,
         'validation': self.validate_positive_integer,
         'depends_on': 'MEMORY_TTL_ENABLED',
         'tooltip': _(
             'Через сколько дней Low-приоритетные воспоминания автоматически забываются. 0 = выключено.',
             'Days after which Low-priority memories are auto-forgotten. 0 = disabled.')},
        {'label': _('TTL для Normal-приоритета (дней)', 'TTL for Normal priority (days)'),
         'key': 'MEMORY_TTL_NORMAL_DAYS', 'type': 'entry', 'default': 0,
         'validation': self.validate_positive_integer_or_zero,
         'depends_on': 'MEMORY_TTL_ENABLED',
         'tooltip': _(
             'Через сколько дней Normal-приоритетные воспоминания автоматически забываются. 0 = выключено.',
             'Days after which Normal-priority memories are auto-forgotten. 0 = disabled.')},
        {'type': 'button_group', 'buttons': [
            {'label': _('Применить TTL сейчас', 'Apply TTL cleanup now'),
             'command': lambda: _run_ttl_cleanup(self)},
        ]},

        {'type': 'end'},
    ]


def _build_history_compression_config(self, hc_provider_names) -> list:
    return [
        {'label': _('Сжатие истории', 'History compression'), 'type': 'subsection',
         'depends_on': 'RAG_ENABLED'},

        {'label': _('Сжимать историю при достижении лимита', 'Compress history on limit'),
         'key': 'ENABLE_HISTORY_COMPRESSION_ON_LIMIT', 'type': 'checkbutton',
         'default_checkbutton': False,
         'tooltip': _('Включить автоматическое сжатие истории чата, когда количество сообщений превышает лимит.',
                      'Enable automatic chat history compression when message count exceeds a limit.')},
        {'label': _('Периодическое сжатие истории', 'Periodic history compression'),
         'key': 'ENABLE_HISTORY_COMPRESSION_PERIODIC', 'type': 'checkbutton',
         'default_checkbutton': False,
         'tooltip': _('Включить автоматическое сжатие истории чата через заданные интервалы.',
                      'Enable automatic chat history compression at specified intervals.')},
        {'label': _('Интервал периодического сжатия (сообщения)', 'Periodic compression interval (messages)'),
         'key': 'HISTORY_COMPRESSION_PERIODIC_INTERVAL', 'type': 'entry',
         'default': 20, 'validation': self.validate_positive_integer,
         'tooltip': _('Количество сообщений, после которых будет произведено периодическое сжатие истории.',
                      'Number of messages after which periodic history compression will occur.')},
        {'label': _('Шаблон промпта для сжатия', 'Compression prompt template'),
         'key': 'HISTORY_COMPRESSION_PROMPT_TEMPLATE', 'type': 'entry',
         'default': "Prompts/System/compression_prompt.txt",
         'tooltip': _('Путь к файлу шаблона промпта, используемого для сжатия истории.',
                      'Path to the prompt template file used for history compression.')},
        {'label': _('Процент для сжатия', 'Percent to compress'),
         'key': 'HISTORY_COMPRESSION_MIN_PERCENT_TO_COMPRESS', 'type': 'entry',
         'default': 0.85, 'validation': self.validate_float_0_1,
         'tooltip': _('Минимальное количество сообщений в истории, необходимое для запуска процесса сжатия.',
                      'Minimum number of messages in history required to trigger compression.')},
        {'label': _('Цель вывода сжатой истории', 'Compressed history output target'),
         'key': 'HISTORY_COMPRESSION_OUTPUT_TARGET', 'type': 'combobox',
         'options': ['history', 'memory'], 'default': "history",
         'tooltip': _('Куда помещать результат сжатия истории (например, "memory", "summary_message").',
                      'Where to place the compressed history output (e.g., "memory", "summary_message").')},
        {'label': _('Провайдер для сжатия', 'Provider for compression'),
         'key': 'HC_PROVIDER', 'type': 'combobox',
         'options': hc_provider_names, 'default': _('Текущий', 'Current')},

        {'type': 'end'},
    ]


def _build_rag_core_config(self) -> list:
    return [
        {'label': _('RAG и память', 'RAG & Memory'), 'type': 'subsection'},

        {'label': _('Включить RAG (требует перезагрузки)', 'Enable RAG (requires restart)'),
         'key': 'RAG_ENABLED', 'type': 'checkbutton', 'default_checkbutton': False,
         'tooltip': _('Включает систему RAG. Если выключено, модель эмбеддингов не загружается.',
                      'Enables the RAG system. If disabled, the embedding model is not loaded.')},
        {'label': _('Искать в памяти', 'Search in memory'),
         'key': 'RAG_SEARCH_MEMORY', 'type': 'checkbutton', 'default_checkbutton': True,
         'depends_on': 'RAG_ENABLED'},
        {'label': _('Искать в истории', 'Search in history'),
         'key': 'RAG_SEARCH_HISTORY', 'type': 'checkbutton', 'default_checkbutton': True,
         'depends_on': 'RAG_ENABLED'},
        {'label': _('Макс. результатов RAG', 'RAG max results'),
         'key': 'RAG_MAX_RESULTS', 'type': 'entry', 'default': 10,
         'validation': self.validate_positive_integer,
         'tooltip': _('Сколько фрагментов RAG добавлять в system prompt.',
                      'How many RAG chunks to inject into the system prompt.'),
         'depends_on': 'RAG_ENABLED'},
        {'label': _('Порог схожести (Sim threshold)', 'Similarity threshold (Sim threshold)'),
         'key': 'RAG_SIM_THRESHOLD', 'type': 'entry', 'default': 0.30,
         'validation': self.validate_float_0_to_1,
         'tooltip': _('Минимальная косинусная схожесть для кандидата (0..1).',
                      'Minimum cosine similarity for a candidate (0..1).'),
         'depends_on': 'RAG_ENABLED'},

        {'type': 'end'},
    ]


def _build_embed_config(self) -> list:
    return [
        {'label': _('Модель эмбеддингов', 'Embedding Model'), 'type': 'subsection',
         'depends_on': 'RAG_ENABLED'},

        {'label': _('Векторный поиск (локальная модель)', 'Vector search (local model)'),
         'key': 'RAG_VECTOR_SEARCH_ENABLED', 'type': 'checkbutton', 'default_checkbutton': False,
         'tooltip': _('Включает векторный поиск через локальную модель эмбеддингов (torch/transformers). '
                      'Выключите, если torch недоступен — RAG продолжит работать только на FTS/keyword.',
                      'Enables vector search via a local embedding model (torch/transformers). '
                      'Disable if torch is unavailable — RAG will fall back to FTS/keyword only.'),
         'depends_on': 'RAG_ENABLED'},

        {'label': _('Модель', 'Model'),
         'key': 'RAG_EMBED_MODEL', 'type': 'combobox',
         'options': list_preset_names(), 'default': 'Snowflake Arctic M v2.0',
         'tooltip': _('Выберите пресет или "Custom" для ручного ввода HuggingFace модели.',
                      'Choose a preset or "Custom" for manual HuggingFace model input.'),
         'depends_on': 'RAG_ENABLED'},
        {'label': _('HF имя модели (Custom)', 'HF model name (Custom)'),
         'key': 'RAG_EMBED_MODEL_CUSTOM', 'type': 'entry', 'default': '',
         'depends_on': 'RAG_EMBED_MODEL', 'depends_on_value': 'Custom', 'hide_when_disabled': True,
         'tooltip': _('Полное имя модели на HuggingFace, напр. "BAAI/bge-m3".',
                      'Full HuggingFace model name, e.g. "BAAI/bge-m3".')},
        {'label': _('Префикс запроса (Custom)', 'Query prefix (Custom)'),
         'key': 'RAG_EMBED_QUERY_PREFIX', 'type': 'entry', 'default': '',
         'depends_on': 'RAG_EMBED_MODEL', 'depends_on_value': 'Custom', 'hide_when_disabled': True,
         'tooltip': _('Префикс, добавляемый перед текстом запроса (напр. "query: ").',
                      'Prefix prepended to query text (e.g. "query: ").')},
        {'label': _('HuggingFace токен', 'HuggingFace token'),
         'key': 'HF_TOKEN', 'type': 'entry', 'default': '',
         'hide': bool(self.settings.get("HIDE_PRIVATE")),
         'depends_on': 'RAG_ENABLED',
         'tooltip': _('Токен HuggingFace для ускорения загрузки и доступа к gated-моделям.',
                      'HuggingFace token for faster downloads and gated model access.')},
        {'type': 'button_group', 'buttons': [
            {'label': _('Переиндексировать эмбеддинги', 'Reindex embeddings'),
             'command': lambda: _reindex_embeddings(self)},
            {'label': _('Обновить статус', 'Refresh status'),
             'command': lambda: _refresh_embed_status(self)},
        ]},

        {'type': 'end'},
    ]


def _build_graph_config(self, hc_provider_names) -> list:
    return [
        {'label': _('Граф знаний (экстракция сущностей)', 'Knowledge Graph (entity extraction)'),
         'type': 'subsection'},

        {'label': _('Включить экстракцию сущностей', 'Enable entity extraction'),
         'key': 'GRAPH_EXTRACTION_ENABLED', 'type': 'checkbutton', 'default_checkbutton': False,
         'tooltip': _('Извлекать сущности и связи из диалога через LLM-провайдер и сохранять в граф.',
                      'Extract entities and relations from dialogue via LLM provider and store in graph.')},
        {'label': _('Inline-режим (основная модель, без доп. запроса)', 'Inline mode (main model, no extra call)'),
         'key': 'GRAPH_EXTRACTION_INLINE', 'type': 'checkbutton', 'default_checkbutton': False,
         'depends_on': 'GRAPH_EXTRACTION_ENABLED',
         'tooltip': _('Основная модель сама пишет <graph>JSON</graph> в ответе — отдельный API-вызов не нужен. '
                      'Если выключено, используется отдельный провайдер ниже.',
                      'Main model embeds <graph>JSON</graph> in its response — no extra API call. '
                      'If disabled, a separate provider call is used instead.')},
        {'label': _('Реал-тайм экстракция (после каждого ответа)', 'Real-time extraction (after each reply)'),
         'key': 'GRAPH_EXTRACTION_REALTIME', 'type': 'checkbutton', 'default_checkbutton': False,
         'depends_on': 'GRAPH_EXTRACTION_ENABLED',
         'tooltip': _('Автоматически извлекать сущности после каждого ответа модели. '
                      'Если выключено — только ручная batch-экстракция кнопками ниже. '
                      'По умолчанию выключено, чтобы не конкурировать с основной моделью за LLM.',
                      'Automatically extract entities after every model reply. '
                      'If disabled — only manual batch extraction via buttons below. '
                      'Off by default to avoid competing with the main model for the LLM slot.')},
        {'label': _('Провайдер для экстракции графа', 'Provider for graph extraction'),
         'key': 'GRAPH_PROVIDER', 'type': 'combobox',
         'options': hc_provider_names, 'default': _('Текущий', 'Current'),
         'depends_on': 'GRAPH_EXTRACTION_ENABLED',
         'tooltip': _('Провайдер для экстракции (используется только если inline-режим выключен). '
                      'Текущий = та же модель, но отдельным запросом после ответа.',
                      'Provider for extraction (only used when inline mode is off). '
                      'Current = same model, but as a separate request after the response.')},
        {'label': _('Искать в графе знаний при RAG', 'Search knowledge graph in RAG'),
         'key': 'RAG_SEARCH_GRAPH', 'type': 'checkbutton', 'default_checkbutton': False,
         'depends_on': 'GRAPH_EXTRACTION_ENABLED',
         'tooltip': _('Включает поиск в графе сущностей при RAG-запросе.',
                      'Enables entity graph search during RAG queries.')},
        {'label': _('Минимум результатов из графа', 'Min graph results'),
         'key': 'RAG_GRAPH_MIN_RESULTS', 'type': 'entry', 'default': 0,
         'validation': self.validate_positive_integer_or_zero,
         'depends_on': 'RAG_SEARCH_GRAPH',
         'tooltip': _('Минимальное количество граф-трипл в выдаче RAG (0 = без гарантий). '
                      'Гарантирует присутствие знаний из графа даже если они проигрывают по score.',
                      'Minimum number of graph triples guaranteed in RAG output (0 = no guarantee). '
                      'Ensures graph knowledge appears even if outscored by history/memories.')},
        {'label': _('Авто-очистка графа (GC) после экстракции', 'Auto-clean graph (GC) after extraction'),
         'key': 'GRAPH_GC_AUTO', 'type': 'checkbutton', 'default_checkbutton': False,
         'depends_on': 'GRAPH_EXTRACTION_ENABLED',
         'tooltip': _('Автоматически запускать сборщик мусора графа после каждой экстракции сущностей. '
                      'Удаляет мусор, дубли, объединяет синонимы.',
                      'Automatically run entity graph GC after each extraction. '
                      'Removes garbage entities, duplicates, merges synonyms.')},
        {'label': _('Параллельных воркеров (batch-экстракция)', 'Parallel workers (batch extraction)'),
         'key': 'GRAPH_EXTRACTION_WORKERS', 'type': 'entry', 'default': 1,
         'validation': self.validate_positive_integer,
         'depends_on': 'GRAPH_EXTRACTION_ENABLED',
         'tooltip': _('Сколько потоков одновременно отправляют запросы при batch-извлечении сущностей. '
                      '1 = последовательно (по умолчанию). '
                      'Увеличивай если LM Studio настроен на Parallel Requests > 1 и есть запас VRAM.',
                      'How many threads send requests concurrently during batch entity extraction. '
                      '1 = sequential (default). '
                      'Increase if LM Studio is configured with Parallel Requests > 1 and you have spare VRAM.')},
        {'type': 'button_group', 'buttons': [
            {'label': _('Текущий (только новые)', 'Current char (new only)'),
             'command': lambda: _extract_entities(self, mode='current', skip_existing=True)},
            {'label': _('Все (только новые)', 'All chars (new only)'),
             'command': lambda: _extract_entities(self, mode='all', skip_existing=True)},
        ]},
        {'type': 'button_group', 'buttons': [
            {'label': _('Текущий (заново)', 'Current char (redo all)'),
             'command': lambda: _extract_entities(self, mode='current', skip_existing=False)},
            {'label': _('Все (заново)', 'All chars (redo all)'),
             'command': lambda: _extract_entities(self, mode='all', skip_existing=False)},
        ]},
        {'type': 'button_group', 'buttons': [
            {'label': _('Очистить граф (GC)', 'Clean graph (GC)'),
             'command': lambda: _run_entity_gc(self)},
            {'label': _('Предпросмотр GC', 'Preview GC'),
             'command': lambda: _run_entity_gc(self, dry_run=True)},
        ]},
        {'type': 'button_group', 'buttons': [
            {'label': _('Удалить весь граф', 'Delete all graph data'),
             'command': lambda: _delete_all_graph_data(self)},
        ]},

        {'label': _('Дедупликация памяти (векторная)', 'Memory deduplication (vector)'), 'type': 'subsection'},
        {'label': _('Порог косинусного сходства', 'Cosine similarity threshold'),
         'key': 'MEMORY_DEDUP_THRESHOLD', 'type': 'entry', 'default': 0.94,
         'validation': self.validate_float_0_to_1,
         'tooltip': _(
             'Порог сходства эмбеддингов для считывания двух воспоминаний дублями (0–1). '
             'Чем выше — тем строже. Возрастной decay корректирует порог автоматически.',
             'Embedding similarity threshold for treating two memories as duplicates (0–1). '
             'Higher = stricter. Age-based decay adjusts the threshold automatically.')},
        {'label': _('Возрастной decay порога', 'Age-based threshold decay'),
         'key': 'MEMORY_DEDUP_AGE_DECAY', 'type': 'checkbutton', 'default_checkbutton': True,
         'tooltip': _(
             'Строже для свежих (<7 дн: +0.03) и мягче для старых (>30 дн: −0.04) воспоминаний.',
             'Stricter for fresh (<7d: +0.03) and looser for old (>30d: −0.04) memories.')},
        {'type': 'button_group', 'buttons': [
            {'label': _('Найти дубли (превью)', 'Find duplicates (preview)'),
             'command': lambda: _run_memory_dedup(self, dry_run=True)},
            {'label': _('Слить дубли', 'Merge duplicates'),
             'command': lambda: _run_memory_dedup(self, dry_run=False)},
        ]},

        {'type': 'end'},
    ]


def _run_memory_dedup(gui, dry_run: bool = True) -> None:
    """Analyze or apply vector-based memory deduplication for the current character."""
    try:
        char_id = getattr(gui, 'current_character_id', None) or getattr(gui, '_current_char_id', None)
        if not char_id:
            try:
                res = get_event_bus().emit_and_wait(Events.Character.GET_CURRENT_PROFILE, timeout=1.0)
                char_id = ((res[0] if res else None) or {}).get("character_id", "")
            except Exception:
                char_id = ""
        if not char_id:
            QMessageBox.warning(
                gui,
                _("Дедупликация", "Deduplication"),
                _("Не удалось определить текущего персонажа.", "Could not determine the current character."),
            )
            return

        from managers.memory_dedup import MemoryDeduplicator
        dedup = MemoryDeduplicator(char_id)

        try:
            plan = dedup.analyze()
        except ImportError:
            QMessageBox.warning(
                gui,
                _("Дедупликация", "Deduplication"),
                _("numpy не установлен — векторная дедупликация недоступна.",
                  "numpy is not installed — vector deduplication is unavailable."),
            )
            return

        if len(plan) == 0:
            QMessageBox.information(
                gui,
                _("Дедупликация", "Deduplication"),
                _("Дублей не найдено (или эмбеддинги ещё не посчитаны).",
                  "No duplicates found (or embeddings are not yet computed)."),
            )
            return

        if dry_run:
            lines = [_("Найдены потенциальные дубли:", "Potential duplicates found:")]
            for p in plan.pairs:
                sim_pct = f"{p.similarity * 100:.1f}%"
                src_preview = p.source_content[:60].replace("\n", " ")
                tgt_preview = p.target_content[:60].replace("\n", " ")
                lines.append(
                    f"  #{p.source_id} → #{p.target_id}  [{sim_pct}]\n"
                    f"    src: {src_preview}\n"
                    f"    tgt: {tgt_preview}"
                )
            QMessageBox.information(
                gui,
                _("Дедупликация — предпросмотр", "Deduplication — preview"),
                "\n\n".join(lines),
            )
        else:
            confirm = QMessageBox.question(
                gui,
                _("Слить дубли?", "Merge duplicates?"),
                _( f"Будет слито {len(plan)} пар воспоминаний. Продолжить?",
                   f"Will merge {len(plan)} memory pairs. Continue?"),
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            )
            if confirm != QMessageBox.StandardButton.Yes:
                return

            from managers.memory_manager import MemoryManager
            mm = MemoryManager(char_id)
            result = dedup.apply(plan, mm)
            QMessageBox.information(
                gui,
                _("Дедупликация завершена", "Deduplication complete"),
                _( f"Слито: {result['merged']}, ошибок: {result['failed']}.",
                   f"Merged: {result['merged']}, failed: {result['failed']}."),
            )

    except Exception as e:
        QMessageBox.critical(
            gui,
            _("Ошибка дедупликации", "Deduplication error"),
            str(e),
        )


def _build_query_tail_config(self) -> list:
    return [
        {'label': _('Хвост сообщений', 'Query tail'), 'type': 'subsection'},

        {'label': _('Хвост сообщений для query (1-3)', 'Query tail messages (1-3)'),
         'key': 'RAG_QUERY_TAIL_MESSAGES', 'type': 'entry', 'default': 1,
         'validation': self.validate_positive_integer,
         'tooltip': _('Сколько последних активных сообщений (user/assistant) использовать для построения query-строки.',
                      'How many last active messages (user/assistant) to use when building the query string.'),
         'depends_on': 'RAG_ENABLED'},
        {'label': _('Режим эмбеддинга запроса', 'Query embedding mode'),
         'key': 'RAG_QUERY_EMBED_MODE', 'type': 'combobox', 'default': 'weighted',
         'options': ['concat', 'weighted'],
         'tooltip': _(
             'Режим объединения сообщений для построения запроса к памяти: "concat" (конкатенация) или "weighted" (взвешенный).',
             'Mode for combining messages to build the memory query: "concat" (concatenation) or "weighted".')},
        {'label': _('Вес последнего сообщения пользователя (Weighted)', 'Last user message weight (Weighted)'),
         'key': 'RAG_QUERY_WEIGHT_LAST_USER', 'type': 'entry', 'default': 0.85,
         'validation': self.validate_float_0_to_1,
         'tooltip': _('Вес последнего сообщения пользователя в режиме "weighted".',
                      'Weight of the last user message in "weighted" mode.')},
        {'label': _('Вес предыдущего контекста (Weighted)', 'Previous context weight (Weighted)'),
         'key': 'RAG_QUERY_WEIGHT_PREV_CONTEXT', 'type': 'entry', 'default': 0.15,
         'validation': self.validate_float_0_to_1,
         'tooltip': _('Вес предыдущего контекста (остальных сообщений) в режиме "weighted".',
                      'Weight of the previous context (remaining messages) in "weighted" mode.')},
        {'label': _('Фильтр ролей для хвоста (Weighted)', 'Tail role filter (Weighted)'),
         'key': 'RAG_QUERY_TAIL_ROLE_FILTER', 'type': 'combobox', 'default': 'user_only',
         'options': ['user_only', 'user_and_assistant', 'assistant_only'],
         'tooltip': _(
             'Какие роли сообщений включать в хвост для построения запроса в режиме "weighted".',
             'Which message roles to include in the tail for query building in "weighted" mode.')},
        {'label': _('Экспоненциальное затухание веса хвоста (Weighted)', 'Tail weight exponential decay (Weighted)'),
         'key': 'RAG_QUERY_TAIL_EXP_DECAY', 'type': 'entry', 'default': 0.6,
         'validation': self.validate_float_0_to_1,
         'tooltip': _(
             'Коэффициент экспоненциального затухания веса: чем ближе сообщение к последнему, тем больше его вес. Используется в режиме "weighted".',
             'Exponential decay factor for weight: the closer a message is to the last one, the higher its weight. Used in "weighted" mode.')},
        {'label': _('Макс. символов в хвосте сообщений (Weighted)', 'Max chars in tail messages (Weighted)'),
         'key': 'RAG_QUERY_TAIL_MAX_CHARS', 'type': 'entry', 'default': 1200,
         'validation': self.validate_positive_integer,
         'tooltip': _(
             'Максимальное количество символов, которое будет использовано из хвостовых сообщений в режиме "weighted".',
             'Maximum number of characters to use from the tail messages in "weighted" mode.')},
        {'label': _('Fallback на Keywords при ошибке эмбеддинга', 'Keyword fallback on embedding error'),
         'key': 'RAG_FALLBACK_KEYWORD', 'type': 'checkbutton', 'default_checkbutton': True,
         'tooltip': _(
             'Если не удалось получить эмбеддинг запроса, но включен поиск по ключевым словам и ключевые слова есть, использовать только поиск по ключевым словам.',
             'If query embedding fails, but keyword search is enabled and keywords exist, use keyword-only search.')},

        {'type': 'end'},
    ]


def _build_weights_config(self) -> list:
    return [
        {'label': _('Веса и затухание', 'Weights & decay'), 'type': 'subsection',
         'depends_on': 'RAG_ENABLED'},

        {'label': _('Вес схожести K1', 'Similarity weight K1'),
         'key': 'RAG_WEIGHT_SIMILARITY', 'type': 'entry', 'default': 1.0,
         'validation': self.validate_float_positive_or_zero, 'depends_on': 'RAG_ENABLED'},
        {'label': _('Вес времени K2 (history)', 'Time weight K2 (history)'),
         'key': 'RAG_WEIGHT_TIME', 'type': 'entry', 'default': 0.3,
         'validation': self.validate_float_positive_or_zero, 'depends_on': 'RAG_ENABLED'},
        {'label': _('Вес приоритета K3 (memories)', 'Priority weight K3 (memories)'),
         'key': 'RAG_WEIGHT_PRIORITY', 'type': 'entry', 'default': 0.5,
         'validation': self.validate_float_positive_or_zero, 'depends_on': 'RAG_ENABLED'},
        {'label': _('Вес сущностей K4', 'Entity weight K4'),
         'key': 'RAG_WEIGHT_ENTITY', 'type': 'entry', 'default': 0.5,
         'validation': self.validate_float_positive_or_zero, 'depends_on': 'RAG_ENABLED'},
        {'label': _('Скорость затухания (decay_rate)', 'Decay rate (decay_rate)'),
         'key': 'RAG_TIME_DECAY_RATE', 'type': 'entry', 'default': 0.05,
         'validation': self.validate_float_positive_or_zero,
         'tooltip': _('TimeFactor = 1/(1+decay_rate*days). Чем больше decay_rate, тем сильнее штраф старым сообщениям.',
                      'TimeFactor = 1/(1+decay_rate*days). Higher decay_rate penalizes older messages more.'),
         'depends_on': 'RAG_ENABLED'},
        {'label': _('Шум (serendipity) максимум', 'Noise (serendipity) max'),
         'key': 'RAG_NOISE_MAX', 'type': 'entry', 'default': 0.02,
         'validation': self.validate_float_0_to_1,
         'tooltip': _('Случайная добавка 0..NoiseMax для редких неожиданных совпадений.',
                      'Random bonus 0..NoiseMax for occasional unexpected matches.'),
         'depends_on': 'RAG_ENABLED'},

        {'type': 'end'},
    ]


def _build_keyword_config(self) -> list:
    return [
        {'label': _("Поиск по ключевым словам", "Keyword Search"), 'type': 'subsection',
         'depends_on': 'RAG_ENABLED'},

        {'label': _('Включить поиск по ключевым словам', 'Enable keyword search'),
         'key': 'RAG_KEYWORD_SEARCH', 'type': 'checkbutton', 'default_checkbutton': True,
         'tooltip': _('Включает дополнительный поиск по ключевым словам в истории/памяти.',
                      'Enables additional keyword search in history/memory.')},
        {'label': _('Включить Лемматизацию', 'Enable lemmatization'),
         'key': 'RAG_LEMMATIZATION', 'type': 'checkbutton', 'default_checkbutton': True,
         'tooltip': _('Включает лемматизацию при поиске на русском.',
                      'Enables lemmatization while using search in russian'),
         'depends_on': 'RAG_KEYWORD_SEARCH'},
        {'label': _('Вес ключевых слов K5', 'Keyword weight K5'),
         'key': 'RAG_WEIGHT_KEYWORDS', 'type': 'entry', 'default': 0.6,
         'validation': self.validate_float_positive_or_zero,
         'depends_on': 'RAG_KEYWORD_SEARCH',
         'tooltip': _('Вес, с которым результат поиска по ключевым словам K5 будет влиять на финальный скоринг.',
                      'The weight (K5) with which the keyword search result will influence the final scoring.')},
        {'label': _('Макс. ключевых слов', 'Max keywords'),
         'key': 'RAG_KEYWORDS_MAX_TERMS', 'type': 'entry', 'default': 8,
         'validation': self.validate_positive_integer, 'depends_on': 'RAG_KEYWORD_SEARCH',
         'tooltip': _('Максимальное количество ключевых слов, извлекаемых из запроса для поиска.',
                      'Maximum number of keywords extracted from the query for search.')},
        {'label': _('Мин. длина ключевого слова', 'Min keyword length'),
         'key': 'RAG_KEYWORDS_MIN_LEN', 'type': 'entry', 'default': 3,
         'validation': self.validate_positive_integer, 'depends_on': 'RAG_KEYWORD_SEARCH',
         'tooltip': _('Минимальная длина ключевого слова для его включения в поиск.',
                      'Minimum length for a keyword to be included in the search.')},
        {'label': _('Мин. оценка совпадения', 'Min match score'),
         'key': 'RAG_KEYWORD_MIN_SCORE', 'type': 'entry', 'default': 0.34,
         'validation': self.validate_float_0_to_1, 'depends_on': 'RAG_KEYWORD_SEARCH',
         'tooltip': _('Минимальная оценка (доля совпадений), необходимая для включения результата.',
                      'Minimum score (fraction of matches) required to include a result.')},
        {'label': _('SQL лимит поиска', 'SQL search limit'),
         'key': 'RAG_KEYWORD_SQL_LIMIT', 'type': 'entry', 'default': 250,
         'validation': self.validate_positive_integer, 'depends_on': 'RAG_KEYWORD_SEARCH',
         'tooltip': _('Максимальное количество записей, которое запрашивается из базы данных по ключевым словам.',
                      'Maximum number of records requested from the database by keywords.')},

        {'type': 'end'},
    ]


def _build_fts_config(self) -> list:
    return [
        {'label': _("Поиск FTS5", "FTS5 Search"), 'type': 'subsection',
         'depends_on': 'RAG_ENABLED'},

        {'label': _('Использовать FTS5 для поиска', 'Use FTS5 for search'),
         'key': 'RAG_USE_FTS', 'type': 'checkbutton', 'default_checkbutton': True,
         'tooltip': _(
             'Включает лексический поиск через SQLite FTS5 для памяти и/или истории (в зависимости от включенных опций).',
             'Enables lexical search via SQLite FTS5 for memory and/or history (depending on enabled options).')},
        {'label': _('Вес лексического фактора (K6)', 'Lexical factor weight (K6)'),
         'key': 'RAG_WEIGHT_LEXICAL', 'type': 'entry', 'default': 0.3,
         'validation': self.validate_float_0_to_1,
         'tooltip': _(
             'Вес лексического фактора (K6) в общей формуле ранжирования результатов (если используется смешанный поиск).',
             'Weight of the lexical factor (K6) in the overall results ranking formula (if mixed search is used).')},
        {'label': _('FTS Top K История', 'FTS Top K History'),
         'key': 'RAG_FTS_TOP_K_HISTORY', 'type': 'entry', 'default': 50,
         'validation': self.validate_positive_integer,
         'tooltip': _('Максимальное количество результатов, возвращаемых FTS5 из истории чата.',
                      'Maximum number of results returned by FTS5 from chat history.')},
        {'label': _('FTS Top K Память', 'FTS Top K Memories'),
         'key': 'RAG_FTS_TOP_K_MEMORIES', 'type': 'entry', 'default': 50,
         'validation': self.validate_positive_integer,
         'tooltip': _('Максимальное количество результатов, возвращаемых FTS5 из базы знаний (памяти).',
                      'Maximum number of results returned by FTS5 from the knowledge base (memory).')},
        {'label': _('FTS Макс. терминов в запросе', 'FTS Max terms in query'),
         'key': 'RAG_FTS_MAX_TERMS', 'type': 'entry', 'default': 8,
         'validation': self.validate_positive_integer,
         'tooltip': _('Максимальное количество терминов, которое будет использоваться в запросе FTS5 (по умолчанию 8).',
                      'Maximum number of terms that will be used in the FTS5 query (default 8).')},
        {'label': _('FTS Мин. длина термина', 'FTS Min term length'),
         'key': 'RAG_FTS_MIN_LEN', 'type': 'entry', 'default': 3,
         'validation': self.validate_positive_integer,
         'tooltip': _('Минимальная длина слова для включения в токенизацию и поиск FTS5 (по умолчанию 3).',
                      'Minimum word length to include in FTS5 tokenization and search (default 3).')},

        {'type': 'end'},
    ]


def _build_combine_config(self) -> list:
    return [
        {'label': _("Комбинирование", "Combining"), 'type': 'subsection',
         'depends_on': 'RAG_ENABLED'},

        {'label': _('Режим', 'Mode'),
         'key': 'RAG_COMBINE_MODE', 'type': 'combobox', 'default': 'union',
         'options': ['union', 'vector_only', 'intersect', 'two_stage'],
         'tooltip': _(
             'Как объединять результаты разных способов поиска:\n'
             'union — объединить всё (максимально похоже на старое поведение)\n'
             'vector_only — только эмбеддинги\n'
             'intersect — оставить найденное несколькими методами\n'
             'two_stage — сначала vector recall, а keyword/FTS только добавляют фичи (не добавляют новых id).',
             'How to combine results:\n'
             'union — merge all (closest to old behavior)\n'
             'vector_only — embeddings only\n'
             'intersect — keep only results found by multiple methods\n'
             'two_stage — vector recall first, keyword/FTS only add features (no new ids).'
         )},
        {'label': _('Vec TopK', 'Vec TopK'),
         'key': 'RAG_VECTOR_TOP_K', 'type': 'entry', 'default': 0,
         'validation': self.validate_positive_integer_or_zero,
         'depends_on': 'RAG_COMBINE_MODE', 'depends_on_value': ['vector_only', 'two_stage'],
         'hide_when_disabled': True,
         'tooltip': _(
             'Лимит кандидатов на vector-этапе (0 = без лимита). Полезно для скорости.',
             'Candidate cap for vector stage (0 = unlimited). Good for speed.')},

        # intersect options
        {'label': _('Min методов', 'Min methods'),
         'key': 'RAG_INTERSECT_MIN_METHODS', 'type': 'entry', 'default': 2,
         'validation': self.validate_positive_integer,
         'depends_on': 'RAG_COMBINE_MODE', 'depends_on_value': 'intersect',
         'hide_when_disabled': True,
         'tooltip': _(
             'Сколько методов (vector/fts/keyword_only) должны найти один и тот же результат.\nОбычно 2.',
             'How many methods (vector/fts/keyword_only) must find the same result.\nUsually 2.')},
        {'label': _('Треб. vector', 'Require vector'),
         'key': 'RAG_INTERSECT_REQUIRE_VECTOR', 'type': 'checkbutton', 'default_checkbutton': True,
         'depends_on': 'RAG_COMBINE_MODE', 'depends_on_value': 'intersect',
         'hide_when_disabled': True,
         'tooltip': _(
             'Если включено — результат должен присутствовать в vector bucket (т.е. иметь embedding match).',
             'If enabled, result must appear in vector bucket (embedding match required).')},
        {'label': _('Fallback union', 'Fallback union'),
         'key': 'RAG_INTERSECT_FALLBACK_UNION', 'type': 'checkbutton', 'default_checkbutton': True,
         'depends_on': 'RAG_COMBINE_MODE', 'depends_on_value': 'intersect',
         'hide_when_disabled': True,
         'tooltip': _(
             'Если intersect ничего не нашёл — вернуть union, иначе будет пусто.',
             'If intersect yields nothing, fallback to union, otherwise empty.')},

        # two_stage options
        {'label': _('Fallback union', 'Fallback union'),
         'key': 'RAG_TWO_STAGE_FALLBACK_UNION', 'type': 'checkbutton', 'default_checkbutton': True,
         'depends_on': 'RAG_COMBINE_MODE', 'depends_on_value': 'two_stage',
         'hide_when_disabled': True,
         'tooltip': _(
             'Если vector-этап пуст — можно вернуть union (иначе пустая выдача).',
             'If vector stage is empty, fallback to union (otherwise empty).')},

        {'type': 'end'},
    ]


def _build_cross_encoder_config(self) -> list:
    return [
        {'label': _("Cross-encoder (реранкер)", "Cross-encoder (reranker)"), 'type': 'subsection',
         'depends_on': 'RAG_ENABLED'},

        {'label': _('Включить cross-encoder реранкер', 'Enable cross-encoder reranker'),
         'key': 'RAG_CROSS_ENCODER_ENABLED', 'type': 'checkbutton', 'default_checkbutton': False,
         'depends_on': 'RAG_ENABLED',
         'tooltip': _(
             'Второй проход реранкинга: (query, passage) модель переоценивает топ-K кандидатов '
             'после линейного ранжирования. Даёт прирост точности за счёт скорости (~22M параметров).',
             'Second reranking pass: a (query, passage) scoring model re-scores the top-K candidates '
             'after linear ranking. Improves precision at the cost of latency (~22M params).')},
        {'label': _('Модель', 'Model'),
         'key': 'RAG_CROSS_ENCODER_MODEL', 'type': 'combobox',
         'options': list_ce_preset_names(), 'default': 'MiniLM-L6 v2 (22M, fast)',
         'depends_on': 'RAG_CROSS_ENCODER_ENABLED',
         'tooltip': _(
             'Пресет модели cross-encoder. MiniLM-L6 — быстрая ~22M, MiniLM-L12 — точнее ~33M, '
             'MiniLM-L2 — минимальная ~6M. Custom — ввести HF имя вручную.',
             'Cross-encoder model preset. MiniLM-L6 — fast ~22M, MiniLM-L12 — accurate ~33M, '
             'MiniLM-L2 — tiny ~6M. Custom — enter HF name manually.')},
        {'label': _('HF имя модели (Custom)', 'HF model name (Custom)'),
         'key': 'RAG_CROSS_ENCODER_MODEL_CUSTOM', 'type': 'entry', 'default': '',
         'depends_on': 'RAG_CROSS_ENCODER_MODEL', 'depends_on_value': 'Custom',
         'hide_when_disabled': True,
         'tooltip': _(
             'Полное HuggingFace имя cross-encoder модели, напр. "cross-encoder/ms-marco-MiniLM-L-6-v2".',
             'Full HuggingFace model name, e.g. "cross-encoder/ms-marco-MiniLM-L-6-v2".')},
        {'label': _('Мин. кандидатов для реранкинга (Top-K мин.)', 'Min candidates to rerank (Top-K min)'),
         'key': 'RAG_CROSS_ENCODER_TOP_K', 'type': 'entry', 'default': 20,
         'validation': self.validate_positive_integer,
         'depends_on': 'RAG_CROSS_ENCODER_ENABLED',
         'tooltip': _(
             'Минимум кандидатов, передаваемых в cross-encoder. '
             'Итоговое число = max(это, пул × ratio), но не больше жёсткого лимита CE. '
             'Гарантирует что CE получает хотя бы N элементов даже при маленьком пуле.',
             'Minimum candidates sent to the cross-encoder. '
             'Effective count = max(this, pool × ratio), capped by CE hard limit. '
             'Ensures CE always sees at least N items even with a small pool.')},
        {'label': _('Жёсткий лимит кандидатов CE (0 = выкл.)', 'CE hard item cap (0 = off)'),
         'key': 'RAG_CE_MAX_ITEMS', 'type': 'entry', 'default': 0,
         'validation': self.validate_positive_integer_or_zero,
         'depends_on': 'RAG_CROSS_ENCODER_ENABLED',
         'tooltip': _(
             'Максимум элементов, отправляемых в cross-encoder независимо от Top-K и ratio. '
             'Предотвращает зависание при большой истории (напр. пул 1500 → ratio даёт 600 → с лимитом 150 = 4× быстрее). '
             '0 = лимит выключен (старое поведение). Рекомендуется 150.',
             'Hard cap on items sent to the cross-encoder regardless of Top-K and ratio. '
             'Prevents slowdowns with large histories (e.g. pool 1500 → ratio gives 600 → cap 150 = 4× faster). '
             '0 = disabled (old behaviour). Recommended: 150.')},
        {'type': 'button_group', 'buttons': [
            {'label': _('Обновить статус', 'Refresh status'),
             'command': lambda: _refresh_ce_status(self)},
        ]},

        {'type': 'end'},
    ]


def _build_rag_logging_config(self) -> list:
    return [
        {'label': _("Логирование RAG", "RAG Logging"), 'type': 'subsection',
         'depends_on': 'RAG_ENABLED'},

        {'label': _('Подробные логи поиска', 'Detailed search logs'),
         'key': 'RAG_DETAILED_LOGS', 'type': 'checkbutton', 'default_checkbutton': True,
         'tooltip': _(
             'Если включено, в консоль/лог будет выводиться полная конфигурация поиска и список найденных кандидатов со скорами.',
             'If enabled, the full search configuration and list of found candidates with scores will be output to the console/log.')},
        {'label': _('Показывать весь список кандидатов', 'Show all candidates'),
         'key': 'RAG_LOG_LIST_SHOW_ALL', 'type': 'checkbutton', 'default_checkbutton': False,
         'tooltip': _(
             'Игнорировать лимиты Top N / Bottom N и выводить в лог абсолютно все найденные совпадения.',
             'Ignore Top N / Bottom N limits and output absolutely all found matches to the log.')},
        {'label': _('Кол-во лучших в логе (Top N)', 'Log Top N candidates'),
         'key': 'RAG_LOG_LIST_TOP_N', 'type': 'entry', 'default': 10,
         'validation': self.validate_positive_integer,
         'tooltip': _('Сколько первых (самых релевантных) результатов выводить в отладочный лог.',
                      'How many top (most relevant) results to display in the debug log.')},
        {'label': _('Кол-во худших в логе (Bottom N)', 'Log Bottom N candidates'),
         'key': 'RAG_LOG_LIST_BOTTOM_N', 'type': 'entry', 'default': 5,
         'validation': self.validate_positive_integer,
         'tooltip': _('Сколько последних результатов из списка кандидатов выводить в лог (для отладки "мусора").',
                      'How many last results from the candidate list to display in the log (for debugging "noise").')},

        {'type': 'end'},
    ]


# ---------------------------------------------------------------------------
# Section builder
# ---------------------------------------------------------------------------

def build_rag_memory_section(self, parent, hc_provider_names) -> None:
    """Build and inject the Memory & RAG settings section into *parent*."""

    config = (
        _build_pipeline_preset_config(self) +
        _build_memory_limits_config(self) +
        _build_history_compression_config(self, hc_provider_names) +
        _build_rag_core_config(self) +
        _build_embed_config(self) +
        _build_graph_config(self, hc_provider_names) +
        _build_query_tail_config(self) +
        _build_weights_config(self) +
        _build_keyword_config(self) +
        _build_fts_config(self) +
        _build_combine_config(self) +
        _build_cross_encoder_config(self) +
        _build_rag_logging_config(self) +
        []
    )

    create_settings_section(self, parent,
                            _("Настройки Памяти и RAG", "Memory & RAG Settings"),
                            config)

    # --- Dynamic status labels + download button for embedding model ---
    try:
        _dl_label = QLabel(_("Модель:", "Model:") + " " + _get_model_download_status())
        _dl_label.setStyleSheet("color: #aaa; font-size: 11px;")
        _idx_label = QLabel(_("Индекс:", "Index:") + " " + _get_embed_status_text())
        _idx_label.setStyleSheet("color: #aaa; font-size: 11px;")
        _embed_dl_btn = QPushButton(_("Скачать модель", "Download model"))
        _embed_dl_btn.setVisible(not _is_embed_model_downloaded())
        _embed_dl_btn.clicked.connect(lambda: _download_embed_model(self))
        self._embed_status_label = _idx_label
        self._embed_dl_label = _dl_label
        self._embed_dl_btn = _embed_dl_btn

        _rag_section = parent.layout().itemAt(parent.layout().count() - 1)
        if _rag_section and _rag_section.widget():
            _sec_widget = _rag_section.widget()
            _content = getattr(_sec_widget, 'content', None)
            if _content:
                _content_layout = _content.layout()
                if _content_layout:
                    for i in range(_content_layout.count()):
                        _item = _content_layout.itemAt(i)
                        if _item and _item.widget():
                            _w = _item.widget()
                            from managers.settings_manager import InnerCollapsibleSection
                            if isinstance(_w, InnerCollapsibleSection):
                                _tl = getattr(_w, 'title_label', None)
                                _title = _tl.text() if _tl else ''
                                if 'мбеддинг' in _title.lower() or 'mbedding' in _title.lower():
                                    _w.add_widget(_dl_label)
                                    _w.add_widget(_idx_label)
                                    _w.add_widget(_embed_dl_btn)
                                    break
    except Exception:
        pass

    # --- Dynamic status labels + download button for cross-encoder model ---
    try:
        _ce_dl_label = QLabel(_("Модель:", "Model:") + " " + _get_ce_download_status())
        _ce_dl_label.setStyleSheet("color: #aaa; font-size: 11px;")
        _ce_ld_label = QLabel(_("Статус:", "Status:") + " " + _get_ce_loaded_status())
        _ce_ld_label.setStyleSheet("color: #aaa; font-size: 11px;")
        _ce_dl_btn = QPushButton(_("Скачать модель", "Download model"))
        _ce_dl_btn.setVisible(not _is_ce_model_downloaded())
        _ce_dl_btn.clicked.connect(lambda: _download_ce_model(self))
        self._ce_dl_label = _ce_dl_label
        self._ce_loaded_label = _ce_ld_label
        self._ce_dl_btn = _ce_dl_btn

        _rag_section = parent.layout().itemAt(parent.layout().count() - 1)
        if _rag_section and _rag_section.widget():
            _sec_widget = _rag_section.widget()
            _content = getattr(_sec_widget, 'content', None)
            if _content:
                _content_layout = _content.layout()
                if _content_layout:
                    for i in range(_content_layout.count()):
                        _item = _content_layout.itemAt(i)
                        if _item and _item.widget():
                            _w = _item.widget()
                            from managers.settings_manager import InnerCollapsibleSection
                            if isinstance(_w, InnerCollapsibleSection):
                                _tl = getattr(_w, 'title_label', None)
                                _title = _tl.text() if _tl else ''
                                if 'ross-encoder' in _title or 'реранкер' in _title.lower():
                                    _w.add_widget(_ce_dl_label)
                                    _w.add_widget(_ce_ld_label)
                                    _w.add_widget(_ce_dl_btn)
                                    break
    except Exception:
        pass

    # Init delete button state (disabled for built-in presets / Custom)
    try:
        _update_preset_delete_btn(
            self,
            self.settings.get("RAG_PIPELINE_PRESET", "Custom") or "Custom",
        )
    except Exception:
        pass
