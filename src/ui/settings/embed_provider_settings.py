# src/ui/settings/embed_provider_settings.py
"""Embedding provider settings UI — compact vertical layout."""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QCheckBox, QComboBox, QHBoxLayout, QLabel, QLineEdit,
    QPushButton, QSizePolicy, QTextEdit,
    QToolButton, QVBoxLayout, QWidget,
)

from ui.widgets.settings_sections import InnerCollapsibleSection
from ui.gui_templates import SettingsBodyWidget
from ui.mvvm import immutable_payload, mutable_payload
from ui.settings.embed_provider_presentation import (
    ActivateEmbedProvider,
    AddEmbedPreset,
    DeleteEmbedPreset,
    DownloadEmbedModel,
    EmbedProviderShowError,
    EmbedProviderState,
    RefreshEmbedPresets,
    ReorderEmbedPresets,
    SaveEmbedPreset,
    SelectEmbedPreset,
    TestEmbedPreset,
)
from utils import getTranslationVariant as _
from localization.live import tr_set


def build_embed_provider_inner_section(gui, view_model) -> InnerCollapsibleSection:
    section = InnerCollapsibleSection(
        _("Провайдер эмбеддингов", "Embedding Provider"), gui
    )
    ctrl = _EmbedProviderWidget(gui, view_model)
    section.add_widget(ctrl)
    return section


def build_embed_provider_widget(gui, view_model) -> QWidget:
    return _EmbedProviderWidget(gui, view_model)


