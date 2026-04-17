# src/ui/settings/embed_provider_settings.py
"""Embedding provider settings UI — compact vertical layout."""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtWidgets import (
    QComboBox, QHBoxLayout, QLabel, QLineEdit,
    QPushButton, QSizePolicy, QTextEdit,
    QToolButton, QVBoxLayout, QWidget,
)

from core.events import get_event_bus, Events
from managers.settings_manager import InnerCollapsibleSection, SettingsManager
from utils import getTranslationVariant as _


def build_embed_provider_inner_section(gui) -> InnerCollapsibleSection:
    section = InnerCollapsibleSection(
        _("Провайдер эмбеддингов", "Embedding Provider"), gui
    )
    ctrl = _EmbedProviderWidget(gui)
    section.add_widget(ctrl)
    return section


class _EmbedProviderWidget(QWidget):
    def __init__(self, gui):
        super().__init__()
        self._gui = gui
        self._bus = get_event_bus()
        self._current_preset_id: Optional[Any] = None
        self._is_loading = False
        self._test_timer: Optional[QTimer] = None
        self._key_url: str = ""

        self._setup_ui()
        self._load_presets()

        saved = SettingsManager.get("RAG_EMBED_PRESET_ID", None)
        self._select_preset(saved if saved is not None else "local_hf")

        self._bus.subscribe(Events.EmbeddingPresets.TEST_RESULT, self._on_test_result, weak=False)

    # ── UI ────────────────────────────────────────────────────────────────────

    def _setup_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 2, 0, 2)
        root.setSpacing(4)

        # Row: preset selector + add/del buttons
        preset_row = QHBoxLayout()
        preset_row.setSpacing(4)
        preset_row.addWidget(QLabel(_("Пресет:", "Preset:")))
        self._preset_combo = QComboBox()
        self._preset_combo.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self._preset_combo.currentIndexChanged.connect(self._on_preset_combo_changed)
        preset_row.addWidget(self._preset_combo, 1)
        self._add_btn = QToolButton()
        self._add_btn.setText("+")
        self._add_btn.setFixedWidth(24)
        self._add_btn.setToolTip(_("Добавить пресет", "Add preset"))
        self._add_btn.clicked.connect(self._on_add)
        self._del_btn = QToolButton()
        self._del_btn.setText("−")
        self._del_btn.setFixedWidth(24)
        self._del_btn.setToolTip(_("Удалить пресет", "Delete preset"))
        self._del_btn.clicked.connect(self._on_delete)
        preset_row.addWidget(self._add_btn)
        preset_row.addWidget(self._del_btn)
        root.addLayout(preset_row)

        # Row: provider type
        type_row = QHBoxLayout()
        type_row.setSpacing(4)
        type_row.addWidget(QLabel(_("Тип:", "Type:")))
        self._provider_combo = QComboBox()
        self._provider_combo.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        for val, label in [
            ("local",        _("Local (HF / путь)", "Local (HF / path)")),
            ("openai_compat", _("OpenAI-compatible API", "OpenAI-compatible API")),
            ("gemini",       _("Google Gemini API", "Google Gemini API")),
        ]:
            self._provider_combo.addItem(label, userData=val)
        self._provider_combo.currentIndexChanged.connect(self._on_provider_type_changed)
        type_row.addWidget(self._provider_combo, 1)
        root.addLayout(type_row)

        # Row: model
        model_row = QHBoxLayout()
        model_row.setSpacing(4)
        self._model_label = QLabel(_("Модель:", "Model:"))
        model_row.addWidget(self._model_label)
        self._model_combo = QComboBox()
        self._model_combo.setEditable(True)
        self._model_combo.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self._model_combo.lineEdit().textChanged.connect(self._mark_dirty)
        model_row.addWidget(self._model_combo, 1)
        root.addLayout(model_row)

        # Row: URL (API only)
        self._url_widget = QWidget()
        url_row = QHBoxLayout(self._url_widget)
        url_row.setContentsMargins(0, 0, 0, 0)
        url_row.setSpacing(4)
        url_row.addWidget(QLabel("URL:"))
        self._url_edit = QLineEdit()
        self._url_edit.setPlaceholderText("https://...")
        self._url_edit.textChanged.connect(self._mark_dirty)
        url_row.addWidget(self._url_edit, 1)
        root.addWidget(self._url_widget)

        # Row: API key (API only)
        self._key_widget = QWidget()
        key_row = QHBoxLayout(self._key_widget)
        key_row.setContentsMargins(0, 0, 0, 0)
        key_row.setSpacing(4)
        key_row.addWidget(QLabel(_("Ключ:", "Key:")))
        self._key_edit = QLineEdit()
        self._key_edit.setEchoMode(QLineEdit.EchoMode.Password)
        self._key_edit.setPlaceholderText("sk-...")
        self._key_edit.textChanged.connect(self._mark_dirty)
        self._key_eye = QToolButton()
        self._key_eye.setText("👁")
        self._key_eye.setCheckable(True)
        self._key_eye.setFixedWidth(24)
        self._key_eye.toggled.connect(
            lambda on: self._key_edit.setEchoMode(
                QLineEdit.EchoMode.Normal if on else QLineEdit.EchoMode.Password
            )
        )
        key_row.addWidget(self._key_edit, 1)
        key_row.addWidget(self._key_eye)
        root.addWidget(self._key_widget)

        # Reserve keys (API only)
        self._reserve_widget = QWidget()
        rv = QVBoxLayout(self._reserve_widget)
        rv.setContentsMargins(0, 0, 0, 0)
        rv.setSpacing(2)
        rv.addWidget(QLabel(_("Резервные ключи (по строке):", "Reserve keys (one per line):")))
        self._reserve_edit = QTextEdit()
        self._reserve_edit.setFixedHeight(48)
        self._reserve_edit.textChanged.connect(self._mark_dirty)
        rv.addWidget(self._reserve_edit)
        root.addWidget(self._reserve_widget)

        # Row: query prefix
        prefix_row = QHBoxLayout()
        prefix_row.setSpacing(4)
        prefix_row.addWidget(QLabel(_("Префикс:", "Prefix:")))
        self._prefix_edit = QLineEdit()
        self._prefix_edit.setPlaceholderText('query: ')
        self._prefix_edit.textChanged.connect(self._mark_dirty)
        prefix_row.addWidget(self._prefix_edit, 1)
        root.addLayout(prefix_row)

        # Status label
        self._status_label = QLabel()
        self._status_label.setWordWrap(True)
        root.addWidget(self._status_label)

        # Action buttons
        btn_row = QHBoxLayout()
        btn_row.setSpacing(4)
        self._save_btn = QPushButton(_("Сохранить", "Save"))
        self._save_btn.clicked.connect(self._on_save)
        self._test_btn = QPushButton(_("Тест", "Test"))
        self._test_btn.clicked.connect(self._on_test)
        self._key_url_btn = QPushButton(_("Получить ключ ↗", "Get key ↗"))
        self._key_url_btn.setVisible(False)
        self._key_url_btn.clicked.connect(self._on_open_key_url)
        btn_row.addWidget(self._save_btn)
        btn_row.addWidget(self._test_btn)
        btn_row.addWidget(self._key_url_btn)
        btn_row.addStretch()
        root.addLayout(btn_row)

    # ── Data ──────────────────────────────────────────────────────────────────

    def _load_presets(self):
        self._preset_combo.blockSignals(True)
        self._preset_combo.clear()
        try:
            results = self._bus.emit_and_wait(
                Events.EmbeddingPresets.GET_PRESET_LIST, {}, timeout=2.0
            )
            meta = results[0] if results else {}
        except Exception:
            meta = {}

        if not meta:
            from presets.embedding_provider_presets import list_builtin_presets
            for bp in list_builtin_presets():
                self._preset_combo.addItem(bp["name"], userData=bp["id"])
        else:
            for b in meta.get("builtin", []):
                self._preset_combo.addItem(b["name"], userData=b["id"])
            for c in meta.get("custom", []):
                self._preset_combo.addItem("✎ " + c["name"], userData=c["id"])
        self._preset_combo.blockSignals(False)

    def _select_preset(self, preset_id: Any):
        idx = self._find_combo_index(preset_id)
        if idx >= 0:
            self._preset_combo.setCurrentIndex(idx)
        else:
            self._load_into_editor(preset_id)

    def _find_combo_index(self, preset_id: Any) -> int:
        for i in range(self._preset_combo.count()):
            if self._preset_combo.itemData(i) == preset_id:
                return i
        return -1

    def _on_preset_combo_changed(self, _idx: int):
        pid = self._preset_combo.currentData()
        if pid is not None:
            self._load_into_editor(pid)

    def _load_into_editor(self, preset_id: Any):
        self._is_loading = True
        try:
            cfg = self._fetch_cfg(preset_id)
            if not cfg:
                return
            self._current_preset_id = preset_id
            SettingsManager.set("RAG_EMBED_PRESET_ID", preset_id)

            provider = cfg.get("provider_name") or "local"
            idx = self._provider_combo.findData(provider)
            self._provider_combo.blockSignals(True)
            if idx >= 0:
                self._provider_combo.setCurrentIndex(idx)
            self._provider_combo.blockSignals(False)

            is_local = provider == "local"
            is_builtin = bool(cfg.get("is_builtin", True))

            model = cfg.get("model") or ""
            known = list(cfg.get("known_models") or [])
            self._model_combo.blockSignals(True)
            self._model_combo.clear()
            self._model_combo.addItems(known)
            if model and model not in known:
                self._model_combo.insertItem(0, model)
            mi = self._model_combo.findText(model) if model else -1
            self._model_combo.setCurrentIndex(mi if mi >= 0 else 0)
            self._model_combo.blockSignals(False)

            self._model_label.setText(
                _("Модель / путь:", "Model / path:") if is_local else _("Модель:", "Model:")
            )

            self._url_edit.setText(cfg.get("api_url") or "")
            self._key_edit.setText(cfg.get("api_key") or "")
            rk = cfg.get("reserve_keys") or []
            self._reserve_edit.blockSignals(True)
            self._reserve_edit.setPlainText("\n".join(rk))
            self._reserve_edit.blockSignals(False)
            self._prefix_edit.setText(cfg.get("query_prefix") or "")

            self._key_url = cfg.get("key_url") or ""
            self._key_url_btn.setVisible(bool(self._key_url) and not is_local)

            self._provider_combo.setEnabled(not is_builtin)
            self._url_edit.setReadOnly(is_builtin)
            self._del_btn.setEnabled(not is_builtin)

            self._apply_visibility(is_local)
            self._refresh_index_status()
            self._save_btn.setStyleSheet("")
        finally:
            self._is_loading = False

    def _fetch_cfg(self, preset_id: Any) -> Optional[Dict[str, Any]]:
        try:
            results = self._bus.emit_and_wait(
                Events.EmbeddingPresets.GET_PRESET_FULL, {"id": preset_id}, timeout=2.0
            )
            cfg = results[0] if results else None
            if cfg and isinstance(cfg, dict):
                return cfg
        except Exception:
            pass
        try:
            from presets.embedding_provider_presets import get_builtin_preset
            bp = get_builtin_preset(str(preset_id))
            if bp:
                provider = bp["provider"]
                model = bp["default_model"]
                return {
                    "id": bp["id"], "name": bp["name"],
                    "provider_name": provider, "model": model,
                    "hf_name": model if provider == "local" else "",
                    "api_url": bp.get("default_url") or "",
                    "api_key": None, "reserve_keys": [],
                    "headers": dict(bp.get("default_headers") or {}),
                    "query_prefix": "",
                    "dimensions": int(bp.get("default_dimensions") or 0),
                    "key_url": bp.get("key_url") or "",
                    "known_models": list(bp.get("known_models") or []),
                    "is_builtin": True,
                }
        except Exception:
            pass
        return None

    def _apply_visibility(self, is_local: bool):
        self._url_widget.setVisible(not is_local)
        self._key_widget.setVisible(not is_local)
        self._reserve_widget.setVisible(not is_local)

    def _on_provider_type_changed(self):
        if self._is_loading:
            return
        is_local = (self._provider_combo.currentData() == "local")
        self._apply_visibility(is_local)
        self._mark_dirty()

    def _mark_dirty(self):
        if not self._is_loading:
            self._save_btn.setStyleSheet("font-weight: bold;")

    # ── Actions ───────────────────────────────────────────────────────────────

    def _on_save(self):
        pid = self._current_preset_id
        if pid is None:
            return
        provider = self._provider_combo.currentData() or "local"
        model = self._model_combo.currentText().strip()
        url = self._url_edit.text().strip()
        key = self._key_edit.text().strip()
        reserve_keys = [l.strip() for l in self._reserve_edit.toPlainText().splitlines() if l.strip()]
        prefix = self._prefix_edit.text()

        is_builtin = isinstance(pid, str)
        if is_builtin:
            data = {
                "id": None,
                "name": self._get_current_display_name() + " (custom)",
                "base": pid,
                "provider_name": provider,
                "model": model,
                "url": "",
                "key": key,
                "reserve_keys": reserve_keys,
                "query_prefix": prefix,
            }
        else:
            data = {
                "id": pid,
                "provider_name": provider,
                "model": model,
                "url": url,
                "key": key,
                "reserve_keys": reserve_keys,
                "query_prefix": prefix,
            }

        try:
            results = self._bus.emit_and_wait(
                Events.EmbeddingPresets.SAVE_CUSTOM_PRESET, {"data": data}, timeout=2.0
            )
            saved_id = results[0] if results else None
            if saved_id is not None:
                SettingsManager.set("RAG_EMBED_PRESET_ID", saved_id)
                self._current_preset_id = saved_id
                self._save_btn.setStyleSheet("")
                self._load_presets()
                self._select_preset(saved_id)
        except Exception as e:
            self._status_label.setText(_("Ошибка: ", "Error: ") + str(e))

    def _on_add(self):
        from PyQt6.QtWidgets import QInputDialog
        name, ok = QInputDialog.getText(
            self, _("Новый пресет", "New preset"), _("Имя:", "Name:")
        )
        if not ok or not name.strip():
            return
        data = {"id": None, "name": name.strip(), "provider_name": "local",
                "model": "", "url": "", "key": "", "reserve_keys": [], "query_prefix": ""}
        try:
            results = self._bus.emit_and_wait(
                Events.EmbeddingPresets.SAVE_CUSTOM_PRESET, {"data": data}, timeout=2.0
            )
            new_id = results[0] if results else None
            if new_id is not None:
                self._load_presets()
                self._select_preset(new_id)
        except Exception as e:
            self._status_label.setText(str(e))

    def _on_delete(self):
        pid = self._current_preset_id
        if pid is None or isinstance(pid, str):
            return
        try:
            self._bus.emit_and_wait(
                Events.EmbeddingPresets.DELETE_CUSTOM_PRESET, {"id": pid}, timeout=2.0
            )
        except Exception:
            pass
        self._load_presets()
        if self._preset_combo.count() > 0:
            self._preset_combo.setCurrentIndex(0)

    def _on_test(self):
        self._status_label.setStyleSheet("")
        self._status_label.setText(_("Тестирование...", "Testing..."))
        self._test_btn.setEnabled(False)
        self._bus.emit(Events.EmbeddingPresets.TEST_PRESET, {"id": self._current_preset_id})
        if self._test_timer:
            self._test_timer.stop()
        self._test_timer = QTimer(singleShot=True)
        self._test_timer.timeout.connect(lambda: self._test_btn.setEnabled(True))
        self._test_timer.start(30000)

    def _on_test_result(self, event):
        data = event.data or {}
        if data.get("id") != self._current_preset_id:
            return
        if self._test_timer:
            self._test_timer.stop()
        self._test_btn.setEnabled(True)
        if data.get("success"):
            self._status_label.setText("✓ " + (data.get("message") or "OK"))
            self._status_label.setStyleSheet("color: green;")
        else:
            self._status_label.setText("✗ " + (data.get("message") or "Error"))
            self._status_label.setStyleSheet("color: red;")

    def _on_open_key_url(self):
        import webbrowser
        if self._key_url:
            webbrowser.open(self._key_url)

    def _get_current_display_name(self) -> str:
        return self._preset_combo.currentText().lstrip("✎ ").strip()

    def _refresh_index_status(self):
        try:
            from ui.settings.rag_memory_settings import _get_embed_status_text
            self._status_label.setStyleSheet("")
            self._status_label.setText(_get_embed_status_text())
        except Exception:
            pass
