# src/ui/windows/asr_glossary_view.py
from __future__ import annotations

from PyQt6.QtCore import Qt, pyqtSignal, QTimer, QSize
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QListWidget, QListWidgetItem, QFrame, QScrollArea,
    QSplitter, QLineEdit, QComboBox, QCheckBox, QTabWidget, QTabBar
)

try:
    import qtawesome as qta
except Exception:
    qta = None

from core.events import get_event_bus, Events
from utils import getTranslationVariant as _
from styles.asr_model_styles import get_asr_stylesheet


class AsrModelListItemWidget(QWidget):
    def __init__(self, model_data: dict, parent=None):
        super().__init__(parent)
        self.model_data = model_data or {}
        self._build()

    def _build(self):
        mid = str(self.model_data.get("id", "unknown"))
        installed = bool(self.model_data.get("installed", False))

        lay = QHBoxLayout(self)
        lay.setContentsMargins(8, 4, 8, 4)
        lay.setSpacing(6)

        icon = QLabel()
        icon.setFixedSize(16, 16)
        if qta:
            try:
                name = "fa5s.check-circle" if installed else "fa5s.circle"
                col = "#4caf50" if installed else "#555555"
                icon.setPixmap(qta.icon(name, color=col).pixmap(16, 16))
            except Exception:
                icon.setText("●" if installed else "○")
        else:
            icon.setText("●" if installed else "○")
            icon.setStyleSheet(f"color: {'#4caf50' if installed else '#555555'}; font-weight: 700;")
        lay.addWidget(icon, 0)

        name_lbl = QLabel(self.model_data.get("name") or mid)
        name_lbl.setStyleSheet("font-size: 9pt;")
        lay.addWidget(name_lbl, 1)

        lay.addStretch()


