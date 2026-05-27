import os
import threading

import qtawesome as qta

from PyQt6.QtCore import QSize, QTimer, Qt
from PyQt6.QtGui import QPixmap
from PyQt6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from core.events import Events
from main_logger import logger
from ui.chat.message_widget import AVATAR_MAP, _get_avatar_dir
from ui.widgets.chat_panel import ChatPanel
from ui.widgets.character_state_panel import CharacterStatePanel
from utils import _

_MODEL_CONFIGURE_SENTINEL = "__configure_models__"
_TTS_CONFIGURE_SENTINEL = "__configure_tts__"
_ASR_CONFIGURE_SENTINEL = "__configure_asr__"
_PROMPT_CONFIGURE_SENTINEL = "__configure_prompts__"


class _NoWheelComboBox(QComboBox):
    """QComboBox that blocks wheel-scroll from reaching separator/sentinel items."""

    _SENTINELS = frozenset({
        _MODEL_CONFIGURE_SENTINEL,
        _TTS_CONFIGURE_SENTINEL,
        _ASR_CONFIGURE_SENTINEL,
        _PROMPT_CONFIGURE_SENTINEL,
    })

    def wheelEvent(self, event):
        step = -1 if event.angleDelta().y() > 0 else 1
        target = self.currentIndex() + step
        if not (0 <= target < self.count()):
            event.accept()
            return
        if not self.itemText(target) or self.itemData(target) in self._SENTINELS:
            event.accept()
            return
        super().wheelEvent(event)


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
        self._inspector_stack = None
        self._inspector_tab_host = None
        self._inspector_collapse_btn = None
        self._inspector_tab_buttons = {}
        self._character_avatar_label = None
        self._asr_retries = 0
        self._inspector_expanded_width = 380
        self._inspector_collapsed_width = 56
        self._inspector_tab_indexes = {}

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
            self._jump_to_settings("characters")
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

        # Sync memory progress bars in the Session tab so they always reflect
        # the latest values (changed via settings page or memory profile).
        for key, (bar, value_lbl) in getattr(self, "_memory_bars", {}).items():
            try:
                val = int(get(key, bar.value()) or 0)
            except Exception:
                val = bar.value()
            try:
                bar.setValue(val)
                value_lbl.setText(str(val))
            except Exception:
                pass

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

    def show_debug_tab(self):
        if self._inspector_collapsed:
            self._toggle_inspector_collapsed()
        self._set_inspector_tab("debug")
        self._refresh_debug_summary()

    def _repolish(self, widget: QWidget | None) -> None:
        if widget is None:
            return
        widget.style().unpolish(widget)
        widget.style().polish(widget)
        widget.update()

    def _set_inspector_tab(self, tab_key: str) -> None:
        if self._inspector_stack is None:
            return
        index = self._inspector_tab_indexes.get(tab_key)
        if index is None:
            return
        self._inspector_stack.setCurrentIndex(index)
        for key, button in self._inspector_tab_buttons.items():
            active = key == tab_key
            button.setProperty("active", active)
            button.setChecked(active)
            self._repolish(button)

    def _make_inspector_tab_button(self, tab_key: str, label: str) -> QPushButton:
        button = QPushButton(label)
        button.setObjectName("SandboxInspectorTabButton")
        button.setCheckable(True)
        button.setCursor(Qt.CursorShape.PointingHandCursor)
        button.clicked.connect(lambda checked=False, key=tab_key: self._set_inspector_tab(key))
        self._inspector_tab_buttons[tab_key] = button
        return button

    def _update_inspector_collapse_icon(self) -> None:
        if self._inspector_collapse_btn is None:
            return
        icon_name = "fa6s.angles-left" if self._inspector_collapsed else "fa6s.angles-right"
        self._inspector_collapse_btn.setIcon(qta.icon(icon_name, color="#ffd6ee"))
        self._inspector_collapse_btn.setIconSize(QSize(14, 14))

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

    def _make_strip(self, title_text: str, icon_name: str | None = None) -> tuple[QWidget, QVBoxLayout]:
        """Stack-panel section: flat, no card border, just a title row
        with an optional icon and an underline. Used everywhere except the
        State tab (which keeps cards on the character_state_panel)."""
        strip = QWidget()
        strip.setObjectName("SandboxInspectorStrip")
        layout = QVBoxLayout(strip)
        layout.setContentsMargins(2, 2, 2, 2)
        layout.setSpacing(8)

        title_row = QHBoxLayout()
        title_row.setContentsMargins(0, 0, 0, 0)
        title_row.setSpacing(8)
        if icon_name:
            icon_label = QLabel()
            icon_label.setObjectName("SandboxSelectorIcon")
            icon_label.setPixmap(qta.icon(icon_name, color="#ffd2ec").pixmap(14, 14))
            title_row.addWidget(icon_label, 0, Qt.AlignmentFlag.AlignVCenter)
        title = QLabel(title_text)
        title.setObjectName("SandboxStripTitle")
        title_row.addWidget(title, 0, Qt.AlignmentFlag.AlignVCenter)
        title_row.addStretch(1)
        layout.addLayout(title_row)

        underline = QFrame()
        underline.setObjectName("SandboxStripUnderline")
        underline.setFixedHeight(1)
        layout.addWidget(underline)

        return strip, layout

    def _make_info_row(
        self,
        label_text: str,
        value_provider,
        edit_target: str,
        *,
        edit_tooltip: str | None = None,
    ) -> tuple[QWidget, QLabel]:
        """One read-only row: [label] [bold value] [pencil button].

        `value_provider` is a callable that returns the current text, OR a
        QComboBox (then we mirror currentText() and listen for changes).
        `edit_target` is the settings category key to jump to on pencil click.
        Returns (widget, value_label) so the caller can store the label and
        update it later if needed.
        """
        row = QWidget()
        row.setObjectName("SandboxInfoRow")
        h = QHBoxLayout(row)
        h.setContentsMargins(0, 0, 0, 0)
        h.setSpacing(8)

        label = QLabel(label_text)
        label.setObjectName("SandboxInfoLabel")
        h.addWidget(label, 0, Qt.AlignmentFlag.AlignVCenter)

        value_label = QLabel("—")
        value_label.setObjectName("SandboxInfoValue")
        value_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        h.addWidget(value_label, 1, Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignRight)

        edit_btn = QPushButton()
        edit_btn.setObjectName("SandboxInfoEditBtn")
        edit_btn.setIcon(qta.icon("fa6s.pen", color="#ffd2ec"))
        edit_btn.setFixedSize(26, 26)
        edit_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        edit_btn.setToolTip(edit_tooltip or _("Изменить в настройках", "Edit in settings"))
        edit_btn.clicked.connect(lambda: self._jump_to_settings(edit_target))
        h.addWidget(edit_btn, 0, Qt.AlignmentFlag.AlignVCenter)

        # Wire up the value source
        if isinstance(value_provider, QComboBox):
            combo = value_provider

            def _sync():
                value_label.setText(combo.currentText() or "—")
            _sync()
            combo.currentTextChanged.connect(lambda _t: _sync())
        elif callable(value_provider):
            try:
                value_label.setText(str(value_provider() or "—"))
            except Exception:
                value_label.setText("—")
        else:
            value_label.setText(str(value_provider or "—"))

        return row, value_label

    def _build_title_bar(self) -> QFrame:
        title_card = QFrame()
        title_card.setObjectName("SandboxWorkspaceHeader")
        title_layout = QHBoxLayout(title_card)
        title_layout.setContentsMargins(4, 2, 4, 10)
        title_layout.setSpacing(18)

        title_col = QVBoxLayout()
        title_col.setSpacing(5)

        headline_row = QHBoxLayout()
        headline_row.setSpacing(10)
        headline_row.setContentsMargins(0, 0, 0, 0)

        icon_label = QLabel()
        icon_label.setObjectName("SandboxHeroIcon")
        icon_label.setPixmap(qta.icon("fa6s.flask", color="#ff6db7").pixmap(22, 22))
        headline_row.addWidget(icon_label, 0, Qt.AlignmentFlag.AlignVCenter)

        title_label = QLabel(_("Песочница / Sandbox", "Sandbox"))
        title_label.setObjectName("ChatHeroTitle")
        headline_row.addWidget(title_label, 0, Qt.AlignmentFlag.AlignVCenter)

        badge = QLabel("BETA")
        badge.setObjectName("SandboxHeroBadge")
        headline_row.addWidget(badge, 0, Qt.AlignmentFlag.AlignVCenter)
        headline_row.addStretch(1)
        title_col.addLayout(headline_row)

        title_layout.addLayout(title_col, 1)

        actions = QHBoxLayout()
        actions.setSpacing(10)

        guide_button = QPushButton(_("Руководство", "Guide"))
        guide_button.setObjectName("SandboxHeaderButton")
        guide_button.clicked.connect(self.gui._show_guide)
        actions.addWidget(guide_button)

        settings_button = QPushButton(_("Настройки", "Settings"))
        settings_button.setObjectName("SandboxHeaderButton")
        settings_button.clicked.connect(lambda: self.gui.switch_main_page("settings"))
        actions.addWidget(settings_button)

        home_button = QPushButton(_("На главную", "Home"))
        home_button.setObjectName("SandboxHeaderPrimaryButton")
        home_button.clicked.connect(lambda: self.gui.switch_main_page("home"))
        actions.addWidget(home_button)

        title_layout.addLayout(actions, 0)
        return title_card

    # --------- Inspector tabs -----------
    def _wrap_in_scroll(self, page: QWidget) -> QScrollArea:
        scroll = QScrollArea()
        scroll.setObjectName("SandboxInspectorScroll")
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setWidget(page)
        return scroll

    def _build_inspector_session_tab(self) -> QWidget:
        from PyQt6.QtWidgets import QProgressBar
        page, layout = self._make_tab_page()

        # ── Hidden combo boxes ──────────────────────────────────────────────
        # Other modules (chat_panel, character_settings/logic, etc.) reference
        # gui.chat_*_combobox to read the active character / sync model lists.
        # We keep the QComboBox instances alive but stash them invisibly so
        # they continue to back the UI state without their own scroll-wheel
        # ever triggering re-initialization.
        hidden_host = QWidget(page)
        hidden_host.setVisible(False)
        hidden_layout = QVBoxLayout(hidden_host)
        hidden_layout.setContentsMargins(0, 0, 0, 0)

        def _new_hidden_combo(attr: str, *, tooltip: str = "", change_slot=None) -> QComboBox:
            combo = _NoWheelComboBox(hidden_host)
            combo.setObjectName("ChatCharacterCombo")
            combo.setToolTip(tooltip)
            if change_slot is not None:
                # Use currentIndexChanged where the old signal used it
                if change_slot is self._on_chat_character_changed:
                    combo.currentTextChanged.connect(change_slot)
                elif change_slot is self._on_rag_changed:
                    combo.currentTextChanged.connect(change_slot)
                else:
                    combo.currentIndexChanged.connect(change_slot)
            hidden_layout.addWidget(combo)
            setattr(self.gui, attr, combo)
            return combo

        char_combo = _new_hidden_combo(
            "chat_character_combobox",
            tooltip=_("Выбрать персонажа", "Select character"),
            change_slot=self._on_chat_character_changed,
        )
        prompt_combo = _new_hidden_combo(
            "chat_prompt_pack_combobox",
            tooltip=_("Активный набор промптов", "Active prompt set"),
            change_slot=self._on_chat_prompt_pack_changed,
        )
        model_combo = _new_hidden_combo(
            "chat_model_combobox",
            tooltip=_("Активный API-пресет (модель)", "Active API preset (model)"),
            change_slot=self._on_chat_model_changed,
        )
        tts_combo = _new_hidden_combo(
            "chat_tts_combobox",
            tooltip=_("Способ озвучки", "Voice output"),
            change_slot=self._on_chat_voice_changed,
        )
        asr_combo = _new_hidden_combo(
            "chat_asr_combobox",
            tooltip=_("Установленные модели распознавания речи", "Installed speech recognition models"),
            change_slot=self._on_chat_asr_changed,
        )
        rag_combo = _new_hidden_combo(
            "chat_rag_combobox",
            tooltip=_("Профиль памяти / RAG", "Memory / RAG profile"),
            change_slot=self._on_rag_changed,
        )
        labels = self._memory_profile_labels()
        rag_combo.addItems([
            labels.get("optimized", "Optimized"),
            labels.get("balanced", "Balanced"),
            labels.get("large", "Large"),
            labels.get("custom", "Custom"),
        ])

        layout.addWidget(hidden_host)

        # ── Активная сессия (info-only strip) ──────────────────────────────
        active_strip, active_layout = self._make_strip(_("Активная сессия", "Active session"), "fa6s.id-badge")

        # Character row with the avatar tucked into the value label.
        char_row = QWidget()
        char_row.setObjectName("SandboxInfoRow")
        char_h = QHBoxLayout(char_row)
        char_h.setContentsMargins(0, 0, 0, 0)
        char_h.setSpacing(8)
        char_lbl = QLabel(_("Персонаж", "Character"))
        char_lbl.setObjectName("SandboxInfoLabel")
        char_h.addWidget(char_lbl, 0, Qt.AlignmentFlag.AlignVCenter)

        self._character_avatar_label = QLabel()
        self._character_avatar_label.setObjectName("SandboxCharacterAvatar")
        self._character_avatar_label.setFixedSize(22, 22)
        char_h.addStretch(1)
        char_h.addWidget(self._character_avatar_label, 0, Qt.AlignmentFlag.AlignVCenter)
        self._character_value_label = QLabel("—")
        self._character_value_label.setObjectName("SandboxInfoValue")
        char_h.addWidget(self._character_value_label, 0, Qt.AlignmentFlag.AlignVCenter)

        char_edit_btn = QPushButton()
        char_edit_btn.setObjectName("SandboxInfoEditBtn")
        char_edit_btn.setIcon(qta.icon("fa6s.pen", color="#ffd2ec"))
        char_edit_btn.setFixedSize(26, 26)
        char_edit_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        char_edit_btn.setToolTip(_("Сменить персонажа в настройках", "Change character in settings"))
        char_edit_btn.clicked.connect(lambda: self._jump_to_settings("characters"))
        char_h.addWidget(char_edit_btn, 0, Qt.AlignmentFlag.AlignVCenter)
        active_layout.addWidget(char_row)

        char_combo.currentTextChanged.connect(
            lambda t: self._character_value_label.setText(t or "—")
        )

        prompt_row, _unused = self._make_info_row(
            _("Набор промптов", "Prompt set"),
            prompt_combo,
            "characters",
            edit_tooltip=_("Изменить промпты в настройках персонажа", "Change prompts in character settings"),
        )
        active_layout.addWidget(prompt_row)

        model_row, _unused = self._make_info_row(
            _("Модель", "Model"),
            model_combo,
            "api",
            edit_tooltip=_("Изменить активную модель в настройках API", "Change active model in API settings"),
        )
        active_layout.addWidget(model_row)
        layout.addWidget(active_strip)

        # ── Голос и распознавание ───────────────────────────────────────────
        # Renamed from "Голос и память" — RAG/memory got its own strip below.
        voice_strip, voice_layout = self._make_strip(_("Голос и микрофон", "Voice & microphone"), "fa6s.sliders")

        tts_row, _unused = self._make_info_row(
            _("Голосовой вывод", "Voice output"),
            tts_combo,
            "voice",
            edit_tooltip=_("Настроить озвучку", "Configure voice output"),
        )
        voice_layout.addWidget(tts_row)

        asr_row, _unused = self._make_info_row(
            _("Распознавание речи", "Speech recognition"),
            asr_combo,
            "microphone",
            edit_tooltip=_("Настроить распознавание речи", "Configure speech recognition"),
        )
        voice_layout.addWidget(asr_row)
        layout.addWidget(voice_strip)

        # ── Память и RAG ────────────────────────────────────────────────────
        memory_strip, memory_layout = self._make_strip(_("Память и контекст", "Memory & context"), "fa6s.brain")

        # Live readout of the three memory dials, both as numbers and as
        # progress bars normalized to 100. Clicking the pencil jumps to the
        # models settings where the limits live.
        rag_row, _unused = self._make_info_row(
            _("Профиль", "Profile"),
            rag_combo,
            "models",
            edit_tooltip=_("Настроить профиль памяти", "Configure memory profile"),
        )
        memory_layout.addWidget(rag_row)

        self._memory_bars = {}
        for key, label_text, fallback, max_hint in (
            ("MODEL_MESSAGE_LIMIT", _("Сообщений", "Messages"), 35, 100),
            ("MEMORY_CAPACITY", _("Память", "Memory"), 50, 100),
            ("RAG_MAX_RESULTS", _("RAG-результатов", "RAG results"), 50, 100),
        ):
            row = QWidget()
            row.setObjectName("SandboxMemoryRow")
            rl = QHBoxLayout(row)
            rl.setContentsMargins(0, 0, 0, 0)
            rl.setSpacing(8)
            lbl = QLabel(label_text)
            lbl.setObjectName("SandboxInfoLabel")
            lbl.setMinimumWidth(110)
            rl.addWidget(lbl, 0, Qt.AlignmentFlag.AlignVCenter)
            bar = QProgressBar()
            bar.setObjectName("SandboxMemoryBar")
            bar.setRange(0, max_hint)
            try:
                bar.setValue(int(self.gui._get_setting(key, fallback) or fallback))
            except Exception:
                bar.setValue(int(fallback))
            bar.setTextVisible(False)
            bar.setFixedHeight(8)
            rl.addWidget(bar, 1, Qt.AlignmentFlag.AlignVCenter)
            value_lbl = QLabel(str(bar.value()))
            value_lbl.setObjectName("SandboxInfoValue")
            value_lbl.setMinimumWidth(28)
            value_lbl.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            rl.addWidget(value_lbl, 0, Qt.AlignmentFlag.AlignVCenter)
            memory_layout.addWidget(row)
            self._memory_bars[key] = (bar, value_lbl)

        layout.addWidget(memory_strip)

        # ── Захват ─────────────────────────────────────────────────────────
        capture_strip, capture_layout = self._make_strip(_("Захват", "Capture"), "fa6s.camera-retro")
        screen_cb = QCheckBox(_("Захват экрана", "Screen capture"))
        screen_cb.setObjectName("SandboxCaptureToggle")
        screen_cb.setChecked(bool(self.gui._get_setting("ENABLE_SCREEN_ANALYSIS", False)))
        screen_cb.toggled.connect(lambda v: self._on_capture_toggle("ENABLE_SCREEN_ANALYSIS", v))
        capture_layout.addWidget(screen_cb)
        self._capture_screen_cb = screen_cb

        auto_attach_cb = QCheckBox(_("Авто-прикрепление", "Auto-attach"))
        auto_attach_cb.setObjectName("SandboxCaptureToggle")
        auto_attach_cb.setChecked(bool(self.gui._get_setting("AUTO_ATTACH_IMAGES", False)))
        auto_attach_cb.toggled.connect(lambda v: self._on_capture_toggle("AUTO_ATTACH_IMAGES", v))
        capture_layout.addWidget(auto_attach_cb)
        self._capture_auto_attach_cb = auto_attach_cb

        camera_cb = QCheckBox(_("Захват с камеры", "Camera capture"))
        camera_cb.setObjectName("SandboxCaptureToggle")
        camera_cb.setChecked(bool(self.gui._get_setting("ENABLE_CAMERA_CAPTURE", False)))
        camera_cb.toggled.connect(lambda v: self._on_capture_toggle("ENABLE_CAMERA_CAPTURE", v))
        capture_layout.addWidget(camera_cb)
        self._capture_camera_cb = camera_cb
        layout.addWidget(capture_strip)

        # ── Быстрые действия ───────────────────────────────────────────────
        actions_strip, actions_layout = self._make_strip(_("Быстрые действия", "Quick actions"), "fa6s.bolt")
        self.gui.clear_chat_button = QPushButton(_("Очистить чат", "Clear chat"))
        self.gui.clear_chat_button.setObjectName("SandboxQuickAction")
        self.gui.clear_chat_button.clicked.connect(self.gui.clear_chat_display)
        actions_layout.addWidget(self.gui.clear_chat_button)

        self.gui.load_history_button = QPushButton(_("Загрузить историю", "Load history"))
        self.gui.load_history_button.setObjectName("SandboxQuickAction")
        self.gui.load_history_button.clicked.connect(self.gui.load_chat_history)
        actions_layout.addWidget(self.gui.load_history_button)

        reset_btn = QPushButton(_("Сбросить персонажа", "Reset character"))
        reset_btn.setObjectName("SandboxQuickAction")
        reset_btn.setProperty("danger", True)
        reset_btn.clicked.connect(self._on_reset_character)
        actions_layout.addWidget(reset_btn)

        full_settings_btn = QPushButton(_("Полные настройки", "Full settings"))
        full_settings_btn.setObjectName("SandboxQuickAction")
        full_settings_btn.clicked.connect(lambda: self.gui.switch_main_page("settings"))
        actions_layout.addWidget(full_settings_btn)
        layout.addWidget(actions_strip)

        layout.addStretch(1)
        return self._wrap_in_scroll(page)

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

    def _on_reset_character(self) -> None:
        char_id = self._get_current_character_id()
        if not char_id:
            return
        reply = QMessageBox.question(
            self,
            _("Сбросить персонажа", "Reset character"),
            _(
                "Очистить историю и состояние '{name}'? Это действие необратимо.",
                "Clear history and state of '{name}'? This cannot be undone.",
            ).format(name=char_id),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return
        try:
            self.gui.event_bus.emit(Events.Character.CLEAR_HISTORY)
        except Exception as exc:
            logger.error(f"Failed to reset character: {exc}", exc_info=True)
            return
        try:
            self.gui.clear_chat_display()
        except Exception:
            pass

    def _build_inspector_state_tab(self) -> QWidget:
        page, layout = self._make_tab_page()
        self._character_state_panel = CharacterStatePanel(self.gui)
        layout.addWidget(self._character_state_panel)

        # Memory shortcuts (small)
        memory_card, memory_layout = self._make_inspector_card(_("Контекст и память", "Context & memory"), "fa6s.brain")
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
            memory_layout.addLayout(row)
            self._memory_limit_values[key] = value

        memory_btn = QPushButton(_("Открыть RAG / память", "Open RAG / memory"))
        memory_btn.setObjectName("SandboxQuickAction")
        memory_btn.clicked.connect(lambda: self._jump_to_settings("models"))
        memory_layout.addWidget(memory_btn)
        layout.addWidget(memory_card)

        layout.addStretch(1)
        return self._wrap_in_scroll(page)

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

        refresh_btn = QPushButton(_("Обновить сводку", "Refresh summary"))
        refresh_btn.setObjectName("SandboxQuickAction")
        refresh_btn.clicked.connect(self._refresh_debug_summary)
        summary_layout.addWidget(refresh_btn)
        layout.addWidget(summary_card)

        diagnostics_card, diagnostics_layout = self._make_inspector_card(_("Диагностика", "Diagnostics"), "fa6s.screwdriver-wrench")
        db_btn = QPushButton(_("Открыть DB персонажа", "Open character DB"))
        db_btn.setObjectName("SandboxQuickAction")
        db_btn.clicked.connect(self._open_selected_character_history)
        diagnostics_layout.addWidget(db_btn)

        logs_btn = QPushButton(_("Открыть страницу логов", "Open logs page"))
        logs_btn.setObjectName("SandboxQuickAction")
        logs_btn.clicked.connect(lambda: self.gui.switch_main_page("logs"))
        diagnostics_layout.addWidget(logs_btn)

        api_btn = QPushButton(_("Открыть API-настройки", "Open API settings"))
        api_btn.setObjectName("SandboxQuickAction")
        api_btn.clicked.connect(lambda: self._jump_to_settings("api"))
        diagnostics_layout.addWidget(api_btn)
        layout.addWidget(diagnostics_card)

        # Debug panel controls migrated from DeveloperPage
        debug_panel_card, debug_panel_layout = self._make_inspector_card(_("Параметры отладки", "Debug parameters"), "fa6s.bug")
        try:
            from ui.settings.debug_settings import setup_debug_panel_controls
            setup_debug_panel_controls(self.gui, debug_panel_layout)
        except Exception as exc:
            err = QLabel(f"[debug_settings error] {exc}")
            err.setWordWrap(True)
            debug_panel_layout.addWidget(err)
        layout.addWidget(debug_panel_card)

        layout.addStretch(1)
        return self._wrap_in_scroll(page)

    def _build_inspector(self) -> QWidget:
        inspector = QFrame()
        inspector.setObjectName("SandboxInspector")
        inspector.setMinimumWidth(self._inspector_expanded_width)
        inspector.setMaximumWidth(self._inspector_expanded_width)
        self._inspector_widget = inspector

        layout = QVBoxLayout(inspector)
        layout.setContentsMargins(14, 14, 14, 14)
        layout.setSpacing(10)

        header = QFrame()
        header.setObjectName("SandboxInspectorTabHeader")
        header_layout = QHBoxLayout(header)
        header_layout.setContentsMargins(0, 0, 0, 0)
        header_layout.setSpacing(8)

        tab_host = QWidget()
        tab_host.setObjectName("SandboxInspectorTabHost")
        tab_host_layout = QHBoxLayout(tab_host)
        tab_host_layout.setContentsMargins(0, 0, 0, 0)
        tab_host_layout.setSpacing(8)
        self._inspector_tab_host = tab_host

        session_page = self._build_inspector_session_tab()
        state_page = self._build_inspector_state_tab()
        debug_page = self._build_inspector_debug_tab()

        self._inspector_tab_buttons = {}
        for key, label in (
            ("session", _("Сессия", "Session")),
            ("state", _("Состояние", "State")),
            ("debug", _("Отладка", "Debug")),
        ):
            tab_host_layout.addWidget(self._make_inspector_tab_button(key, label))
        tab_host_layout.addStretch(1)
        header_layout.addWidget(tab_host, 1)

        collapse_btn = QPushButton()
        collapse_btn.setObjectName("SandboxInspectorCollapseBtn")
        collapse_btn.setFixedSize(34, 34)
        collapse_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        collapse_btn.setToolTip(_("Свернуть панель", "Collapse panel"))
        collapse_btn.clicked.connect(self._toggle_inspector_collapsed)
        header_layout.addWidget(collapse_btn, 0, Qt.AlignmentFlag.AlignVCenter)
        self._inspector_collapse_btn = collapse_btn
        self._update_inspector_collapse_icon()
        layout.addWidget(header)

        stack = QStackedWidget()
        stack.setObjectName("SandboxInspectorStack")
        self._inspector_tab_indexes = {
            "session": stack.addWidget(session_page),
            "state": stack.addWidget(state_page),
            "debug": stack.addWidget(debug_page),
        }
        layout.addWidget(stack, 1)
        self.gui.sandbox_inspector_tabs = stack
        self._inspector_stack = stack
        self._set_inspector_tab("session")
        return inspector

    def _toggle_inspector_collapsed(self):
        self._inspector_collapsed = not self._inspector_collapsed
        if self._inspector_widget is None or self._inspector_stack is None:
            return
        if self._inspector_collapsed:
            self._inspector_stack.hide()
            if self._inspector_tab_host is not None:
                self._inspector_tab_host.hide()
            self._inspector_widget.setMinimumWidth(self._inspector_collapsed_width)
            self._inspector_widget.setMaximumWidth(self._inspector_collapsed_width)
        else:
            self._inspector_stack.show()
            if self._inspector_tab_host is not None:
                self._inspector_tab_host.show()
            self._inspector_widget.setMinimumWidth(self._inspector_expanded_width)
            self._inspector_widget.setMaximumWidth(self._inspector_expanded_width)
        if self._inspector_collapse_btn is not None:
            self._inspector_collapse_btn.setToolTip(
                _("Развернуть панель", "Expand panel") if self._inspector_collapsed else _("Свернуть панель", "Collapse panel")
            )
        self._update_inspector_collapse_icon()

    def _build_ui(self):
        page_layout = QVBoxLayout(self)
        page_layout.setContentsMargins(14, 12, 14, 12)
        page_layout.setSpacing(0)

        workspace_shell = QFrame()
        workspace_shell.setObjectName("SandboxWorkspaceShell")
        shell_layout = QGridLayout(workspace_shell)
        shell_layout.setContentsMargins(14, 12, 14, 12)
        shell_layout.setHorizontalSpacing(12)
        shell_layout.setVerticalSpacing(8)
        shell_layout.setColumnStretch(0, 1)
        shell_layout.setColumnStretch(1, 0)
        shell_layout.setRowStretch(1, 1)

        shell_layout.addWidget(self._build_title_bar(), 0, 0, 1, 2)

        self._chat_panel = ChatPanel(self.gui)
        chat_host = QFrame()
        chat_host.setObjectName("SandboxChatHost")
        chat_host_layout = QVBoxLayout(chat_host)
        chat_host_layout.setContentsMargins(14, 14, 14, 14)
        chat_host_layout.setSpacing(0)
        chat_host_layout.addWidget(self._chat_panel)

        shell_layout.addWidget(chat_host, 1, 0)
        shell_layout.addWidget(self._build_inspector(), 1, 1)
        page_layout.addWidget(workspace_shell, 1)


def build_sandbox_page(window) -> QWidget:
    return SandboxPage(window)
