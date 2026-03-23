import os

from PyQt6.QtWidgets import (
    QLineEdit, QCheckBox, QComboBox, QMessageBox,
    QProgressDialog, QLabel, QHBoxLayout, QWidget, QPushButton,
)
from PyQt6.QtCore import Qt

from ui.gui_templates import create_settings_section, create_section_header
from utils import getTranslationVariant as _
from core.events import get_event_bus, Events
from managers.rag.pipeline.config import RAG_DEFAULTS
from handlers.embedding_presets import list_preset_names, resolve_model_settings


def _get_embed_status_text() -> str:
    """Check if current model has missing embeddings."""
    try:
        from managers.database_manager import DatabaseManager
        ms = resolve_model_settings()
        model = ms["hf_name"]
        db = DatabaseManager()
        conn = db.get_connection()
        cur = conn.cursor()

        # Count rows without embedding for current model
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

        # HF caches models in subdirectories like models--org--name
        cache_dir_name = "models--" + hf_name.replace("/", "--")
        model_path = os.path.join(checkpoints_dir, cache_dir_name)

        if os.path.isdir(model_path):
            return _("Скачана", "Downloaded")
        return _("Не скачана", "Not downloaded")
    except Exception:
        return "?"


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
    num_chars = len(cids)

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


def _refresh_embed_status(gui) -> None:
    """Refresh embedding status labels."""
    try:
        if hasattr(gui, '_embed_dl_label'):
            gui._embed_dl_label.setText(_("Модель:", "Model:") + " " + _get_model_download_status())
        if hasattr(gui, '_embed_status_label'):
            gui._embed_status_label.setText(_("Индекс:", "Index:") + " " + _get_embed_status_text())
    except Exception:
        pass


def _extract_entities_all(gui) -> None:
    """Run entity extraction for all history messages via GraphController."""
    from managers.database_manager import DatabaseManager
    from managers.rag.graph.graph_store import GraphStore
    from managers.rag.graph.entity_extractor import parse_extraction_response, store_extraction
    from ui.task_worker import TaskWorker

    db = DatabaseManager()
    conn = db.get_connection()
    cur = conn.cursor()
    cur.execute("SELECT DISTINCT character_id FROM history")
    cids = [r[0] for r in cur.fetchall() if r[0]]
    conn.close()

    if not cids:
        QMessageBox.information(gui, _("Готово", "Done"), _("Нет персонажей.", "No characters."))
        return

    def _do_extract(*, progress_callback=None):
        eb = get_event_bus()
        from managers.settings_manager import SettingsManager

        total_processed = 0
        grand_total = 0

        # Count total messages
        for cid in cids:
            c = db.get_connection()
            cur2 = c.cursor()
            cur2.execute(
                "SELECT COUNT(*) FROM history WHERE character_id=? AND content IS NOT NULL AND content != ''",
                (cid,),
            )
            grand_total += cur2.fetchone()[0] or 0
            c.close()

        for cid in cids:
            gs = GraphStore(db, cid)
            c = db.get_connection()
            cur2 = c.cursor()
            cur2.execute(
                """SELECT id, role, content FROM history
                   WHERE character_id=? AND content IS NOT NULL AND content != ''
                   ORDER BY id""",
                (cid,),
            )
            rows = cur2.fetchall() or []
            c.close()

            # Process in pairs (user + assistant)
            i = 0
            while i < len(rows):
                hid, role, content = rows[i]
                user_text = ""
                assistant_text = ""

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

                if text.strip():
                    # Use LLM for extraction via event
                    prompt = f"""Extract entities and relations from this dialogue message.
Output ONLY valid JSON (no commentary):
{{"entities":[{{"name":"...","type":"person|place|thing|concept"}}],
 "relations":[{{"s":"subject","p":"predicate","o":"object"}}]}}

Rules:
- Keep entity names short (1-3 words).
- Use lowercase for names and predicates.
- Only extract clearly stated facts, not speculation.
- If nothing meaningful, return {{"entities":[],"relations":[]}}

Message:
{text.strip()}"""

                    try:
                        res = eb.emit_and_wait(
                            Events.Model.GENERATE_RESPONSE,
                            {
                                "user_input": "",
                                "system_input": prompt,
                                "image_data": [],
                                "stream_callback": None,
                                "message_id": None,
                                "event_type": "graph_extract",
                            },
                            timeout=30.0,
                        )
                        if res and res[0]:
                            parsed = parse_extraction_response(str(res[0]))
                            if parsed:
                                store_extraction(gs, parsed, hid)
                    except Exception:
                        pass

                total_processed += 1
                i += 1
                if progress_callback and total_processed % 5 == 0:
                    try:
                        progress_callback(total_processed, grand_total)
                    except Exception:
                        pass

        return total_processed

    worker = TaskWorker(_do_extract, use_progress=True)

    progress = QProgressDialog(
        _("Извлечение сущностей...", "Extracting entities..."),
        _("Отмена", "Cancel"), 0, 100, gui,
    )
    progress.setWindowModality(Qt.WindowModality.WindowModal)
    progress.setMinimumDuration(0)
    progress.setValue(0)

    def on_progress(curr, total):
        try:
            progress.setRange(0, max(int(total), 1))
            progress.setValue(min(int(curr), max(int(total), 1)))
        except Exception:
            pass

    def on_finished(count):
        progress.close()
        from managers.settings_manager import SettingsManager
        if SettingsManager.get("GRAPH_GC_AUTO", False):
            _run_entity_gc(gui)
        else:
            QMessageBox.information(
                gui, _("Готово", "Done"),
                _("Обработано сообщений: {n}", "Messages processed: {n}").format(n=int(count or 0)),
            )

    def on_error(msg):
        progress.close()
        QMessageBox.critical(gui, _("Ошибка", "Error"), str(msg))

    worker.progress_signal.connect(on_progress)
    worker.finished_signal.connect(on_finished)
    worker.error_signal.connect(on_error)
    progress.canceled.connect(lambda: worker.requestInterruption())

    gui._entity_extract_worker = worker
    progress.show()
    worker.start()