class AsrGlossaryView(QWidget):
    request_install = pyqtSignal(str)
    request_refresh = pyqtSignal()

    asr_install_progress_signal = pyqtSignal(dict)
    asr_install_finished_signal = pyqtSignal(dict)
    asr_install_failed_signal = pyqtSignal(dict)

    def __init__(self):
        super().__init__()
        self.event_bus = get_event_bus()

        self._models: list[dict] = []
        self._current_engine: str | None = None

        self.setWindowTitle(_("ASR Модели", "ASR Models"))
        self.setStyleSheet(get_asr_stylesheet())
        self.setMinimumSize(820, 560)

        self._build_ui()

        self.asr_install_progress_signal.connect(self._on_install_progress_internal)
        self.asr_install_finished_signal.connect(self._on_install_finished_internal)
        self.asr_install_failed_signal.connect(self._on_install_failed_internal)

        QTimer.singleShot(0, lambda: self.request_refresh.emit())

    def refresh(self):
        try:
            res = self.event_bus.emit_and_wait(Events.Speech.GET_ASR_MODELS_GLOSSARY, timeout=2.0)
            self._models = res[0] if res and isinstance(res[0], list) else []
        except Exception:
            self._models = []
        self._rebuild_list(keep_selection=True)

    def on_install_progress(self, model: str, progress: int, status: str):
        self.asr_install_progress_signal.emit({"model": model, "progress": progress, "status": status})

    def on_install_finished(self, model: str):
        self.asr_install_finished_signal.emit({"model": model})

    def on_install_failed(self, model: str, error: str):
        self.asr_install_failed_signal.emit({"model": model, "error": error})

    def _build_ui(self):
        root = QHBoxLayout(self)
        root.setContentsMargins(8, 8, 8, 8)
        root.setSpacing(8)

        self.splitter = QSplitter(Qt.Orientation.Horizontal)
        self.splitter.setHandleWidth(4)
        root.addWidget(self.splitter, 1)

        left = QWidget()
        ll = QVBoxLayout(left)
        ll.setContentsMargins(0, 0, 0, 0)
        ll.setSpacing(6)

        search_row = QHBoxLayout()
        search_row.setContentsMargins(0, 0, 0, 0)
        search_row.setSpacing(6)

        self.search_box = QLineEdit()
        self.search_box.setObjectName("SearchBox")
        self.search_box.setPlaceholderText(_("Поиск...", "Search..."))
        self.search_box.textChanged.connect(self._apply_filter)
        search_row.addWidget(self.search_box, 1)

        self.btn_refresh_list = QPushButton()
        self.btn_refresh_list.setObjectName("SecondaryButton")
        self.btn_refresh_list.setFixedSize(32, 28)
        self.btn_refresh_list.setToolTip(_("Обновить", "Refresh"))
        if qta:
            try:
                self.btn_refresh_list.setIcon(qta.icon("fa5s.sync", color="#ffffff"))
            except Exception:
                pass
        self.btn_refresh_list.clicked.connect(lambda: self.request_refresh.emit())
        search_row.addWidget(self.btn_refresh_list, 0)

        ll.addLayout(search_row, 0)

        self.list_widget = QListWidget()
        self.list_widget.setObjectName("ModelsList")
        self.list_widget.setMouseTracking(True)
        self.list_widget.setSpacing(2)
        self.list_widget.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.list_widget.itemSelectionChanged.connect(self._on_selection_changed)
        ll.addWidget(self.list_widget, 1)

        self.splitter.addWidget(left)

        right = QWidget()
        rl = QVBoxLayout(right)
        rl.setContentsMargins(0, 0, 0, 0)
        rl.setSpacing(8)

        self.model_panel = QFrame()
        self.model_panel.setObjectName("ModelPanel")
        mp = QVBoxLayout(self.model_panel)
        mp.setContentsMargins(10, 8, 10, 8)
        mp.setSpacing(6)

        title_row = QHBoxLayout()
        title_row.setContentsMargins(0, 0, 0, 0)
        title_row.setSpacing(6)

        self.lbl_title = QLabel("—")
        self.lbl_title.setObjectName("TitleLabel")
        title_row.addWidget(self.lbl_title, 1)

        self.chip_status = QLabel("")
        self.chip_status.setVisible(False)
        self.chip_status.setObjectName("ChipInfo")
        title_row.addWidget(self.chip_status, 0)

        mp.addLayout(title_row)

        self.tags_row = QHBoxLayout()
        self.tags_row.setContentsMargins(0, 0, 0, 0)
        self.tags_row.setSpacing(6)
        mp.addLayout(self.tags_row)

        self.lbl_desc = QLabel("—")
        self.lbl_desc.setObjectName("Subtle")
        self.lbl_desc.setWordWrap(True)
        mp.addWidget(self.lbl_desc)

        mp.addStretch(1)

        action_row = QHBoxLayout()
        action_row.setContentsMargins(0, 2, 0, 0)
        action_row.setSpacing(8)

        self.lbl_progress = QLabel("")
        self.lbl_progress.setVisible(False)
        self.lbl_progress.setObjectName("Subtle")
        self.lbl_progress.setWordWrap(True)
        action_row.addWidget(self.lbl_progress, 1)

        self.btn_install = QPushButton(_("Установить", "Install"))
        self.btn_install.setObjectName("InstallButton")
        self.btn_install.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_install.setVisible(False)
        if qta:
            try:
                self.btn_install.setIcon(qta.icon("fa5s.download", color="#ffffff"))
            except Exception:
                pass
        self.btn_install.clicked.connect(self._on_install_clicked)
        action_row.addWidget(self.btn_install, 0, Qt.AlignmentFlag.AlignRight)

        mp.addLayout(action_row)

        rl.addWidget(self.model_panel, 0)

        self.detail_tabs = QTabWidget()
        self.detail_tabs.setObjectName("DetailTabs")
        rl.addWidget(self.detail_tabs, 1)

        self._build_tab_settings()
        self._build_tab_deps()

        self.splitter.addWidget(right)
        self.splitter.setSizes([320, 760])

    def _build_tab_settings(self):
        tab = QWidget()
        l = QVBoxLayout(tab)
        l.setContentsMargins(0, 0, 0, 0)
        l.setSpacing(0)

        self.settings_scroll = QScrollArea()
        self.settings_scroll.setWidgetResizable(True)
        self.settings_scroll.setFrameShape(QFrame.Shape.NoFrame)

        self.settings_holder = QWidget()
        self.settings_layout = QVBoxLayout(self.settings_holder)
        self.settings_layout.setContentsMargins(6, 6, 6, 6)
        self.settings_layout.setSpacing(6)

        self.settings_scroll.setWidget(self.settings_holder)
        l.addWidget(self.settings_scroll, 1)

        self.detail_tabs.addTab(tab, _("Настройки", "Settings"))

    def _build_tab_deps(self):
        tab = QWidget()
        l = QVBoxLayout(tab)
        l.setContentsMargins(0, 0, 0, 0)
        l.setSpacing(0)

        self.deps_scroll = QScrollArea()
        self.deps_scroll.setWidgetResizable(True)
        self.deps_scroll.setFrameShape(QFrame.Shape.NoFrame)

        self.deps_holder = QWidget()
        self.deps_layout = QVBoxLayout(self.deps_holder)
        self.deps_layout.setContentsMargins(6, 6, 6, 6)
        self.deps_layout.setSpacing(6)

        self.deps_scroll.setWidget(self.deps_holder)
        l.addWidget(self.deps_scroll, 1)

        self.deps_tab_index = self.detail_tabs.addTab(tab, _("Зависимости", "Dependencies"))

        self._deps_badge = QLabel("0")
        self._deps_badge.setObjectName("DepsBadge")
        self._deps_badge.setProperty("state", "ok")
        self._deps_badge.setVisible(False)
        self._deps_badge.setFixedSize(16, 16)

        tb = self.detail_tabs.tabBar()
        tb.setTabButton(self.deps_tab_index, QTabBar.ButtonPosition.RightSide, self._deps_badge)

    def _apply_filter(self, text: str):
        t = (text or "").strip().lower()
        for i in range(self.list_widget.count()):
            item = self.list_widget.item(i)
            mid = str(item.data(Qt.ItemDataRole.UserRole) or "").lower()
            name = str(item.data(Qt.ItemDataRole.ToolTipRole) or "").lower()
            item.setHidden(bool(t) and (t not in mid) and (t not in name))

    def _rebuild_list(self, keep_selection: bool = True):
        current_id = None
        if keep_selection and self.list_widget.currentItem():
            current_id = self.list_widget.currentItem().data(Qt.ItemDataRole.UserRole)

        self.list_widget.clear()

        for m in (self._models or []):
            mid = m.get("id")
            if not mid:
                continue

            item = QListWidgetItem()
            item.setData(Qt.ItemDataRole.UserRole, str(mid))
            item.setData(Qt.ItemDataRole.ToolTipRole, str(m.get("name") or mid))
            item.setSizeHint(QSize(0, 26))

            w = AsrModelListItemWidget(m)
            self.list_widget.addItem(item)
            self.list_widget.setItemWidget(item, w)

            if current_id and str(mid) == str(current_id):
                self.list_widget.setCurrentItem(item)

        if self.list_widget.count() and self.list_widget.currentRow() < 0:
            self.list_widget.setCurrentRow(0)

        if not self.list_widget.count():
            self._clear_details()

    def _on_selection_changed(self):
        item = self.list_widget.currentItem()
        if not item:
            self._current_engine = None
            self._clear_details()
            return

        mid = str(item.data(Qt.ItemDataRole.UserRole) or "")
        self._current_engine = mid

        data = self._find_model(mid)
        self._render_model_detail(mid, data)

    def _find_model(self, model_id: str) -> dict:
        for m in (self._models or []):
            if str(m.get("id")) == str(model_id):
                return m
        return {}

    def _clear_layout(self, layout):
        while layout.count():
            it = layout.takeAt(0)
            w = it.widget()
            if w:
                w.deleteLater()
            elif it.layout():
                self._clear_layout(it.layout())

    def _make_tag(self, text: str, more: bool = False) -> QLabel:
        lab = QLabel(text)
        lab.setObjectName("TagMore" if more else "Tag")
        return lab

    def _make_chip(self, text: str, kind: str) -> QLabel:
        lab = QLabel(text)
        if kind == "ok":
            lab.setObjectName("ChipOk")
        elif kind == "warn":
            lab.setObjectName("ChipWarn")
        else:
            lab.setObjectName("ChipInfo")
        return lab

    def _set_deps_badge(self, *, total: int, ok: bool):
        total = int(total)
        if total <= 0:
            self._deps_badge.setVisible(False)
            return
        self._deps_badge.setVisible(True)
        self._deps_badge.setText(str(total))
        self._deps_badge.setProperty("state", "ok" if ok else "warn")
        self._deps_badge.style().unpolish(self._deps_badge)
        self._deps_badge.style().polish(self._deps_badge)

    def _render_model_detail(self, engine_id: str, data: dict):
        name = str(data.get("name") or engine_id)
        installed = bool(data.get("installed", False))

        self.lbl_title.setText(name)

        self.chip_status.setVisible(True)
        if installed:
            self.chip_status.setText(_("Установлено", "Installed"))
            self.chip_status.setObjectName("ChipOk")
        else:
            self.chip_status.setText(_("Доступно", "Available"))
            self.chip_status.setObjectName("ChipInfo")
        self.chip_status.style().unpolish(self.chip_status)
        self.chip_status.style().polish(self.chip_status)

        self._render_tags(data)

        self.lbl_desc.setText(
            str(data.get("description") or data.get("desc") or _("Описание отсутствует.", "No description."))
        )

        self._render_settings(engine_id, installed)
        self._render_dependencies(data)

        self.btn_install.setVisible(not installed)
        self.btn_install.setEnabled(True)

        self.lbl_progress.setVisible(False)
        self.lbl_progress.setText("")
        self.lbl_progress.setObjectName("Subtle")
        self.lbl_progress.style().unpolish(self.lbl_progress)
        self.lbl_progress.style().polish(self.lbl_progress)

    def _render_tags(self, data: dict):
        self._clear_layout(self.tags_row)

        tags: list[QLabel] = []

        vendors = data.get("gpu_vendor") or data.get("gpu_vendors") or data.get("vendors")
        if isinstance(vendors, str):
            vendors = [vendors]
        if isinstance(vendors, (list, tuple)):
            for v in vendors:
                if v:
                    tags.append(self._make_tag(str(v)))

        langs = data.get("languages") or data.get("langs")
        if isinstance(langs, str):
            langs = [langs]
        if isinstance(langs, (list, tuple)) and langs:
            max_lang = 8
            visible = [str(x) for x in langs[:max_lang]]
            hidden = [str(x) for x in langs[max_lang:]]
            for lg in visible:
                tags.append(self._make_tag(lg))
            if hidden:
                more = self._make_tag(f"+{len(hidden)}", more=True)
                more.setToolTip("\n".join(hidden))
                tags.append(more)

        purpose = data.get("tags") or data.get("intents") or data.get("purpose")
        if isinstance(purpose, str):
            purpose = [purpose]
        if isinstance(purpose, (list, tuple)):
            for p in purpose[:6]:
                if p:
                    tags.append(self._make_tag(str(p)))

        if not tags:
            self.tags_row.addWidget(self._make_chip(_("Нет тегов", "No tags"), "info"))
            self.tags_row.addStretch()
            return

        for w in tags:
            self.tags_row.addWidget(w, 0, Qt.AlignmentFlag.AlignVCenter)
        self.tags_row.addStretch()

    def _render_settings(self, engine_id: str, installed: bool):
        self._clear_layout(self.settings_layout)

        if not installed:
            placeholder = QLabel(
                _("Модель не установлена.\nНажмите «Установить», чтобы начать загрузку.",
                  "Model is not installed.\nClick “Install” to start downloading.")
            )
            placeholder.setAlignment(Qt.AlignmentFlag.AlignCenter)
            placeholder.setWordWrap(True)
            placeholder.setObjectName("Subtle")
            self.settings_layout.addWidget(placeholder)
            self.settings_layout.addStretch()
            return

        schema_res = self.event_bus.emit_and_wait(
            Events.Speech.GET_RECOGNIZER_SETTINGS_SCHEMA, {"engine": engine_id}, timeout=1.0
        )
        schema = schema_res[0] if schema_res else []

        vals_res = self.event_bus.emit_and_wait(
            Events.Speech.GET_RECOGNIZER_SETTINGS, {"engine": engine_id}, timeout=1.0
        )
        values = vals_res[0] if vals_res else {}

        if not schema:
            lbl = QLabel(_("Нет настроек для этой модели.", "No settings for this model."))
            lbl.setObjectName("Subtle")
            self.settings_layout.addWidget(lbl)
            self.settings_layout.addStretch()
            return

        for field in schema:
            key = field.get("key")
            if not key:
                continue

            label_txt = _(field.get("label_ru", key), field.get("label_en", key))
            ftype = field.get("type", "entry")
            val = values.get(key, field.get("default"))

            row = QFrame()
            row.setObjectName("SettingRow")
            hl = QHBoxLayout(row)
            hl.setContentsMargins(0, 0, 0, 0)
            hl.setSpacing(6)

            left = QFrame()
            left.setObjectName("SettingLabel")
            ll = QHBoxLayout(left)
            ll.setContentsMargins(10, 0, 10, 0)
            ll.setSpacing(0)
            ll.addWidget(QLabel(str(label_txt)), 0, Qt.AlignmentFlag.AlignVCenter)

            right = QFrame()
            right.setObjectName("SettingWidget")
            rl = QHBoxLayout(right)
            rl.setContentsMargins(0, 0, 0, 0)
            rl.setSpacing(0)

            if ftype == "combobox":
                w = QComboBox()
                opts = field.get("options", []) or []
                w.addItems([str(x) for x in opts])
                idx = w.findText(str(val))
                if idx >= 0:
                    w.setCurrentIndex(idx)
                w.currentTextChanged.connect(
                    lambda v, e=engine_id, k=key: self.event_bus.emit(
                        Events.Speech.SET_RECOGNIZER_OPTION, {"engine": e, "key": k, "value": v}
                    )
                )
                rl.addWidget(w, 0, Qt.AlignmentFlag.AlignVCenter)

            elif ftype == "check":
                w = QCheckBox()
                w.setChecked(bool(val))
                w.toggled.connect(
                    lambda state, e=engine_id, k=key: self.event_bus.emit(
                        Events.Speech.SET_RECOGNIZER_OPTION, {"engine": e, "key": k, "value": bool(state)}
                    )
                )
                rl.addWidget(w, 0, Qt.AlignmentFlag.AlignVCenter)
                rl.addStretch()

            else:
                w = QLineEdit("" if val is None else str(val))
                w.editingFinished.connect(
                    lambda ww=w, e=engine_id, k=key: self.event_bus.emit(
                        Events.Speech.SET_RECOGNIZER_OPTION, {"engine": e, "key": k, "value": ww.text().strip()}
                    )
                )
                rl.addWidget(w, 0, Qt.AlignmentFlag.AlignVCenter)

            hl.addWidget(left, 4)
            hl.addWidget(right, 6)
            self.settings_layout.addWidget(row)

        self.settings_layout.addStretch()

    def _render_dependencies(self, data: dict):
        self._clear_layout(self.deps_layout)

        details = data.get("details", []) or []
        total = len(details)
        missing = [d for d in details if not bool(d.get("ok", False))]

        self._set_deps_badge(total=total, ok=(total == 0 or len(missing) == 0))

        if total == 0:
            lbl = QLabel(_("Для этой модели не предоставлен список зависимостей.", "This model provides no dependency list."))
            lbl.setObjectName("Subtle")
            lbl.setWordWrap(True)
            self.deps_layout.addWidget(lbl)
            self.deps_layout.addStretch()
            return

        for dep in details:
            dep_id = str(dep.get("id") or "unknown")
            ok = bool(dep.get("ok", False))

            row = QFrame()
            row.setObjectName("DepRow")
            hl = QHBoxLayout(row)
            hl.setContentsMargins(10, 8, 10, 8)
            hl.setSpacing(10)

            ic = QLabel()
            ic.setFixedSize(14, 14)
            if qta:
                try:
                    name = "fa5s.check" if ok else "fa5s.times"
                    col = "#4caf50" if ok else "#e25757"
                    ic.setPixmap(qta.icon(name, color=col).pixmap(14, 14))
                except Exception:
                    ic.setText("✓" if ok else "✗")
            else:
                ic.setText("✓" if ok else "✗")
                ic.setStyleSheet(f"color: {'#4caf50' if ok else '#e25757'}; font-weight: 700;")
            hl.addWidget(ic, 0, Qt.AlignmentFlag.AlignVCenter)

            name = QLabel(dep_id)
            hl.addWidget(name, 1, Qt.AlignmentFlag.AlignVCenter)

            state = self._make_chip(_("OK", "OK"), "ok") if ok else self._make_chip(_("Отсутствует", "Missing"), "warn")
            hl.addWidget(state, 0, Qt.AlignmentFlag.AlignVCenter)

            self.deps_layout.addWidget(row)

        self.deps_layout.addStretch()

    def _clear_details(self):
        self.lbl_title.setText("—")
        self.lbl_desc.setText("—")
        self.btn_install.setVisible(False)
        self.chip_status.setVisible(False)
        self.lbl_progress.setVisible(False)
        self._clear_layout(self.tags_row)
        self._clear_layout(self.settings_layout)
        self._clear_layout(self.deps_layout)
        self.settings_layout.addStretch()
        self.deps_layout.addStretch()
        self._set_deps_badge(total=0, ok=True)

    def _on_install_clicked(self):
        if not self._current_engine:
            return
        self.btn_install.setEnabled(False)
        self.lbl_progress.setVisible(True)
        self.lbl_progress.setObjectName("Subtle")
        self.lbl_progress.setText(_("Подготовка...", "Preparing..."))
        self.request_install.emit(self._current_engine)

    def _on_install_progress_internal(self, data: dict):
        if str(data.get("model") or "") != str(self._current_engine or ""):
            return
        status = str(data.get("status", "") or "")
        progress = int(data.get("progress", 0) or 0)
        self.lbl_progress.setVisible(True)
        self.lbl_progress.setObjectName("Subtle")
        self.lbl_progress.setText(f"{status} ({progress}%)")
        self.lbl_progress.style().unpolish(self.lbl_progress)
        self.lbl_progress.style().polish(self.lbl_progress)

    def _on_install_finished_internal(self, data: dict):
        if str(data.get("model") or "") != str(self._current_engine or ""):
            return
        self.lbl_progress.setVisible(True)
        self.lbl_progress.setObjectName("ChipOk")
        self.lbl_progress.setText(_("Успешно установлено", "Installed successfully"))
        self.lbl_progress.style().unpolish(self.lbl_progress)
        self.lbl_progress.style().polish(self.lbl_progress)
        QTimer.singleShot(250, self.refresh)

    def _on_install_failed_internal(self, data: dict):
        if str(data.get("model") or "") != str(self._current_engine or ""):
            return
        err = str(data.get("error", "") or "")
        self.lbl_progress.setVisible(True)
        self.lbl_progress.setObjectName("ChipWarn")
        self.lbl_progress.setText((_("Ошибка: ", "Error: ") + err) if err else _("Ошибка установки", "Install failed"))
        self.lbl_progress.style().unpolish(self.lbl_progress)
        self.lbl_progress.style().polish(self.lbl_progress)
        self.btn_install.setEnabled(True)