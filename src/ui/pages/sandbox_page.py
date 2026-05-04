import os
import threading

import qtawesome as qta

from PyQt6.QtCore import QTimer, Qt
from PyQt6.QtGui import QPixmap
from PyQt6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from core.events import Events
from main_logger import logger
from ui.chat.message_widget import AVATAR_MAP, _get_avatar_dir
from ui.widgets.chat_panel import ChatPanel
from utils import _

_MODEL_CONFIGURE_SENTINEL = "__configure_models__"
_TTS_CONFIGURE_SENTINEL = "__configure_tts__"
_ASR_CONFIGURE_SENTINEL = "__configure_asr__"
_PROMPT_CONFIGURE_SENTINEL = "__configure_prompts__"


def _round_pixmap(src: QPixmap, size: int) -> QPixmap:
    from PyQt6.QtGui import QPainter, QPainterPath
    scaled = src.scaled(size, size, Qt.AspectRatioMode.KeepAspectRatioByExpanding,
                        Qt.TransformationMode.SmoothTransformation)
    out = QPixmap(size, size)
    out.fill(Qt.GlobalColor.transparent)
    p = QPainter(out)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    path = QPainterPath()
    path.addEllipse(0, 0, size, size)
    p.setClipPath(path)
    x = (size - scaled.width()) // 2
    y = (size - scaled.height()) // 2
    p.drawPixmap(x, y, scaled)
    p.end()
    return out