def _run_entity_gc(gui, dry_run: bool = False) -> None:
    """Run entity GC for all characters (dry-run shows plan, apply executes it)."""
    from managers.database_manager import DatabaseManager
    from managers.rag.graph.entity_gc import EntityGC
    from ui.task_worker import TaskWorker

    db = DatabaseManager()
    conn = db.get_connection()
    cur = conn.cursor()
    cur.execute("SELECT DISTINCT character_id FROM graph_entities")
    cids = [r[0] for r in cur.fetchall() if r[0]]
    conn.close()

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
            lines = []
            for cid, info in results.items():
                lines.append(info.get("plan", ""))
            QMessageBox.information(gui, _("GC — предпросмотр", "GC — dry run"),
                                    "\n\n".join(lines) or _("Нечего чистить.", "Nothing to clean."))
        else:
            summary = "\n".join(
                f"{cid}: del={v.get('delete', 0)} merge={v.get('merge', 0)} "
                f"rename={v.get('rename', 0)}"
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


def _reset_rag_defaults(gui) -> None:
    """Reset all RAG settings to optimal defaults and update UI widgets."""
    for key, val in RAG_DEFAULTS.items():
        gui._save_setting(key, val)
        widget = getattr(gui, key, None)
        if widget is None:
            continue
        if isinstance(widget, QCheckBox):
            widget.setChecked(bool(val))
        elif isinstance(widget, QComboBox):
            widget.setCurrentText(str(val))
        elif isinstance(widget, QLineEdit):
            widget.setText(str(val))
    QMessageBox.information(
        gui,
        _("Сброс RAG", "RAG Reset"),
        _("Все настройки RAG сброшены к оптимальным значениям.",
          "All RAG settings have been reset to optimal defaults."),
    )

def setup_model_interaction_controls(self, parent):
    create_section_header(parent, _("Настройки взаимодействия с моделью", "Model Interaction Settings"))
    
    general_config = [
        {'label': _('Настройки сообщений', 'Message settings'), 'type': 'subsection'},
        {'label': _('Промты раздельно', 'Separated prompts'), 'key': 'SEPARATE_PROMPTS',
         'type': 'checkbutton', 'default_checkbutton': True},
        {'label': _('Кол-во попыток', 'Attempt count'), 'key': 'MODEL_MESSAGE_ATTEMPTS_COUNT',
         'type': 'entry', 'default': 3},
        {'label': _('Время между попытками', 'time between attempts'),
         'key': 'MODEL_MESSAGE_ATTEMPTS_TIME', 'type': 'entry', 'default': 0.20},
        {'label': _('Включить стриминговую передачу', 'Enable Streaming'), 'key': 'ENABLE_STREAMING',
         'type': 'checkbutton',
         'default_checkbutton': False},
        {'label': _('Использовать gpt4free последней попыткой ', 'Use gpt4free as last attempt'),
         'key': 'GPT4FREE_LAST_ATTEMPT', 'type': 'checkbutton', 'default_checkbutton': False},

        {'type': 'end'},

        {'label': _('Настройки ожидания', 'Waiting settings'), 'type': 'subsection'},
        {'label': _('Время ожидания текста (сек)', 'Text waiting time (sec)'),
         'key': 'TEXT_WAIT_TIME', 'type': 'entry', 'default': 40,
         'tooltip': _('время ожидания ответа', 'response waiting time')},
        {'label': _('Время ожидания звука (сек)', 'Voice waiting time (sec)'),
         'key': 'VOICE_WAIT_TIME', 'type': 'entry', 'default': 40,
         'tooltip': _('время ожидания озвучки', 'voice generation waiting time')},

        {'type': 'end'},

        {'label': _('Настройки генерации текста', 'Text Generation Settings'), 'type': 'subsection'},

        {'label': _('Макс. токенов в ответе', 'Max response tokens'),
        'key': 'MODEL_MAX_RESPONSE_TOKENS',
        'type': 'entry',
        'toggle_key': 'USE_MODEL_MAX_RESPONSE_TOKENS',
        'toggle_default': self.settings.get('USE_MODEL_MAX_RESPONSE_TOKENS', True),
        'default': 2500,
        'validation': self.validate_positive_integer,
        'tooltip': _('Максимальное количество токенов в ответе модели',
                    'Maximum number of tokens in the model response')},

        {'label': _('Температура', 'Temperature'), 'key': 'MODEL_TEMPERATURE',
         'type': 'entry', 'default': 1.0, 'validation': self.validate_float_0_to_2,
         'tooltip': _('Креативность ответа (0.0 = строго, 2.0 = очень творчески)',
                      'Creativity of response (0.0 = strict, 2.0 = very creative)')},

        {'label': _('Top-K', 'Top-K'),
        'key': 'MODEL_TOP_K',
        'type': 'entry',
        'toggle_key': 'USE_MODEL_TOP_K',
        'toggle_default': self.settings.get('USE_MODEL_TOP_K', True),
        'default': 0,
        'validation': self.validate_positive_integer_or_zero,
        'tooltip': _('Ограничивает выбор токенов K наиболее вероятными (0 = отключено)',
                    'Limits token selection to K most likely (0 = disabled)')},

        {'label': _('Top-P', 'Top-P'),
        'key': 'MODEL_TOP_P',
        'type': 'entry',
        'toggle_key': 'USE_MODEL_TOP_P',
        'toggle_default': self.settings.get('USE_MODEL_TOP_P', True),
        'default': 1.0,
        'validation': self.validate_float_0_to_1,
        'tooltip': _('Ограничивает выбор токенов по кумулятивной вероятности (0.0-1.0)',
                    'Limits token selection by cumulative probability (0.0-1.0)')},

        {'label': _('Бюджет размышлений', 'Thinking budget'),
        'key': 'MODEL_THINKING_BUDGET',
        'type': 'entry',
        'toggle_key': 'USE_MODEL_THINKING_BUDGET',
        'toggle_default': self.settings.get('USE_MODEL_THINKING_BUDGET', False),
        'default': 0.0,
        'validation': self.validate_float_minus2_to_2,
        'tooltip': _('Параметр, влияющий на глубину "размышлений" модели (зависит от модели)',
                    'Parameter influencing the depth of model "thoughts" (model-dependent)')},

        {'label': _('Штраф присутствия', 'Presence penalty'),
        'key': 'MODEL_PRESENCE_PENALTY',
        'type': 'entry',
        'toggle_key': 'USE_MODEL_PRESENCE_PENALTY',
        'toggle_default': self.settings.get('USE_MODEL_PRESENCE_PENALTY', False),
        'default': 0.0,
        'validation': self.validate_float_minus2_to_2,
        'tooltip': _('Штраф за использование новых токенов (-2.0 = поощрять новые, 2.0 = сильно штрафовать)',
                    'Penalty for using new tokens (-2.0 = encourage new, 2.0 = strongly penalize)')},

        {'label': _('Штраф частоты', 'Frequency penalty'),
        'key': 'MODEL_FREQUENCY_PENALTY',
        'type': 'entry',
        'toggle_key': 'USE_MODEL_FREQUENCY_PENALTY',
        'toggle_default': self.settings.get('USE_MODEL_FREQUENCY_PENALTY', False),
        'default': 0.0,
        'validation': self.validate_float_minus2_to_2,
        'tooltip': _('Штраф за частоту использования токенов (-2.0 = поощрять повторение, 2.0 = сильно штрафовать)',
                    'Penalty for the frequency of token usage (-2.0 = encourage repetition, 2.0 = strongly penalize)')},

        {'label': _('Лог вероятности', 'Log probability'),
        'key': 'MODEL_LOG_PROBABILITY',
        'type': 'entry',
        'toggle_key': 'USE_MODEL_LOG_PROBABILITY',
        'toggle_default': self.settings.get('USE_MODEL_LOG_PROBABILITY', False),
        'default': 0.0,
        'validation': self.validate_float_minus2_to_2,
        'tooltip': _('Параметр, влияющий на логарифмическую вероятность выбора токенов (-2.0 = поощрять, 2.0 = штрафовать)',
                    'Parameter influencing the logarithmic probability of token selection (-2.0 = encourage, 2.0 = penalize)')},

        {'label': _('Вызов инструментов', 'Tools use'),
         'key': 'TOOLS_ON',
         'type': 'checkbutton',
         'default_checkbutton': False,
         'tooltip': _(
             'Позволяет использовать инструменты такие как поиск в сети',
             'Allow using tools like seacrh')},
        {'label': _("Режим инструментов","Tools mode"), 'key': 'TOOLS_MODE', 'type': 'combobox',
         'options': ["native", "legacy"], 'default': "native", "depends_on": "TOOLS_ON",
         'tooltip': _('Native - использует вшитые возможности модели, legacy - добавляет промпт и ловит вызов вручную',
                    'Native - using buit-in tools, legacy - using own prompts and handler')},

        {'label': _('GOOGLE API KEY'), 'key': 'GOOGLE_API_KEY', 'type': 'entry',
         'default': "", 'hide': bool(self.settings.get("HIDE_PRIVATE"))},
        {'label': _('GOOGLE CSE ID'), 'key': 'GOOGLE_CSE_ID', 'type': 'entry',
         'default': "", 'hide': bool(self.settings.get("HIDE_PRIVATE"))},

        {'type': 'end'},
    ]

    create_settings_section(
        self,
        parent,
        _("Параметры генерации", "Generation Parameters"),
        general_config,
        icon_name='fa5s.cogs'
    )

    event_bus = get_event_bus()
    presets_meta = event_bus.emit_and_wait(Events.ApiPresets.GET_PRESET_LIST, timeout=1.0)
    hc_provider_names = [_('Текущий', 'Current')]
    if presets_meta and presets_meta[0]:
        all_presets = presets_meta[0].get('custom', [])
        for preset in all_presets:
            hc_provider_names.append(preset.name)
    react_provider_names = [_('Текущий', 'Current')]
    if presets_meta and presets_meta[0]:
        all_presets = presets_meta[0].get('custom', [])
        for preset in all_presets:
            react_provider_names.append(preset.name)


    
    react_settings_config = [
        {
            'label': _('Использовать реакции (react)', 'Use react events'),
            'key': 'REACT_ENABLED',
            'type': 'checkbutton',
            'default_checkbutton': False,
            'tooltip': _(
                'Включить генерацию реакций на действия игрока (react-задачи). '
                'Отключение полностью блокирует вызовы модели для react.',
                'Enable generation of reactions to player actions (react tasks). '
                'Disabling completely blocks model calls for react.'
            )
        },
        {
            'label': _('Использовать реакции L1 (тихие)', 'Enable react L1 (silent)'),
            'key': 'REACT_L1_ENABLED',
            'type': 'checkbutton',
            'default_checkbutton': True,
            'depends_on': 'REACT_ENABLED',
            'tooltip': _(
                'Тихие реакции: мимика/поза/действия без ответа текстом.',
                'Silent reactions: face/pose/actions without text answer.'
            )
        },
        {
            'label': _('Провайдер для реакций L1', 'Provider for react L1'),
            'key': 'REACT_PROVIDER_L1',
            'type': 'combobox',
            'options': react_provider_names,
            'default': _('Текущий', 'Current'),
            'depends_on': 'REACT_L1_ENABLED',
            'tooltip': _(
                'Какой API-пресет использовать для тихих react-сообщений (L1).',
                'Which API preset to use for silent react messages (L1).'
            )
        },
        {
            'label': _('Использовать реакции L2 (с ответом)', 'Enable react L2 (with answer)'),
            'key': 'REACT_L2_ENABLED',
            'type': 'checkbutton',
            'default_checkbutton': False,
            'depends_on': 'REACT_ENABLED',
            'tooltip': _(
                'Реакции с полноценным ответом: текст + озвучка, запись в историю.',
                'Answer reactions: text + voiceover, saved to history.'
            )
        },
        {
            'label': _('Провайдер для реакций L2', 'Provider for react L2'),
            'key': 'REACT_PROVIDER_L2',
            'type': 'combobox',
            'options': react_provider_names,
            'default': _('Текущий', 'Current'),
            'depends_on': 'REACT_L2_ENABLED',
            'tooltip': _(
                'Какой API-пресет использовать для react-ответов (L2).',
                'Which API preset to use for answer-react messages (L2).'
            )
        },
    ]

    create_settings_section(
        self,
        parent,
        _("Настройки реакций", "React settings"),
        react_settings_config
    )

    # ------------------------------------------------------------------
    # RAG & Memory settings (NEW)
    # ------------------------------------------------------------------
    rag_memory_config = [
        {'label': _('Лимит сообщений', 'Message limit'), 'key': 'MODEL_MESSAGE_LIMIT',
         'type': 'entry', 'default': 40,
         'tooltip': _('Сколько сообщений будет помнить мита', 'How much messages Mita will remember')},
        {'label': _('Лимит воспоминаний', 'Active memory limit (MEMORY_CAPACITY)'),
         'key': 'MEMORY_CAPACITY', 'type': 'entry', 'default': 75,
         'validation': self.validate_positive_integer,
         'tooltip': _(
             'Максимум активных воспоминаний (не удалённых и не забытых). При превышении система помечает одно как is_forgotten=1.',
             'Maximum number of active memories (not deleted and not forgotten). When exceeded, the system marks one as is_forgotten=1.')},

        {'type': 'end'},

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
         'options': ['history', 'memory'],
         'default': "history",
         'tooltip': _('Куда помещать результат сжатия истории (например, "memory", "summary_message").',
                      'Where to place the compressed history output (e.g., "memory", "summary_message").')},
        {'label': _('Провайдер для сжатия', 'Provider for compression'),
         'key': 'HC_PROVIDER',
         'type': 'combobox',
         'options': hc_provider_names,
         'default': _('Текущий', 'Current')},


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

        {'label': _('Модель эмбеддингов', 'Embedding Model'), 'type': 'subsection',
         'depends_on': 'RAG_ENABLED'},

        {'label': _('Модель', 'Model'),
         'key': 'RAG_EMBED_MODEL', 'type': 'combobox',
         'options': list_preset_names(),
         'default': 'Snowflake Arctic M v2.0',
         'tooltip': _('Выберите пресет или "Custom" для ручного ввода HuggingFace модели.',
                      'Choose a preset or "Custom" for manual HuggingFace model input.'),
         'depends_on': 'RAG_ENABLED'},

        {'label': _('HF имя модели (Custom)', 'HF model name (Custom)'),
         'key': 'RAG_EMBED_MODEL_CUSTOM', 'type': 'entry', 'default': '',
         'depends_on': 'RAG_EMBED_MODEL',
         'depends_on_value': 'Custom',
         'hide_when_disabled': True,
         'tooltip': _('Полное имя модели на HuggingFace, напр. "BAAI/bge-m3".',
                      'Full HuggingFace model name, e.g. "BAAI/bge-m3".')},

        {'label': _('Префикс запроса (Custom)', 'Query prefix (Custom)'),
         'key': 'RAG_EMBED_QUERY_PREFIX', 'type': 'entry', 'default': '',
         'depends_on': 'RAG_EMBED_MODEL',
         'depends_on_value': 'Custom',
         'hide_when_disabled': True,
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

        {'label': _('Граф знаний (экстракция сущностей)', 'Knowledge Graph (entity extraction)'),
         'type': 'subsection'},

        {'label': _('Включить экстракцию сущностей', 'Enable entity extraction'),
         'key': 'GRAPH_EXTRACTION_ENABLED', 'type': 'checkbutton',
         'default_checkbutton': False,
         'tooltip': _('Извлекать сущности и связи из диалога через LLM-провайдер и сохранять в граф.',
                       'Extract entities and relations from dialogue via LLM provider and store in graph.')},

        {'label': _('Провайдер для экстракции графа', 'Provider for graph extraction'),
         'key': 'GRAPH_PROVIDER',
         'type': 'combobox',
         'options': hc_provider_names,
         'default': _('Текущий', 'Current'),
         'depends_on': 'GRAPH_EXTRACTION_ENABLED',
         'tooltip': _('Какой LLM-провайдер использовать для экстракции сущностей (рекомендуется лёгкая модель).',
                       'Which LLM provider to use for entity extraction (lightweight model recommended).')},

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

        {'type': 'button_group', 'buttons': [
            {'label': _('Извлечь сущности из истории', 'Extract entities from history'),
             'command': lambda: _extract_entities_all(self)},
        ]},

        {'type': 'button_group', 'buttons': [
            {'label': _('Очистить граф (GC)', 'Clean graph (GC)'),
             'command': lambda: _run_entity_gc(self)},
            {'label': _('Предпросмотр GC', 'Preview GC'),
             'command': lambda: _run_entity_gc(self, dry_run=True)},
        ]},

        {'type': 'end'},

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

        {'label': _('Веса и затухание', 'Weights & decay'), 'type': 'subsection',
         'depends_on': 'RAG_ENABLED'},

        {'label': _('Вес схожести K1', 'Similarity weight K1'),
         'key': 'RAG_WEIGHT_SIMILARITY', 'type': 'entry', 'default': 1.0,
         'validation': self.validate_float_positive_or_zero,
         'depends_on': 'RAG_ENABLED'},

        {'label': _('Вес времени K2 (history)', 'Time weight K2 (history)'),
         'key': 'RAG_WEIGHT_TIME', 'type': 'entry', 'default': 0.3,
         'validation': self.validate_float_positive_or_zero,
         'depends_on': 'RAG_ENABLED'},

        {'label': _('Вес приоритета K3 (memories)', 'Priority weight K3 (memories)'),
         'key': 'RAG_WEIGHT_PRIORITY', 'type': 'entry', 'default': 0.5,
         'validation': self.validate_float_positive_or_zero,
         'depends_on': 'RAG_ENABLED'},

        {'label': _('Вес сущностей K4', 'Entity weight K4'),
         'key': 'RAG_WEIGHT_ENTITY', 'type': 'entry', 'default': 0.5,
         'validation': self.validate_float_positive_or_zero,
         'depends_on': 'RAG_ENABLED'},

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
         'validation': self.validate_positive_integer,
         'depends_on': 'RAG_KEYWORD_SEARCH',
         'tooltip': _('Максимальное количество ключевых слов, извлекаемых из запроса для поиска.',
                      'Maximum number of keywords extracted from the query for search.')},

        {'label': _('Мин. длина ключевого слова', 'Min keyword length'),
         'key': 'RAG_KEYWORDS_MIN_LEN', 'type': 'entry', 'default': 3,
         'validation': self.validate_positive_integer,
         'depends_on': 'RAG_KEYWORD_SEARCH',
         'tooltip': _('Минимальная длина ключевого слова для его включения в поиск.',
                      'Minimum length for a keyword to be included in the search.')},

        {'label': _('Мин. оценка совпадения', 'Min match score'),
         'key': 'RAG_KEYWORD_MIN_SCORE', 'type': 'entry', 'default': 0.34,
         'validation': self.validate_float_0_to_1,
         'depends_on': 'RAG_KEYWORD_SEARCH',
         'tooltip': _('Минимальная оценка (доля совпадений), необходимая для включения результата.',
                      'Minimum score (fraction of matches) required to include a result.')},

        {'label': _('SQL лимит поиска', 'SQL search limit'),
         'key': 'RAG_KEYWORD_SQL_LIMIT', 'type': 'entry', 'default': 250,
         'validation': self.validate_positive_integer,
         'depends_on': 'RAG_KEYWORD_SEARCH',
         'tooltip': _('Максимальное количество записей, которое запрашивается из базы данных по ключевым словам.',
                      'Maximum number of records requested from the database by keywords.')},
        {'type': 'end'},

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

        {'label': _("Комбинирование", "Combining"), 'type': 'subsection',
         'depends_on': 'RAG_ENABLED'},

        {'label': _('Режим', 'Mode'),
         'key': 'RAG_COMBINE_MODE',
         'type': 'combobox',
         'default': 'union',
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

        # Если применил мини-патч — можешь прятать по двум значениям:
        {'label': _('Vec TopK', 'Vec TopK'),
         'key': 'RAG_VECTOR_TOP_K',
         'type': 'entry',
         'default': 0,
         'validation': self.validate_positive_integer_or_zero,
         'depends_on': 'RAG_COMBINE_MODE',
         'depends_on_value': ['vector_only', 'two_stage'],  # <-- работает после патча
         'hide_when_disabled': True,
         'tooltip': _(
             'Лимит кандидатов на vector-этапе (0 = без лимита). Полезно для скорости.',
             'Candidate cap for vector stage (0 = unlimited). Good for speed.'
         )},

        # --- Intersect options (показывать только в intersect)
        {'label': _('Min методов', 'Min methods'),
         'key': 'RAG_INTERSECT_MIN_METHODS',
         'type': 'entry',
         'default': 2,
         'validation': self.validate_positive_integer,
         'depends_on': 'RAG_COMBINE_MODE',
         'depends_on_value': 'intersect',
         'hide_when_disabled': True,
         'tooltip': _(
             'Сколько методов (vector/fts/keyword_only) должны найти один и тот же результат.\n'
             'Обычно 2.',
             'How many methods (vector/fts/keyword_only) must find the same result.\n'
             'Usually 2.'
         )},

        {'label': _('Треб. vector', 'Require vector'),
         'key': 'RAG_INTERSECT_REQUIRE_VECTOR',
         'type': 'checkbutton',
         'default_checkbutton': True,
         'depends_on': 'RAG_COMBINE_MODE',
         'depends_on_value': 'intersect',
         'hide_when_disabled': True,
         'tooltip': _(
             'Если включено — результат должен присутствовать в vector bucket (т.е. иметь embedding match).',
             'If enabled, result must appear in vector bucket (embedding match required).'
         )},

        {'label': _('Fallback union', 'Fallback union'),
         'key': 'RAG_INTERSECT_FALLBACK_UNION',
         'type': 'checkbutton',
         'default_checkbutton': True,
         'depends_on': 'RAG_COMBINE_MODE',
         'depends_on_value': 'intersect',
         'hide_when_disabled': True,
         'tooltip': _(
             'Если intersect ничего не нашёл — вернуть union, иначе будет пусто.',
             'If intersect yields nothing, fallback to union, otherwise empty.'
         )},

        # --- Two-stage options (показывать только в two_stage)
        {'label': _('Fallback union', 'Fallback union'),
         'key': 'RAG_TWO_STAGE_FALLBACK_UNION',
         'type': 'checkbutton',
         'default_checkbutton': True,
         'depends_on': 'RAG_COMBINE_MODE',
         'depends_on_value': 'two_stage',
         'hide_when_disabled': True,
         'tooltip': _(
             'Если vector-этап пуст — можно вернуть union (иначе пустая выдача).',
             'If vector stage is empty, fallback to union (otherwise empty).'
         )},

        {'type': 'end'},

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

        {'type': 'button_group', 'buttons': [
            {'label': _('Сбросить RAG к базовым', 'Reset RAG defaults'),
             'command': lambda: _reset_rag_defaults(self)},
        ]},

    ]


    create_settings_section(self, parent,
                           _("Настройки Памяти и RAG", "Memory & RAG Settings"),
                           rag_memory_config)

    # --- Dynamic status labels for embedding model (injected into subsection) ---
    try:
        _dl_label = QLabel(_("Модель:", "Model:") + " " + _get_model_download_status())
        _dl_label.setStyleSheet("color: #aaa; font-size: 11px;")
        _idx_label = QLabel(_("Индекс:", "Index:") + " " + _get_embed_status_text())
        _idx_label.setStyleSheet("color: #aaa; font-size: 11px;")
        self._embed_status_label = _idx_label
        self._embed_dl_label = _dl_label

        # Find the "Embedding Model" subsection inside the created section and inject labels
        _rag_section = parent.layout().itemAt(parent.layout().count() - 1)
        if _rag_section and _rag_section.widget():
            _sec_widget = _rag_section.widget()
            # CollapsibleSection stores child InnerCollapsibleSections; find the embedding one
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
                                    break
    except Exception:
        pass

    token_settings_config = [
        {'label': _('Показывать информацию о токенах', 'Show Token Info'), 'key': 'SHOW_TOKEN_INFO',
         'type': 'checkbutton', 'default_checkbutton': True,
         'tooltip': _('Отображать количество токенов и ориентировочную стоимость в интерфейсе чата.',
                      'Display token count and approximate cost in the chat interface.')},
        {'label': _('Стоимость токена (вход, ₽)', 'Token Cost (input, ₽)'), 'key': 'TOKEN_COST_INPUT', 'depends_on': 'SHOW_TOKEN_INFO',
         'type': 'entry', 'default': 0.000001, 'validation': self.validate_float_positive_or_zero,
         'tooltip': _('Стоимость одного токена для входных данных (например, 0.000001 ₽ за токен).',
                      'Cost of one token for input data (e.g., 0.000001 ₽ per token).')},
        {'label': _('Стоимость токена (выход, ₽)', 'Token Cost (output, ₽)'), 'key': 'TOKEN_COST_OUTPUT', 'depends_on': 'SHOW_TOKEN_INFO',
         'type': 'entry', 'default': 0.000002, 'validation': self.validate_float_positive_or_zero,
         'tooltip': _('Стоимость одного токена для выходных данных (например, 0.000002 ₽ за токен).',
                      'Cost of one token for output data (e.g., 0.000002 ₽ per token).')},
        {'label': _('Максимальное количество токенов модели', 'Max Model Tokens'), 'key': 'MAX_MODEL_TOKENS', 'depends_on': 'SHOW_TOKEN_INFO',
         'type': 'entry', 'default': 32000, 'validation': self.validate_positive_integer,
         'tooltip': _('Максимальное количество токенов, которое может обработать модель.',
                      'Maximum number of tokens the model can process.')},
    ]

    create_settings_section(self, parent,
                           _("Настройки токенов", "Token Settings"),
                           token_settings_config)

    command_processing_config = [
        {'label': _('Использовать обработку команд', 'Use command processing'), 'key': 'USE_COMMAND_REPLACER',
         'type': 'checkbutton',
         'default_checkbutton': False, 'tooltip': _('Включает замену команд в ответе модели на основе схожести.',
                                                    'Enables replacing commands in the model response based on similarity.')},
        {'label': _('Мин. порог схожести', 'Min similarity threshold'), 'key': 'MIN_SIMILARITY_THRESHOLD',
         'type': 'entry', 
         'depends_on': 'USE_COMMAND_REPLACER', 'hide_when_disabled': True,
         'default': 0.40, 
         'validation': self.validate_float_0_to_1, 
         'tooltip': _('Минимальный порог схожести для замены команды (0.0-1.0).',
                      'Minimum similarity threshold for command replacement (0.0-1.0).')},
        {'label': _('Порог смены категории', 'Category switch threshold'), 'key': 'CATEGORY_SWITCH_THRESHOLD',
         'type': 'entry',
         'depends_on': 'USE_COMMAND_REPLACER', 'hide_when_disabled': True,
         'default': 0.18,
         'validation': self.validate_float_0_to_1, 
         'tooltip': _('Дополнительный порог для переключения на другую категорию команд (0.0-1.0).',
                      'Additional threshold for switching to a different command category (0.0-1.0).')},
        {'label': _('Пропускать параметры с запятой', 'Skip comma parameters'), 'key': 'SKIP_COMMA_PARAMETERS',
         'type': 'checkbutton', 
         'depends_on': 'USE_COMMAND_REPLACER', 'hide_when_disabled': True,
         'default_checkbutton': True, 
         'tooltip': _('Пропускать параметры, содержащие запятую, при замене.',
                                                   'Skip parameters containing commas during replacement.')},
    ]

    create_settings_section(self, parent,
                           _("Обработка команд", "Command Processing"),
                           command_processing_config)