class _EmbedProviderWidget(QWidget):
    def __init__(self, gui, view_model):
        super().__init__()
        self._gui = gui
        self._current_preset_id: Optional[Any] = None
        self._is_loading = False
        self._key_url: str = ""
        self._known_local_models: tuple[str, ...] = ()
        self._items_revision = -1
        self._config_revision = -1

        self._setup_ui()
        self._view_model = view_model
        self._view_model.setParent(self)
        self._view_model.state_changed.connect(self.render)
        self._view_model.effect_emitted.connect(self.handle_effect)
        self.destroyed.connect(lambda _obj=None: self._view_model.close())
        self.dispatch_intent(ActivateEmbedProvider())

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
        self._preset_combo.setMinimumContentsLength(8)
        self._preset_combo.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
        self._preset_combo.currentIndexChanged.connect(self._on_preset_combo_changed)
        preset_row.addWidget(self._preset_combo, 1)
        self._add_btn = QToolButton()
        self._add_btn.setText("+")
        self._add_btn.setFixedWidth(24)
        tr_set(self._add_btn, "Добавить пресет", "Add preset", "setToolTip")
        self._add_btn.clicked.connect(self._on_add)
        self._del_btn = QToolButton()
        self._del_btn.setText("−")
        self._del_btn.setFixedWidth(24)
        tr_set(self._del_btn, "Удалить пресет", "Delete preset", "setToolTip")
        self._del_btn.clicked.connect(self._on_delete)
        self._up_btn = QToolButton()
        self._up_btn.setText("↑")
        self._up_btn.setFixedWidth(24)
        tr_set(self._up_btn, "Вверх", "Move up", "setToolTip")
        self._up_btn.clicked.connect(lambda: self._move_current_custom(-1))
        self._down_btn = QToolButton()
        self._down_btn.setText("↓")
        self._down_btn.setFixedWidth(24)
        tr_set(self._down_btn, "Вниз", "Move down", "setToolTip")
        self._down_btn.clicked.connect(lambda: self._move_current_custom(1))
        preset_row.addWidget(self._add_btn)
        preset_row.addWidget(self._del_btn)
        preset_row.addWidget(self._up_btn)
        preset_row.addWidget(self._down_btn)
        root.addLayout(preset_row)

        # Row: provider type
        type_row = QHBoxLayout()
        type_row.setSpacing(4)
        type_row.addWidget(QLabel(_("Тип:", "Type:")))
        self._provider_combo = QComboBox()
        self._provider_combo.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self._provider_combo.setMinimumContentsLength(8)
        self._provider_combo.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
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
        self._model_label = tr_set(QLabel(), "Модель:", "Model:")
        model_row.addWidget(self._model_label)
        self._model_combo = QComboBox()
        self._model_combo.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self._model_combo.setMinimumContentsLength(8)
        self._model_combo.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
        self._model_combo.currentTextChanged.connect(self._mark_dirty)
        model_row.addWidget(self._model_combo, 1)
        root.addLayout(model_row)

        self._manual_path_check = tr_set(QCheckBox(), "Ручное указание пути", "Manual path")
        tr_set(self._manual_path_check, "Выключено: выберите стандартную HuggingFace-модель, она хранится в папке checkpoints. "
            "Включено: поле модели становится ручным HF id или полным путем к папке модели.",
            "Off: choose a standard HuggingFace model stored under checkpoints. "
            "On: the model field becomes a manual HF id or full model directory path.", "setToolTip")
        self._manual_path_check.toggled.connect(self._on_manual_path_toggled)
        root.addWidget(self._manual_path_check)

        # Row: URL (API only)
        self._url_widget = SettingsBodyWidget()
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
        self._key_widget = SettingsBodyWidget()
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
        self._reserve_widget = SettingsBodyWidget()
        rv = QVBoxLayout(self._reserve_widget)
        rv.setContentsMargins(0, 0, 0, 0)
        rv.setSpacing(2)
        header_row = QHBoxLayout()
        header_row.setContentsMargins(0, 0, 0, 0)
        header_row.setSpacing(4)
        header_row.addWidget(QLabel(_("Резервные ключи (по строке):", "Reserve keys (one per line):")))
        self._reserve_eye = QToolButton()
        self._reserve_eye.setText("\U0001F441")
        self._reserve_eye.setCheckable(True)
        self._reserve_eye.setFixedWidth(24)
        tr_set(self._reserve_eye, "Показать/скрыть все ключи", "Show/hide all keys", "setToolTip")
        self._reserve_eye.toggled.connect(self._on_reserve_eye_toggled)
        header_row.addWidget(self._reserve_eye)
        header_row.addStretch()
        rv.addLayout(header_row)
        self._reserve_edit = QTextEdit()
        self._reserve_edit.setFixedHeight(48)
        self._reserve_masked = True
        self._reserve_original = ""
        self._reserve_edit.textChanged.connect(self._on_reserve_text_changed)
        rv.addWidget(self._reserve_edit)
        root.addWidget(self._reserve_widget)

        # HF token + download (local only)
        self._hf_widget = SettingsBodyWidget()
        hf_row = QHBoxLayout(self._hf_widget)
        hf_row.setContentsMargins(0, 0, 0, 0)
        hf_row.setSpacing(4)
        hf_row.addWidget(QLabel(_("HuggingFace токен:", "HuggingFace token:")))
        self._hf_edit = QLineEdit()
        self._hf_edit.setEchoMode(QLineEdit.EchoMode.Password)
        self._hf_edit.textChanged.connect(self._mark_dirty)
        self._hf_eye = QToolButton()
        self._hf_eye.setText("👁")
        self._hf_eye.setCheckable(True)
        self._hf_eye.setFixedWidth(24)
        self._hf_eye.toggled.connect(
            lambda on: self._hf_edit.setEchoMode(
                QLineEdit.EchoMode.Normal if on else QLineEdit.EchoMode.Password
            )
        )
        self._download_btn = tr_set(QPushButton(), "Скачать модель", "Download model")
        self._download_btn.clicked.connect(self._on_download_local_model)
        hf_row.addWidget(self._hf_edit, 1)
        hf_row.addWidget(self._hf_eye)
        hf_row.addWidget(self._download_btn)
        root.addWidget(self._hf_widget)

        # Row: query prefix
        prefix_row = QHBoxLayout()
        prefix_row.setSpacing(4)
        prefix_row.addWidget(QLabel(_("Префикс:", "Prefix:")))
        self._prefix_edit = QLineEdit()
        self._prefix_edit.setPlaceholderText('query: ')
        self._prefix_edit.textChanged.connect(self._mark_dirty)
        prefix_row.addWidget(self._prefix_edit, 1)
        root.addLayout(prefix_row)

        tune_row1 = QHBoxLayout()
        tune_row1.setSpacing(4)
        tune_row1.addWidget(QLabel(_("Batch:", "Batch:")))
        self._batch_edit = QLineEdit()
        self._batch_edit.setPlaceholderText("16")
        self._batch_edit.setMaximumWidth(70)
        self._batch_edit.textChanged.connect(self._mark_dirty)
        tune_row1.addWidget(self._batch_edit)
        tune_row1.addWidget(QLabel(_("Задержка:", "Delay:")))
        self._delay_edit = QLineEdit()
        self._delay_edit.setPlaceholderText("0.0")
        self._delay_edit.setMaximumWidth(70)
        self._delay_edit.textChanged.connect(self._mark_dirty)
        tune_row1.addWidget(self._delay_edit)
        tune_row1.addWidget(QLabel(_("Таймаут:", "Timeout:")))
        self._timeout_edit = QLineEdit()
        self._timeout_edit.setPlaceholderText("60")
        self._timeout_edit.setMaximumWidth(70)
        self._timeout_edit.textChanged.connect(self._mark_dirty)
        tune_row1.addWidget(self._timeout_edit)
        tune_row1.addStretch()
        root.addLayout(tune_row1)

        tune_row2 = QHBoxLayout()
        tune_row2.setSpacing(4)
        tune_row2.addWidget(QLabel(_("Повторы:", "Retries:")))
        self._retries_edit = QLineEdit()
        self._retries_edit.setPlaceholderText("2")
        self._retries_edit.setMaximumWidth(70)
        self._retries_edit.textChanged.connect(self._mark_dirty)
        tune_row2.addWidget(self._retries_edit)
        tune_row2.addWidget(QLabel(_("Пауза:", "Backoff:")))
        self._backoff_edit = QLineEdit()
        self._backoff_edit.setPlaceholderText("0.5")
        self._backoff_edit.setMaximumWidth(70)
        self._backoff_edit.textChanged.connect(self._mark_dirty)
        tune_row2.addWidget(self._backoff_edit)
        tune_row2.addStretch()
        root.addLayout(tune_row2)

        # Status label
        self._status_label = QLabel()
        self._status_label.setWordWrap(True)
        root.addWidget(self._status_label)

        # Action buttons
        btn_row = QHBoxLayout()
        btn_row.setSpacing(4)
        self._save_btn = tr_set(QPushButton(), "Сохранить", "Save")
        self._save_btn.clicked.connect(self._on_save)
        self._test_btn = tr_set(QPushButton(), "Тест", "Test")
        self._test_btn.clicked.connect(self._on_test)
        self._key_url_btn = tr_set(QPushButton(), "Получить ключ ↗", "Get key ↗")
        self._key_url_btn.setVisible(False)
        self._key_url_btn.clicked.connect(self._on_open_key_url)
        btn_row.addWidget(self._save_btn)
        btn_row.addWidget(self._test_btn)
        btn_row.addWidget(self._key_url_btn)
        btn_row.addStretch()
        root.addLayout(btn_row)

    # ── Data ──────────────────────────────────────────────────────────────────

    def _load_presets(self, select_id: Any = None, *, force: bool = False):
        self.dispatch_intent(
            RefreshEmbedPresets(
                selected_preset_id=select_id,
                force=bool(force),
            )
        )

    def _select_preset(self, preset_id: Any):
        idx = self._find_combo_index(preset_id)
        if idx >= 0:
            if self._preset_combo.currentIndex() == idx:
                # setCurrentIndex не эмитит сигнал при совпадении индекса — а после
                # _load_presets текущий индекс уже 0. Для первого пресета (local_hf/Qwen)
                # это значило, что редактор не подгружался и поле модели оставалось пустым.
                self._load_into_editor(preset_id)
            else:
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
        self.dispatch_intent(SelectEmbedPreset(preset_id))

    def _apply_loaded_cfg(self, preset_id: Any, cfg: Optional[Dict[str, Any]]):
        try:
            if not cfg:
                return
            self._current_preset_id = preset_id

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
            self._known_local_models = tuple(str(item) for item in known)
            manual_path = bool((cfg.get("extra") or {}).get("manual_path"))
            if is_local and model and model not in known:
                manual_path = True
            self._manual_path_check.blockSignals(True)
            self._manual_path_check.setChecked(manual_path)
            self._manual_path_check.blockSignals(False)
            self._model_combo.blockSignals(True)
            self._model_combo.setEditable(bool(not is_local or manual_path))
            self._model_combo.clear()
            if is_local and manual_path:
                self._model_combo.addItem(model)
            else:
                self._model_combo.addItems(known)
            if model and model not in known:
                self._model_combo.insertItem(0, model)
            mi = self._model_combo.findText(model) if model else -1
            self._model_combo.setCurrentIndex(mi if mi >= 0 else 0)
            if self._model_combo.isEditable() and self._model_combo.lineEdit():
                self._model_combo.lineEdit().textChanged.connect(self._mark_dirty)
            self._model_combo.blockSignals(False)

            self._model_label.setText(
                _("Модель / путь:", "Model / path:") if is_local and manual_path else _("Модель:", "Model:")
            )

            self._url_edit.setText(cfg.get("api_url") or "")
            self._key_edit.setText(cfg.get("api_key") or "")
            rk = cfg.get("reserve_keys") or []
            self._reserve_edit.blockSignals(True)
            self._reserve_original = "\n".join(rk)
            self._reserve_edit.setPlainText(self._reserve_original)
            self._reserve_edit.blockSignals(False)
            if self._reserve_masked:
                self._apply_masking()
            self._prefix_edit.setText(cfg.get("query_prefix") or "")
            extra = dict(cfg.get("extra") or {})
            self._batch_edit.setText(str(extra["batch_size"]) if "batch_size" in extra else "")
            self._delay_edit.setText(str(extra["request_delay_sec"]) if "request_delay_sec" in extra else "")
            self._timeout_edit.setText(str(extra["timeout_sec"]) if "timeout_sec" in extra else "")
            self._retries_edit.setText(str(extra["max_retries"]) if "max_retries" in extra else "")
            self._backoff_edit.setText(str(extra["retry_backoff_sec"]) if "retry_backoff_sec" in extra else "")

            self._key_url = cfg.get("key_url") or ""
            self._key_url_btn.setVisible(bool(self._key_url) and not is_local)
            self._hf_edit.setText(str(cfg.get("hf_token") or ""))
            self._refresh_download_btn()

            self._provider_combo.setEnabled(not is_builtin)
            self._url_edit.setReadOnly(False)
            self._del_btn.setEnabled(not is_builtin)
            self._up_btn.setEnabled(not is_builtin)
            self._down_btn.setEnabled(not is_builtin)

            self._apply_visibility(is_local)
            self._save_btn.setStyleSheet("")
        finally:
            self._is_loading = False

    def _apply_visibility(self, is_local: bool):
        self._url_widget.setVisible(not is_local)
        self._key_widget.setVisible(not is_local)
        self._reserve_widget.setVisible(not is_local)
        self._hf_widget.setVisible(is_local)
        self._manual_path_check.setVisible(is_local)
        self._download_btn.setEnabled(is_local and not self._manual_path_check.isChecked())

    def _on_provider_type_changed(self):
        if self._is_loading:
            return
        is_local = (self._provider_combo.currentData() == "local")
        self._apply_visibility(is_local)
        self._refresh_download_btn()
        self._mark_dirty()

    def _on_manual_path_toggled(self, checked: bool):
        if self._is_loading:
            return
        current = self._model_combo.currentText().strip()
        self._model_combo.blockSignals(True)
        self._model_combo.setEditable(checked)
        self._model_combo.clear()
        if checked:
            self._model_combo.addItem(current)
            self._model_label.setText(_("Модель / путь:", "Model / path:"))
        else:
            names = list(self._known_local_models)
            self._model_combo.addItems(names)
            if current in names:
                self._model_combo.setCurrentText(current)
            self._model_label.setText(_("Модель:", "Model:"))
        if self._model_combo.isEditable() and self._model_combo.lineEdit():
            self._model_combo.lineEdit().textChanged.connect(self._mark_dirty)
        self._model_combo.blockSignals(False)
        self._download_btn.setEnabled(not checked)
        self._mark_dirty()

    def _mark_dirty(self):
        if not self._is_loading:
            self._save_btn.setStyleSheet("font-weight: bold;")
            self._status_label.setStyleSheet("color: #d6922b;")
            self._status_label.setText(_(
                "Есть несохраненные изменения. Нажмите «Сохранить», иначе будет использоваться старый пресет.",
                "Unsaved changes. Press Save, otherwise the previous preset will be used.",
            ))

    def _on_reserve_text_changed(self):
        if self._reserve_masked:
            return
        text = self._reserve_edit.toPlainText()
        if text != self._reserve_original:
            self._reserve_original = text
            self._mark_dirty()

    def _on_reserve_eye_toggled(self, checked: bool):
        current = self._reserve_edit.toPlainText()
        if not self._reserve_masked:
            self._reserve_original = current
        self._reserve_masked = not checked
        self._reserve_edit.blockSignals(True)
        if self._reserve_masked:
            self._apply_masking()
        else:
            self._reserve_edit.setPlainText(self._reserve_original)
        self._reserve_edit.blockSignals(False)

    def _apply_masking(self):
        masked = "\n".join("\u2022" * len(ln) for ln in self._reserve_original.splitlines())
        self._reserve_edit.setPlainText(masked)

    # ── Actions ───────────────────────────────────────────────────────────────

    def _on_save(self):
        payload, hf_token = self._collect_payload()
        if payload is None:
            return
        self.dispatch_intent(
            SaveEmbedPreset(
                immutable_payload(payload),
                hf_token,
            )
        )

    def _collect_payload(self) -> tuple[dict[str, Any] | None, str]:
        pid = self._current_preset_id
        if pid is None:
            return None, ""
        provider = self._provider_combo.currentData() or "local"
        model = self._model_combo.currentText().strip()
        url = self._url_edit.text().strip()
        key = self._key_edit.text().strip()
        reserve_keys_text = self._reserve_original if self._reserve_masked else self._reserve_edit.toPlainText()
        reserve_keys = [l.strip() for l in reserve_keys_text.splitlines() if l.strip()]
        prefix = self._prefix_edit.text()
        hf_token = self._hf_edit.text().strip()
        extra: Dict[str, Any] = {}
        try:
            if self._batch_edit.text().strip():
                extra["batch_size"] = max(1, int(self._batch_edit.text().strip()))
        except Exception:
            pass
        try:
            if self._delay_edit.text().strip():
                extra["request_delay_sec"] = max(0.0, float(self._delay_edit.text().strip()))
        except Exception:
            pass
        try:
            if self._timeout_edit.text().strip():
                extra["timeout_sec"] = max(1.0, float(self._timeout_edit.text().strip()))
        except Exception:
            pass
        try:
            if self._retries_edit.text().strip():
                extra["max_retries"] = max(0, int(self._retries_edit.text().strip()))
        except Exception:
            pass
        try:
            if self._backoff_edit.text().strip():
                extra["retry_backoff_sec"] = max(0.0, float(self._backoff_edit.text().strip()))
        except Exception:
            pass
        if provider == "local":
            extra["manual_path"] = bool(self._manual_path_check.isChecked())

        data = {
            "id": pid,
            "provider_name": provider,
            "model": model,
            "url": url,
            "key": key,
            "reserve_keys": reserve_keys,
            "query_prefix": prefix,
            "extra": extra,
        }
        return data, hf_token

    def _on_add(self):
        from PyQt6.QtWidgets import QInputDialog
        name, ok = QInputDialog.getText(
            self, _("Новый пресет", "New preset"), _("Имя:", "Name:")
        )
        if not ok or not name.strip():
            return
        self.dispatch_intent(AddEmbedPreset(name.strip()))

    def _on_delete(self):
        pid = self._current_preset_id
        if pid is None or isinstance(pid, str):
            return
        self.dispatch_intent(DeleteEmbedPreset(pid))

    def _move_current_custom(self, delta: int):
        pid = self._current_preset_id
        if pid is None or isinstance(pid, str):
            return

        custom_ids = []
        for i in range(self._preset_combo.count()):
            item_id = self._preset_combo.itemData(i)
            if isinstance(item_id, int):
                custom_ids.append(item_id)
        try:
            cur_idx = custom_ids.index(int(pid))
        except Exception:
            return
        new_idx = cur_idx + int(delta)
        if new_idx < 0 or new_idx >= len(custom_ids):
            return
        custom_ids[cur_idx], custom_ids[new_idx] = custom_ids[new_idx], custom_ids[cur_idx]
        self.dispatch_intent(ReorderEmbedPresets(tuple(custom_ids)))

    def _on_test(self):
        self.dispatch_intent(TestEmbedPreset(self._current_preset_id))

    def _on_open_key_url(self):
        import webbrowser
        if self._key_url:
            webbrowser.open(self._key_url)

    def _on_download_local_model(self):
        payload, hf_token = self._collect_payload()
        if payload is None:
            return
        self.dispatch_intent(
            DownloadEmbedModel(
                immutable_payload(payload),
                hf_token,
            )
        )

    def _refresh_download_btn(self):
        is_local = (self._provider_combo.currentData() == "local")
        manual = bool(getattr(self, "_manual_path_check", None) and self._manual_path_check.isChecked())
        self._download_btn.setVisible(is_local and not manual)
        self._download_btn.setEnabled(is_local and not manual)
        if not is_local or manual:
            return
        if self._view_model.state.downloaded:
            self._download_btn.setText(_("Скачать заново", "Download again"))
        else:
            self._download_btn.setText(_("Скачать модель", "Download model"))

    def _get_current_display_name(self) -> str:
        return self._preset_combo.currentText().lstrip("✎ ").strip()

    def _refresh_index_status_async(self):
        if self._current_preset_id is not None:
            self.dispatch_intent(SelectEmbedPreset(self._current_preset_id))

    def _refresh_index_status(self):
        self._refresh_index_status_async()

    def dispatch_intent(self, intent) -> None:
        self._view_model.dispatch(intent)

    def render(self, state: EmbedProviderState) -> None:
        self._is_loading = bool(state.loading_presets or state.loading_config)
        if state.items_revision != self._items_revision:
            self._items_revision = state.items_revision
            self._preset_combo.blockSignals(True)
            try:
                self._preset_combo.clear()
                for label, item_id in state.preset_items:
                    self._preset_combo.addItem(str(label), userData=item_id)
                index = self._find_combo_index(state.selected_preset_id)
                if index >= 0:
                    self._preset_combo.setCurrentIndex(index)
            finally:
                self._preset_combo.blockSignals(False)

        if state.config_revision != self._config_revision and state.config is not None:
            self._config_revision = state.config_revision
            cfg = mutable_payload(state.config)
            self._apply_loaded_cfg(state.selected_preset_id, dict(cfg or {}))

        busy = bool(
            state.loading_presets
            or state.loading_config
            or state.operation is not None
        )
        self._preset_combo.setEnabled(not busy)
        self._add_btn.setEnabled(not busy)
        custom_selected = (
            state.selected_preset_id is not None
            and not isinstance(state.selected_preset_id, str)
        )
        self._del_btn.setEnabled(not busy and custom_selected)
        self._up_btn.setEnabled(not busy and custom_selected)
        self._down_btn.setEnabled(not busy and custom_selected)
        self._save_btn.setEnabled(not busy)
        self._test_btn.setEnabled(not busy and not state.testing)
        self._download_btn.setEnabled(
            not busy
            and self._provider_combo.currentData() == "local"
            and not self._manual_path_check.isChecked()
        )
        self._refresh_download_btn()

        if state.status_kind == "error":
            self._status_label.setStyleSheet("color: red;")
        elif state.status_kind == "success":
            self._status_label.setStyleSheet("color: #7fe38c;")
        else:
            self._status_label.setStyleSheet("")
        if state.status_text:
            self._status_label.setText(state.status_text)
        elif state.error:
            self._status_label.setText(state.error)

    def handle_effect(self, effect) -> None:
        if isinstance(effect, EmbedProviderShowError):
            self._status_label.setStyleSheet("color: red;")
            self._status_label.setText(effect.message)