class SandboxPage(QWidget):
    def __init__(self, gui):
        super().__init__(gui)
        self.gui = gui
        self.setObjectName("SandboxPage")

        self._memory_limit_values = {}
        self._debug_summary_values = {}
        self._chat_panel = None
        self._inspector_collapsed = False
        self._inspector_widget = None
        self._inspector_tabs = None
        self._inspector_collapse_btn = None
        self._character_avatar_label = None
        self._asr_retries = 0

        self._build_ui()
        self._sync_host_exports()
        self.on_activated()

    def _sync_host_exports(self):
        self.gui.sandbox_page = self

    def _sync_combobox_text(self, combo, value: str):
        if combo is None:
            return
        index = combo.findText(value, Qt.MatchFlag.MatchFixedString)
        if index < 0 or combo.currentIndex() == index:
            return
        combo.blockSignals(True)
        try:
            combo.setCurrentIndex(index)
        finally:
            combo.blockSignals(False)

    def _get_current_character_id(self) -> str:
        try:
            result = self.gui.event_bus.emit_and_wait(Events.Character.GET_CURRENT_PROFILE, timeout=0.5)
            profile = result[0] if result else {}
        except Exception:
            profile = {}
        return str((profile or {}).get("character_id") or "")

    def _jump_to_settings(self, category: str):
        self.gui.switch_main_page("settings")
        self.gui.show_settings_category(category)

    # --------- Avatar -----------
    def _resolve_avatar_pixmap(self, character_id: str, size: int = 32) -> QPixmap:
        char_id = (character_id or "").strip()
        candidates = []
        if char_id:
            # Direct match in AVATAR_MAP keys (e.g. "Crazy Mita")
            for key, fn in AVATAR_MAP.items():
                if key.lower().startswith(char_id.lower()) or char_id.lower().startswith(key.lower().split()[0]):
                    candidates.append(fn)
            candidates.append(f"{char_id.lower()}.png")
        avatar_dir = _get_avatar_dir()
        for fn in candidates:
            path = os.path.join(avatar_dir, fn)
            if os.path.isfile(path):
                pm = QPixmap(path)
                if not pm.isNull():
                    return _round_pixmap(pm, size)
        # Fallback icon
        icon_pm = qta.icon("fa6s.user", color="#ffd2ec").pixmap(size - 4, size - 4)
        return _round_pixmap(icon_pm, size)

    def _refresh_character_avatar(self):
        if self._character_avatar_label is None:
            return
        char_id = self._get_current_character_id()
        if not char_id:
            combo = getattr(self.gui, "chat_character_combobox", None)
            if combo is not None:
                char_id = combo.currentText().strip()
        self._character_avatar_label.setPixmap(self._resolve_avatar_pixmap(char_id, 32))

    # --------- Model -----------
    def _populate_model_combobox(self):
        combo = getattr(self.gui, "chat_model_combobox", None)
        if combo is None:
            return

        try:
            result = self.gui.event_bus.emit_and_wait(Events.ApiPresets.GET_PRESET_LIST, timeout=1.0)
            meta = result[0] if result else {}
        except Exception:
            meta = {}

        customs = list((meta or {}).get("custom", []))

        combo.blockSignals(True)
        try:
            combo.clear()

            if customs:
                for preset in customs:
                    preset_id = getattr(preset, "id", None)
                    name = getattr(preset, "name", "")
                    if preset_id is None:
                        continue
                    combo.addItem(str(name), int(preset_id))
                combo.insertSeparator(combo.count())
            else:
                combo.addItem(_("Нет настроенных моделей", "No configured models"), None)
                combo.insertSeparator(combo.count())

            combo.addItem(_("Настроить…", "Configure…"), _MODEL_CONFIGURE_SENTINEL)

            try:
                current_res = self.gui.event_bus.emit_and_wait(Events.ApiPresets.GET_CURRENT_PRESET_ID, timeout=0.5)
                current_id = current_res[0] if current_res else None
            except Exception:
                current_id = None

            if current_id is not None:
                for index in range(combo.count()):
                    if combo.itemData(index) == int(current_id):
                        combo.setCurrentIndex(index)
                        break
        finally:
            combo.blockSignals(False)

    def _on_chat_model_changed(self, index: int):
        combo = getattr(self.gui, "chat_model_combobox", None)
        if combo is None or index < 0:
            return
        data = combo.itemData(index)
        if data == _MODEL_CONFIGURE_SENTINEL:
            QTimer.singleShot(0, self._populate_model_combobox)
            self._jump_to_settings("api")
            return
        if data is None:
            return
        try:
            self.gui.event_bus.emit(Events.ApiPresets.SET_CURRENT_PRESET_ID, {"id": int(data)})
        except Exception as exc:
            logger.error(f"Failed to switch preset: {exc}")
        self._refresh_debug_summary()

    def _current_preset_name(self) -> str:
        try:
            cur = self.gui.event_bus.emit_and_wait(Events.ApiPresets.GET_CURRENT_PRESET_ID, timeout=0.5)
            cur_id = cur[0] if cur else None
            lst = self.gui.event_bus.emit_and_wait(Events.ApiPresets.GET_PRESET_LIST, timeout=0.5)
            meta = lst[0] if lst else {}
            for preset in (meta or {}).get("custom", []) or []:
                pid = getattr(preset, "id", None)
                if pid is not None and cur_id is not None and int(pid) == int(cur_id):
                    return str(getattr(preset, "name", "") or "")
        except Exception:
            pass
        return ""

    # --------- TTS -----------
    def _populate_tts_combobox(self):
        combo = getattr(self.gui, "chat_tts_combobox", None)
        if combo is None:
            return

        installed_local: set[str] = set()
        try:
            result = self.gui.event_bus.emit_and_wait(Events.VoiceModel.GET_INSTALLED_MODELS, timeout=0.5)
            models = result[0] if result else None
            if isinstance(models, (set, list, tuple)):
                installed_local = {str(item) for item in models}
        except Exception:
            installed_local = set()

        try:
            from ui.settings.voiceover_settings import LOCAL_VOICE_MODELS
        except Exception:
            LOCAL_VOICE_MODELS = []

        method = str(self.gui._get_setting("VOICEOVER_METHOD", "TG") or "TG")
        selected_local_id = str(self.gui._get_setting("LOCAL_VOICE_MODEL_ID", "") or "")

        combo.blockSignals(True)
        try:
            combo.clear()
            combo.addItem("Telegram (TG)", ("TG", None))

            for model in LOCAL_VOICE_MODELS:
                model_id = str(model.get("id") or "")
                name = str(model.get("name") or model_id)
                if model_id in installed_local:
                    combo.addItem(name, ("Local", model_id))

            combo.insertSeparator(combo.count())
            combo.addItem(_("Настроить…", "Configure…"), (_TTS_CONFIGURE_SENTINEL, None))

            active_index = 0
            for index in range(combo.count()):
                data = combo.itemData(index)
                if not isinstance(data, tuple):
                    continue
                kind, model_id = data
                if method == "TG" and kind == "TG":
                    active_index = index
                    break
                if method == "Local" and kind == "Local" and model_id == selected_local_id:
                    active_index = index
                    break
            combo.setCurrentIndex(active_index)
        finally:
            combo.blockSignals(False)

    def _on_chat_voice_changed(self, index: int):
        combo = getattr(self.gui, "chat_tts_combobox", None)
        if combo is None or index < 0:
            return
        data = combo.itemData(index)
        if not isinstance(data, tuple):
            return
        kind, model_id = data
        if kind == _TTS_CONFIGURE_SENTINEL:
            QTimer.singleShot(0, self._populate_tts_combobox)
            self._jump_to_settings("voice")
            return

        try:
            self.gui.settings.set("VOICEOVER_METHOD", kind)
            if kind == "Local" and model_id:
                self.gui.settings.set("LOCAL_VOICE_MODEL_ID", model_id)
                try:
                    self.gui.event_bus.emit(Events.GUI.VOICEOVER_MODEL_SELECTED, {"model_id": model_id})
                except Exception:
                    pass
        except Exception:
            try:
                self.gui.settings["VOICEOVER_METHOD"] = kind
            except Exception:
                pass

        self._refresh_debug_summary()

    # --------- ASR -----------
    def _populate_asr_combobox(self):
        combo = getattr(self.gui, "chat_asr_combobox", None)
        if combo is None:
            return

        combo.blockSignals(True)
        combo.clear()
        combo.addItem(_("Загрузка…", "Loading…"), None)
        combo.setEnabled(False)
        combo.blockSignals(False)

        def _apply(items):
            combo.blockSignals(True)
            try:
                combo.clear()
                engines = []
                for item in items or []:
                    try:
                        if item.get("installed", False) and item.get("id"):
                            engines.append(str(item["id"]))
                    except Exception:
                        pass

                if engines:
                    for engine in engines:
                        combo.addItem(engine, engine)
                    combo.insertSeparator(combo.count())
                    self._asr_retries = 0
                else:
                    if self._asr_retries < 1:
                        self._asr_retries += 1
                        QTimer.singleShot(1500, self._populate_asr_combobox)

                combo.addItem(_("Настроить…", "Configure…"), _ASR_CONFIGURE_SENTINEL)
                combo.setEnabled(True)

                current = str(self.gui._get_setting("RECOGNIZER_TYPE", "") or "")
                for index in range(combo.count()):
                    if combo.itemData(index) == current:
                        combo.setCurrentIndex(index)
                        break
            finally:
                combo.blockSignals(False)
            self._refresh_debug_summary()

        def _worker():
            try:
                res = self.gui.event_bus.emit_and_wait(Events.Speech.GET_ASR_MODELS_GLOSSARY, timeout=5.0)
                items = res[0] if res else []
                if not isinstance(items, list):
                    items = []
            except Exception:
                items = []
            QTimer.singleShot(0, lambda r=items: _apply(r))

        try:
            t = threading.Thread(target=_worker, daemon=True)
            t.start()
        except Exception:
            _apply([])

    def _on_chat_asr_changed(self, index: int):
        combo = getattr(self.gui, "chat_asr_combobox", None)
        if combo is None or index < 0:
            return
        data = combo.itemData(index)
        if data == _ASR_CONFIGURE_SENTINEL:
            QTimer.singleShot(0, self._populate_asr_combobox)
            self._jump_to_settings("microphone")
            return
        if not data:
            return
        try:
            self.gui.settings.set("RECOGNIZER_TYPE", str(data))
        except Exception:
            try:
                self.gui.settings["RECOGNIZER_TYPE"] = str(data)
            except Exception:
                pass
        self._refresh_debug_summary()

    # --------- Prompt set -----------
    def _populate_prompt_pack_combobox(self):
        combo = getattr(self.gui, "chat_prompt_pack_combobox", None)
        if combo is None:
            return
        char_id = self._get_current_character_id()
        if not char_id:
            char_combo = getattr(self.gui, "chat_character_combobox", None)
            if char_combo is not None:
                char_id = char_combo.currentText().strip()

        try:
            from managers.prompt_catalogue_manager import list_prompt_sets
            options = list_prompt_sets("Prompts", char_id) or []
        except Exception:
            options = []

        current = ""
        if char_id:
            try:
                current = str(self.gui._get_setting(f"PROMPT_SET_{char_id}", "") or "")
            except Exception:
                current = ""

        combo.blockSignals(True)
        try:
            combo.clear()
            if options:
                for name in options:
                    combo.addItem(str(name), str(name))
            else:
                combo.addItem(_("Нет наборов", "No sets"), None)
            combo.insertSeparator(combo.count())
            combo.addItem(_("Настроить…", "Configure…"), _PROMPT_CONFIGURE_SENTINEL)

            if current:
                idx = combo.findText(current, Qt.MatchFlag.MatchFixedString)
                if idx >= 0:
                    combo.setCurrentIndex(idx)
        finally:
            combo.blockSignals(False)

    def _on_chat_prompt_pack_changed(self, index: int):
        combo = getattr(self.gui, "chat_prompt_pack_combobox", None)
        if combo is None or index < 0:
            return
        data = combo.itemData(index)
        if data == _PROMPT_CONFIGURE_SENTINEL:
            QTimer.singleShot(0, self._populate_prompt_pack_combobox)
            self._jump_to_settings("character")
            return
        if not data:
            return
        char_id = self._get_current_character_id()
        if not char_id:
            char_combo = getattr(self.gui, "chat_character_combobox", None)
            if char_combo is not None:
                char_id = char_combo.currentText().strip()
        if not char_id:
            return
        try:
            self.gui.settings.set(f"PROMPT_SET_{char_id}", str(data))
            try:
                self.gui.settings.save_settings()
            except Exception:
                pass
            self.gui.event_bus.emit(Events.Character.RELOAD_DATA)
        except Exception as exc:
            logger.error(f"Failed to switch prompt set: {exc}")
        self._refresh_debug_summary()

    # --------- Character -----------
    def _populate_chat_character_combobox(self):
        combo = getattr(self.gui, "chat_character_combobox", None)
        if combo is None:
            return

        all_characters = self.gui.event_bus.emit_and_wait(Events.Character.GET_ALL, timeout=1.0)
        character_list = all_characters[0] if all_characters else ["Crazy"]
        if not character_list:
            character_list = ["Crazy"]

        current_char_id = self._get_current_character_id() or character_list[0]

        combo.blockSignals(True)
        try:
            combo.clear()
            combo.addItems(character_list)
            index = combo.findText(str(current_char_id), Qt.MatchFlag.MatchFixedString)
            if index >= 0:
                combo.setCurrentIndex(index)
        finally:
            combo.blockSignals(False)

    def _on_chat_character_changed(self, character_id):
        character_id = str(character_id or "").strip()
        if not character_id:
            return

        settings_combo = getattr(self.gui, "character_combobox", None)
        if settings_combo is not None and settings_combo.currentText() != character_id:
            index = settings_combo.findText(character_id, Qt.MatchFlag.MatchFixedString)
            if index >= 0:
                settings_combo.setCurrentIndex(index)
                if self._chat_panel is not None:
                    self._chat_panel.on_activated()
                self._refresh_character_avatar()
                self._populate_prompt_pack_combobox()
                self._refresh_debug_summary()
                return

        self.gui.event_bus.emit(Events.Character.SET_CURRENT, {"character_id": character_id})
        self.gui.event_bus.emit(Events.Character.RELOAD_DATA)
        if self._chat_panel is not None:
            self._chat_panel.on_activated()
        self._refresh_character_avatar()
        self._populate_prompt_pack_combobox()
        self._refresh_debug_summary()

    def _open_selected_character_history(self):
        combo = getattr(self.gui, "chat_character_combobox", None)
        character_id = combo.currentText().strip() if combo is not None else ""
        if character_id:
            self.gui.event_bus.emit(Events.Character.SET_CURRENT, {"character_id": character_id})
        try:
            from ui.settings.character_settings.logic import open_db_viewer
            open_db_viewer(self.gui)
        except Exception as exc:
            logger.error(f"Failed to open character history: {exc}", exc_info=True)

    # --------- RAG / memory profile -----------
    def _memory_profile_labels(self):
        from ui.settings.memory_profile import KEY_TO_LABEL_EN, KEY_TO_LABEL_RU
        lang = str(self.gui._get_setting("LANGUAGE", "RU") or "RU").upper()
        return KEY_TO_LABEL_EN if lang == "EN" else KEY_TO_LABEL_RU

    def _refresh_rag_combo(self):
        combo = getattr(self.gui, "chat_rag_combobox", None)
        if combo is None:
            return
        try:
            from ui.settings.memory_profile import detect_memory_profile
            key_to_label = self._memory_profile_labels()
            current_label = key_to_label.get(detect_memory_profile(self.gui))
        except Exception:
            current_label = None
        if current_label:
            self._sync_combobox_text(combo, current_label)

    def _refresh_memory_summary(self):
        for key, fallback in (
            ("MODEL_MESSAGE_LIMIT", 35),
            ("MEMORY_CAPACITY", 50),
            ("RAG_MAX_RESULTS", 50),
        ):
            value_label = self._memory_limit_values.get(key)
            if value_label is not None:
                value_label.setText(str(self.gui._get_setting(key, fallback)))

    def _on_rag_changed(self, label: str):
        try:
            from ui.settings.memory_profile import apply_memory_profile
        except Exception:
            apply_memory_profile = None
        if apply_memory_profile is not None:
            apply_memory_profile(self.gui, label)
        try:
            self.gui.settings.set("MEMORY_PROFILE", label)
            try:
                self.gui.settings.save_settings()
            except Exception:
                pass
        except Exception:
            try:
                self.gui.settings["MEMORY_PROFILE"] = label
            except Exception:
                pass
        self._refresh_memory_summary()
        self._refresh_debug_summary()

    # --------- Debug summary -----------
    def _refresh_debug_summary(self):
        get = self.gui._get_setting
        on_off = lambda v: (_("Вкл", "On") if v else _("Выкл", "Off"))

        def safe(key, fn):
            try:
                self._debug_summary_values[key].setText(str(fn()))
            except Exception:
                try:
                    self._debug_summary_values[key].setText("—")
                except Exception:
                    pass

        if "character" in self._debug_summary_values:
            safe("character", lambda: self._get_current_character_id() or "—")
        if "prompts" in self._debug_summary_values:
            def _prompts():
                cid = self._get_current_character_id()
                return get(f"PROMPT_SET_{cid}", "") or "—" if cid else "—"
            safe("prompts", _prompts)
        if "model" in self._debug_summary_values:
            safe("model", lambda: self._current_preset_name() or "—")
        if "voice" in self._debug_summary_values:
            safe("voice", lambda: str(get("VOICEOVER_METHOD", "TG")))
        if "asr" in self._debug_summary_values:
            safe("asr", lambda: str(get("RECOGNIZER_TYPE", "") or "—"))
        if "rag" in self._debug_summary_values:
            def _rag():
                from ui.settings.memory_profile import detect_memory_profile
                key_to_label = self._memory_profile_labels()
                return key_to_label.get(detect_memory_profile(self.gui), "—")
            safe("rag", _rag)
        if "messages" in self._debug_summary_values:
            safe("messages", lambda: str(get("MODEL_MESSAGE_LIMIT", 35)))
        if "memory" in self._debug_summary_values:
            safe("memory", lambda: str(get("MEMORY_CAPACITY", 50)))
        if "screen" in self._debug_summary_values:
            safe("screen", lambda: on_off(get("ENABLE_SCREEN_ANALYSIS", False)))
        if "camera" in self._debug_summary_values:
            safe("camera", lambda: on_off(get("ENABLE_CAMERA_CAPTURE", False)))

    # --------- Activation -----------
    def on_activated(self):
        self._populate_chat_character_combobox()
        self._populate_model_combobox()
        self._populate_tts_combobox()
        self._asr_retries = 0
        self._populate_asr_combobox()
        self._populate_prompt_pack_combobox()
        self._refresh_character_avatar()
        self._refresh_rag_combo()
        self._refresh_memory_summary()
        self._refresh_debug_summary()
        if self._chat_panel is not None:
            self._chat_panel.on_activated()

    # --------- Building blocks -----------
    def _make_selector_card(self, title: str, icon_name: str | None = None) -> tuple[QFrame, QVBoxLayout]:
        card = QFrame()
        card.setObjectName("SandboxSelectorCard")
        layout = QVBoxLayout(card)
        layout.setContentsMargins(14, 12, 14, 12)
        layout.setSpacing(6)

        title_row = QHBoxLayout()
        title_row.setSpacing(6)
        title_row.setContentsMargins(0, 0, 0, 0)

        if icon_name:
            icon_label = QLabel()
            icon_label.setObjectName("SandboxSelectorIcon")
            icon_label.setPixmap(qta.icon(icon_name, color="#ffd2ec").pixmap(14, 14))
            title_row.addWidget(icon_label, 0, Qt.AlignmentFlag.AlignVCenter)

        label = QLabel(title)
        label.setObjectName("SandboxSelectorLabel")
        title_row.addWidget(label, 0, Qt.AlignmentFlag.AlignVCenter)
        title_row.addStretch(1)
        layout.addLayout(title_row)
        return card, layout

    def _make_tab_page(self) -> tuple[QWidget, QVBoxLayout]:
        page = QWidget()
        page.setObjectName("SandboxInspectorTabPage")
        layout = QVBoxLayout(page)
        layout.setContentsMargins(2, 12, 2, 4)
        layout.setSpacing(12)
        return page, layout

    def _make_inspector_card(self, title_text: str | None = None, icon_name: str | None = None) -> tuple[QFrame, QVBoxLayout]:
        card = QFrame()
        card.setObjectName("SandboxInspectorCard")
        layout = QVBoxLayout(card)
        layout.setContentsMargins(14, 14, 14, 14)
        layout.setSpacing(8)
        if title_text:
            title_row = QHBoxLayout()
            title_row.setSpacing(6)
            title_row.setContentsMargins(0, 0, 0, 0)
            if icon_name:
                icon_label = QLabel()
                icon_label.setObjectName("SandboxSelectorIcon")
                icon_label.setPixmap(qta.icon(icon_name, color="#ffd2ec").pixmap(14, 14))
                title_row.addWidget(icon_label, 0, Qt.AlignmentFlag.AlignVCenter)
            title = QLabel(title_text)
            title.setObjectName("SandboxInspectorTitle")
            title_row.addWidget(title, 0, Qt.AlignmentFlag.AlignVCenter)
            title_row.addStretch(1)
            layout.addLayout(title_row)
        return card, layout

    def _build_header(self) -> QFrame:
        hero_card = QFrame()
        hero_card.setObjectName("ChatToolbarCard")
        hero_layout = QVBoxLayout(hero_card)
        hero_layout.setContentsMargins(18, 18, 18, 18)
        hero_layout.setSpacing(12)

        title_row = QHBoxLayout()
        title_row.setSpacing(16)

        title_col = QVBoxLayout()
        title_col.setSpacing(4)
        title_label = QLabel(_("Песочница", "Sandbox"))
        title_label.setObjectName("ChatHeroTitle")
        title_col.addWidget(title_label)

        subtitle_label = QLabel(
            _(
                "Экспериментируй, общайся и тестируй возможности NeuroMita в новой launcher-оболочке.",
                "Experiment, chat and test NeuroMita inside the rebuilt launcher shell.",
            )
        )
        subtitle_label.setObjectName("ChatHeroSubtitle")
        subtitle_label.setWordWrap(True)
        title_col.addWidget(subtitle_label)
        title_row.addLayout(title_col, 1)

        guide_button = QPushButton(_("Открыть руководство", "Open guide"))
        guide_button.setObjectName("SecondaryButton")
        guide_button.clicked.connect(self.gui._show_guide)
        title_row.addWidget(guide_button, 0, Qt.AlignmentFlag.AlignTop)
        hero_layout.addLayout(title_row)

        selectors = QHBoxLayout()
        selectors.setSpacing(10)

        # ----- Character (smaller, with avatar) -----
        character_card, character_layout = self._make_selector_card(_("Персонаж", "Character"), "fa6s.user")
        char_row = QHBoxLayout()
        char_row.setSpacing(8)
        char_row.setContentsMargins(0, 0, 0, 0)

        self._character_avatar_label = QLabel()
        self._character_avatar_label.setObjectName("SandboxCharacterAvatar")
        self._character_avatar_label.setFixedSize(32, 32)
        char_row.addWidget(self._character_avatar_label, 0, Qt.AlignmentFlag.AlignVCenter)

        self.gui.chat_character_combobox = QComboBox()
        self.gui.chat_character_combobox.setObjectName("ChatCharacterCombo")
        self.gui.chat_character_combobox.setToolTip(_("Выбрать персонажа", "Select character"))
        self.gui.chat_character_combobox.currentTextChanged.connect(self._on_chat_character_changed)
        char_row.addWidget(self.gui.chat_character_combobox, 1)
        character_layout.addLayout(char_row)
        selectors.addWidget(character_card, 2)

        # ----- Prompt set -----
        prompt_card, prompt_layout = self._make_selector_card(_("Набор промптов", "Prompt set"), "fa6s.scroll")
        self.gui.chat_prompt_pack_combobox = QComboBox()
        self.gui.chat_prompt_pack_combobox.setObjectName("ChatCharacterCombo")
        self.gui.chat_prompt_pack_combobox.setToolTip(_("Активный набор промптов", "Active prompt set"))
        self.gui.chat_prompt_pack_combobox.currentIndexChanged.connect(self._on_chat_prompt_pack_changed)
        prompt_layout.addWidget(self.gui.chat_prompt_pack_combobox)
        selectors.addWidget(prompt_card, 2)

        # ----- Model -----
        model_card, model_layout = self._make_selector_card(_("Модель", "Model"), "fa6s.microchip")
        self.gui.chat_model_combobox = QComboBox()
        self.gui.chat_model_combobox.setObjectName("ChatCharacterCombo")
        self.gui.chat_model_combobox.setToolTip(_("Активный API-пресет (модель)", "Active API preset (model)"))
        self.gui.chat_model_combobox.currentIndexChanged.connect(self._on_chat_model_changed)
        model_layout.addWidget(self.gui.chat_model_combobox)
        selectors.addWidget(model_card, 2)

        # ----- TTS -----
        tts_card, tts_layout = self._make_selector_card(_("TTS", "TTS"), "fa6s.volume-high")
        self.gui.chat_tts_combobox = QComboBox()
        self.gui.chat_tts_combobox.setObjectName("ChatCharacterCombo")
        self.gui.chat_tts_combobox.setToolTip(_("Способ озвучки", "Voice output"))
        self.gui.chat_tts_combobox.currentIndexChanged.connect(self._on_chat_voice_changed)
        tts_layout.addWidget(self.gui.chat_tts_combobox)
        selectors.addWidget(tts_card, 1)

        # ----- ASR -----
        asr_card, asr_layout = self._make_selector_card(_("ASR", "ASR"), "fa6s.microphone")
        self.gui.chat_asr_combobox = QComboBox()
        self.gui.chat_asr_combobox.setObjectName("ChatCharacterCombo")
        self.gui.chat_asr_combobox.setToolTip(_("Установленные модели распознавания речи", "Installed speech recognition models"))
        self.gui.chat_asr_combobox.currentIndexChanged.connect(self._on_chat_asr_changed)
        asr_layout.addWidget(self.gui.chat_asr_combobox)
        selectors.addWidget(asr_card, 1)

        # ----- RAG mode -----
        rag_card, rag_layout = self._make_selector_card(_("Режим RAG", "RAG mode"), "fa6s.brain")
        self.gui.chat_rag_combobox = QComboBox()
        self.gui.chat_rag_combobox.setObjectName("ChatCharacterCombo")
        self.gui.chat_rag_combobox.setToolTip(_("Профиль памяти / RAG", "Memory / RAG profile"))
        labels = self._memory_profile_labels()
        self.gui.chat_rag_combobox.addItems([
            labels.get("optimized", "Optimized"),
            labels.get("balanced", "Balanced"),
            labels.get("large", "Large"),
            labels.get("custom", "Custom"),
        ])
        self.gui.chat_rag_combobox.currentTextChanged.connect(self._on_rag_changed)
        rag_layout.addWidget(self.gui.chat_rag_combobox)
        selectors.addWidget(rag_card, 1)

        hero_layout.addLayout(selectors)
        return hero_card

    # --------- Inspector tabs -----------
    def _build_inspector_params_tab(self) -> QWidget:
        page, layout = self._make_tab_page()

        # Capture card
        capture_card, capture_layout = self._make_inspector_card(_("Захват / Capture", "Capture"), "fa6s.camera-retro")

        screen_cb = QCheckBox(_("Захват экрана", "Screen capture"))
        screen_cb.setObjectName("SandboxCaptureToggle")
        screen_cb.setChecked(bool(self.gui._get_setting("ENABLE_SCREEN_ANALYSIS", False)))
        screen_cb.toggled.connect(lambda v: self._on_capture_toggle("ENABLE_SCREEN_ANALYSIS", v))
        capture_layout.addWidget(screen_cb)
        self._capture_screen_cb = screen_cb

        camera_cb = QCheckBox(_("Захват с камеры", "Camera capture"))
        camera_cb.setObjectName("SandboxCaptureToggle")
        camera_cb.setChecked(bool(self.gui._get_setting("ENABLE_CAMERA_CAPTURE", False)))
        camera_cb.toggled.connect(lambda v: self._on_capture_toggle("ENABLE_CAMERA_CAPTURE", v))
        capture_layout.addWidget(camera_cb)
        self._capture_camera_cb = camera_cb

        layout.addWidget(capture_card)

        # Quick actions
        quick_card, quick_layout = self._make_inspector_card(_("Быстрые действия", "Quick actions"))
        self.gui.clear_chat_button = QPushButton(_("Очистить чат", "Clear chat"))
        self.gui.clear_chat_button.setObjectName("SandboxQuickAction")
        self.gui.clear_chat_button.clicked.connect(self.gui.clear_chat_display)
        quick_layout.addWidget(self.gui.clear_chat_button)

        self.gui.load_history_button = QPushButton(_("Загрузить историю", "Load history"))
        self.gui.load_history_button.setObjectName("SandboxQuickAction")
        self.gui.load_history_button.clicked.connect(self.gui.load_chat_history)
        quick_layout.addWidget(self.gui.load_history_button)

        api_button = QPushButton(_("Полные настройки API", "Full API settings"))
        api_button.setObjectName("SandboxQuickAction")
        api_button.clicked.connect(lambda: self._jump_to_settings("api"))
        quick_layout.addWidget(api_button)
        layout.addWidget(quick_card)

        layout.addStretch(1)
        return page

    def _on_capture_toggle(self, key: str, value: bool):
        try:
            self.gui.settings.set(key, bool(value))
            try:
                self.gui.settings.save_settings()
            except Exception:
                pass
        except Exception:
            try:
                self.gui.settings[key] = bool(value)
            except Exception:
                pass
        self._refresh_debug_summary()

    def _build_inspector_memory_tab(self) -> QWidget:
        page, layout = self._make_tab_page()

        counts_card, counts_layout = self._make_inspector_card(_("Лимиты памяти", "Memory limits"))
        for label_text, key, fallback in (
            (_("Сообщений в окне", "Messages in window"), "MODEL_MESSAGE_LIMIT", 35),
            (_("Долгосрочная память", "Long-term memory"), "MEMORY_CAPACITY", 50),
            (_("Результатов RAG", "RAG results"), "RAG_MAX_RESULTS", 50),
        ):
            row = QHBoxLayout()
            row.setSpacing(8)
            label = QLabel(label_text)
            label.setObjectName("SandboxInspectorLabel")
            row.addWidget(label)
            row.addStretch()
            value = QLabel(str(self.gui._get_setting(key, fallback)))
            value.setObjectName("SandboxInspectorValue")
            row.addWidget(value)
            counts_layout.addLayout(row)
            self._memory_limit_values[key] = value

        full_btn = QPushButton(_("Открыть RAG / память", "Open RAG / memory"))
        full_btn.setObjectName("SandboxQuickAction")
        full_btn.clicked.connect(lambda: self._jump_to_settings("models"))
        counts_layout.addWidget(full_btn)
        layout.addWidget(counts_card)

        layout.addStretch(1)
        return page

    def _build_inspector_debug_tab(self) -> QWidget:
        page, layout = self._make_tab_page()

        summary_card, summary_layout = self._make_inspector_card(_("Контекст сессии", "Session context"))
        rows = [
            ("character", _("Персонаж", "Character")),
            ("prompts", _("Промпты", "Prompts")),
            ("model", _("Модель", "Model")),
            ("voice", _("Голос", "Voice")),
            ("asr", _("ASR", "ASR")),
            ("rag", _("RAG-режим", "RAG mode")),
            ("messages", _("Сообщений в окне", "Messages")),
            ("memory", _("Память", "Memory")),
            ("screen", _("Захват экрана", "Screen capture")),
            ("camera", _("Камера", "Camera")),
        ]
        for key, label_text in rows:
            row = QHBoxLayout()
            row.setSpacing(8)
            label = QLabel(label_text)
            label.setObjectName("SandboxInspectorLabel")
            row.addWidget(label)
            row.addStretch()
            value = QLabel("—")
            value.setObjectName("SandboxInspectorValue")
            row.addWidget(value)
            summary_layout.addLayout(row)
            self._debug_summary_values[key] = value
        layout.addWidget(summary_card)

        actions_card, actions_layout = self._make_inspector_card(_("Диагностика", "Diagnostics"))
        db_btn = QPushButton(_("Открыть DB персонажа", "Open character DB"))
        db_btn.setObjectName("SandboxQuickAction")
        db_btn.clicked.connect(self._open_selected_character_history)
        actions_layout.addWidget(db_btn)

        debug_btn = QPushButton(_("Debug настройки", "Debug settings"))
        debug_btn.setObjectName("SandboxQuickAction")
        debug_btn.clicked.connect(lambda: self._jump_to_settings("debug"))
        actions_layout.addWidget(debug_btn)

        logs_btn = QPushButton(_("Открыть страницу логов", "Open logs page"))
        logs_btn.setObjectName("SandboxQuickAction")
        logs_btn.clicked.connect(lambda: self.gui.switch_main_page("logs"))
        actions_layout.addWidget(logs_btn)
        layout.addWidget(actions_card)

        layout.addStretch(1)
        return page

    def _build_inspector(self) -> QWidget:
        inspector = QWidget()
        inspector.setObjectName("SandboxInspector")
        inspector.setMinimumWidth(320)
        inspector.setMaximumWidth(320)
        self._inspector_widget = inspector

        layout = QVBoxLayout(inspector)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)

        # Toolbar with collapse button
        toolbar = QHBoxLayout()
        toolbar.setContentsMargins(0, 0, 0, 0)
        toolbar.setSpacing(0)
        toolbar.addStretch(1)
        collapse_btn = QPushButton("»")
        collapse_btn.setObjectName("SandboxInspectorCollapseBtn")
        collapse_btn.setFixedSize(28, 28)
        collapse_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        collapse_btn.setToolTip(_("Свернуть панель", "Collapse panel"))
        collapse_btn.clicked.connect(self._toggle_inspector_collapsed)
        toolbar.addWidget(collapse_btn, 0, Qt.AlignmentFlag.AlignRight)
        self._inspector_collapse_btn = collapse_btn
        layout.addLayout(toolbar)

        tabs = QTabWidget()
        tabs.setObjectName("SandboxInspectorTabs")
        tabs.setDocumentMode(True)
        tabs.addTab(self._build_inspector_params_tab(), _("Параметры", "Params"))
        tabs.addTab(self._build_inspector_memory_tab(), _("Память", "Memory"))
        tabs.addTab(self._build_inspector_debug_tab(), _("Отладка", "Debug"))
        layout.addWidget(tabs, 1)
        self.gui.sandbox_inspector_tabs = tabs
        self._inspector_tabs = tabs
        return inspector

    def _toggle_inspector_collapsed(self):
        self._inspector_collapsed = not self._inspector_collapsed
        if self._inspector_widget is None or self._inspector_tabs is None:
            return
        if self._inspector_collapsed:
            self._inspector_tabs.hide()
            self._inspector_widget.setMinimumWidth(36)
            self._inspector_widget.setMaximumWidth(36)
            if self._inspector_collapse_btn is not None:
                self._inspector_collapse_btn.setText("«")
                self._inspector_collapse_btn.setToolTip(_("Развернуть панель", "Expand panel"))
        else:
            self._inspector_tabs.show()
            self._inspector_widget.setMinimumWidth(320)
            self._inspector_widget.setMaximumWidth(320)
            if self._inspector_collapse_btn is not None:
                self._inspector_collapse_btn.setText("»")
                self._inspector_collapse_btn.setToolTip(_("Свернуть панель", "Collapse panel"))

    def _build_ui(self):
        page_layout = QVBoxLayout(self)
        page_layout.setContentsMargins(18, 18, 18, 18)
        page_layout.setSpacing(12)
        page_layout.addWidget(self._build_header())

        content_row = QHBoxLayout()
        content_row.setSpacing(12)

        self._chat_panel = ChatPanel(self.gui)
        content_row.addWidget(self._chat_panel, 1)
        content_row.addWidget(self._build_inspector())
        page_layout.addLayout(content_row, 1)


def build_sandbox_page(window) -> QWidget:
    return SandboxPage(window)
