# src/ui/windows/asr_glossary_view.py
from __future__ import annotations

from PyQt6.QtCore import Qt, pyqtSignal, QTimer, QSize
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QListWidget, QListWidgetItem, QFrame, QScrollArea,
    QSplitter, QCheckBox, QLineEdit, QComboBox, QSizePolicy,
    QGridLayout
)

try:
    import qtawesome as qta
except ImportError:
    qta = None

from core.events import get_event_bus, Events
from utils import getTranslationVariant as _
from styles.asr_model_styles import get_asr_stylesheet
from styles.main_styles import get_theme

from main_logger import logger

class AsrModelListItemWidget(QWidget):
    """Компактный виджет элемента списка (Иконка + Имя + Индикатор)"""
    def __init__(self, model_id: str, installed: bool, parent=None):
        super().__init__(parent)
        self.model_id = str(model_id)
        self.installed = bool(installed)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(8, 6, 8, 6)
        layout.setSpacing(10)

        self.icon_lbl = QLabel()
        self.icon_lbl.setFixedSize(18, 18)
        if qta:
            icon_name = 'fa5b.google' if 'google' in self.model_id.lower() else 'fa5s.microphone-alt'
            color = '#e6e6eb' if self.installed else '#7f8c8d'
            self.icon_lbl.setPixmap(qta.icon(icon_name, color=color).pixmap(18, 18))
        else:
            self.icon_lbl.setText("●")
        layout.addWidget(self.icon_lbl)

        name_lbl = QLabel(self.model_id.upper() if len(self.model_id) < 4 else self.model_id.capitalize())
        name_lbl.setStyleSheet(
            f"font-weight: 600; font-size: 10pt; color: {'#e6e6eb' if self.installed else '#7f8c8d'};"
        )
        layout.addWidget(name_lbl)

        layout.addStretch()

        if self.installed:
            status_icon = QLabel()
            if qta:
                status_icon.setPixmap(qta.icon('fa5s.check', color='#4caf50').pixmap(14, 14))
            else:
                status_icon.setText("✓")
                status_icon.setStyleSheet("color: #4caf50")
            layout.addWidget(status_icon)

class AsrGlossaryView(QWidget):
    # Сигналы для взаимодействия с контроллером (инициация действий)
    request_install = pyqtSignal(str)
    request_refresh = pyqtSignal()
    
    # Внутренние сигналы для обновления UI из потоков
    asr_install_progress_signal = pyqtSignal(dict)
    asr_install_finished_signal = pyqtSignal(dict)
    asr_install_failed_signal = pyqtSignal(dict)

    def __init__(self):
        super().__init__()
        self.event_bus = get_event_bus()
        self.theme = get_theme()
        
        self._models: list[dict] = []
        self._current_engine: str | None = None
        
        self.setWindowTitle(_("ASR Модели", "ASR Models"))
        self.setStyleSheet(get_asr_stylesheet())
        self.setMinimumSize(900, 650)

        self._build_ui()
        
        # Подключаем внутренние сигналы к методам отрисовки
        self.asr_install_progress_signal.connect(self._on_install_progress_internal)
        self.asr_install_finished_signal.connect(self._on_install_finished_internal)
        self.asr_install_failed_signal.connect(self._on_install_failed_internal)

        QTimer.singleShot(0, lambda: self.request_refresh.emit())

    def _build_ui(self):
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)

        # Splitter: Список | Детали
        self.splitter = QSplitter(Qt.Orientation.Horizontal)
        self.splitter.setHandleWidth(1)
        main_layout.addWidget(self.splitter)

        # === ЛЕВАЯ ПАНЕЛЬ (Список) ===
        left_widget = QWidget()
        left_layout = QVBoxLayout(left_widget)
        left_layout.setContentsMargins(0, 0, 0, 0)
        left_layout.setSpacing(0)

        # Хедер списка
        list_header = QFrame()
        list_header.setStyleSheet(f"background: {self.theme['panel_bg']}; border-bottom: 1px solid {self.theme['outline']};")
        lh_layout = QVBoxLayout(list_header)
        lh_layout.setContentsMargins(12, 12, 12, 12)
        
        lbl_title = QLabel(_("Движки распознавания", "Recognition Engines"))
        lbl_title.setStyleSheet("font-weight: 700; color: #muted; font-size: 10pt;")
        lh_layout.addWidget(lbl_title)
        
        left_layout.addWidget(list_header)

        # Сам список
        self.list_widget = QListWidget()
        self.list_widget.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.list_widget.itemSelectionChanged.connect(self._on_selection_changed)
        left_layout.addWidget(self.list_widget)

        # Кнопка обновления внизу
        btn_refresh = QPushButton()
        btn_refresh.setToolTip(_("Обновить список", "Refresh List"))
        if qta:
            btn_refresh.setIcon(qta.icon('fa5s.sync-alt', color=self.theme['text']))
        btn_refresh.setFlat(True)
        btn_refresh.clicked.connect(lambda: self.request_refresh.emit())
        
        bot_bar = QFrame()
        bot_bar.setStyleSheet(f"background: {self.theme['panel_bg']}; border-top: 1px solid {self.theme['outline']};")
        bb_layout = QHBoxLayout(bot_bar)
        bb_layout.setContentsMargins(4, 4, 4, 4)
        bb_layout.addStretch()
        bb_layout.addWidget(btn_refresh)
        left_layout.addWidget(bot_bar)

        self.splitter.addWidget(left_widget)

        # === ПРАВАЯ ПАНЕЛЬ (Детали и Настройки) ===
        self.detail_panel = QFrame()
        self.detail_panel.setObjectName("DetailPanel")
        detail_layout = QVBoxLayout(self.detail_panel)
        detail_layout.setContentsMargins(24, 24, 24, 24)
        detail_layout.setSpacing(16)

        # Хедер модели
        self.header_row = QHBoxLayout()
        self.header_row.setSpacing(12)
        
        self.lbl_model_name = QLabel()
        self.lbl_model_name.setObjectName("ModelTitle")
        self.header_row.addWidget(self.lbl_model_name)
        
        self.lbl_status_chip = QLabel()
        self.lbl_status_chip.setObjectName("StatusChip")
        self.header_row.addWidget(self.lbl_status_chip)
        
        self.header_row.addStretch()
        
        self.btn_install = QPushButton(_("Установить", "Install"))
        self.btn_install.setObjectName("PrimaryButton")
        self.btn_install.setCursor(Qt.CursorShape.PointingHandCursor)
        if qta:
            self.btn_install.setIcon(qta.icon('fa5s.download', color='white'))
        self.btn_install.clicked.connect(self._on_install_clicked)
        self.btn_install.setVisible(False)
        self.header_row.addWidget(self.btn_install)
        
        detail_layout.addLayout(self.header_row)

        # Прогресс бар установки (текстовый)
        self.lbl_progress = QLabel()
        self.lbl_progress.setStyleSheet(f"color: {self.theme['accent']}; font-weight: 600;")
        self.lbl_progress.setVisible(False)
        detail_layout.addWidget(self.lbl_progress)

        # Разделитель
        line = QFrame()
        line.setFrameShape(QFrame.Shape.HLine)
        line.setStyleSheet(f"color: {self.theme['border_soft']};")
        detail_layout.addWidget(line)

        # Область скролла для настроек
        self.scroll_area = QScrollArea()
        self.scroll_area.setWidgetResizable(True)
        self.scroll_area.setFrameShape(QFrame.Shape.NoFrame)
        self.scroll_area.setStyleSheet("background: transparent;")
        
        self.settings_container = QWidget()
        self.settings_container.setStyleSheet("background: transparent;")
        self.settings_layout = QVBoxLayout(self.settings_container)
        self.settings_layout.setContentsMargins(0, 10, 10, 10)
        self.settings_layout.setSpacing(12)
        self.settings_layout.addStretch()
        
        self.scroll_area.setWidget(self.settings_container)
        detail_layout.addWidget(self.scroll_area, 1)

        # Блок зависимостей (внизу)
        self.deps_widget = QFrame()
        self.deps_widget.setObjectName("DepsPanel")
        self.deps_layout = QVBoxLayout(self.deps_widget)
        self.deps_layout.setContentsMargins(16, 16, 16, 16)
        self.deps_layout.setSpacing(10)
        
        lbl_deps = QLabel(_("Системные требования", "System Requirements"))
        lbl_deps.setStyleSheet(f"color: {self.theme['muted']}; font-size: 9pt; font-weight: 700; text-transform: uppercase;")
        self.deps_layout.addWidget(lbl_deps)
        
        self.deps_items_layout = QGridLayout()
        self.deps_items_layout.setSpacing(10)
        self.deps_layout.addLayout(self.deps_items_layout)
        
        detail_layout.addWidget(self.deps_widget)

        self.splitter.addWidget(self.detail_panel)
        self.splitter.setSizes([260, 640])

    # --- PUBLIC API ДЛЯ КОНТРОЛЛЕРА ---
    # Эти методы дергает контроллер напрямую! Не удалять!

    def on_install_progress(self, model: str, progress: int, status: str):
        """Вызывается контроллером при прогрессе установки"""
        self.asr_install_progress_signal.emit({"model": model, "progress": progress, "status": status})

    def on_install_finished(self, model: str):
        """Вызывается контроллером при завершении установки"""
        self.asr_install_finished_signal.emit({"model": model})

    def on_install_failed(self, model: str, error: str):
        """Вызывается контроллером при ошибке установки"""
        self.asr_install_failed_signal.emit({"model": model, "error": error})

    # --- ВНУТРЕННЯЯ ЛОГИКА ---

    def refresh(self):
        """Внешний вызов обновления данных"""
        logger.notify("[DEBUG] View: Вход в refresh()")  # <--- ДОБАВИТЬ
        try:
            # ВОТ ТУТ СКОРЕЕ ВСЕГО ВИСНЕТ:
            logger.notify("[DEBUG] View: Вызов emit_and_wait(GET_ASR_MODELS_GLOSSARY)...")  # <--- ДОБАВИТЬ
            models_data = self.event_bus.emit_and_wait(Events.Speech.GET_ASR_MODELS_GLOSSARY, timeout=2.0)
            logger.notify("[DEBUG] View: emit_and_wait вернул данные")  # <--- ДОБАВИТЬ
            
            self._models = models_data[0] if models_data and isinstance(models_data[0], list) else []
            self._rebuild_list()
            logger.notify("[DEBUG] View: refresh() завершен")  # <--- ДОБАВИТЬ
        except Exception as e:
            logger.notify(f"[DEBUG] View: Ошибка в refresh: {e}")

    def _rebuild_list(self):
        current_id = None
        if self.list_widget.currentItem():
            current_id = self.list_widget.currentItem().data(Qt.ItemDataRole.UserRole)

        self.list_widget.clear()

        # Показываем ВСЕ модели (галка и фильтрация удалены)
        for model in self._models:
            mid = model.get("id", "unknown")
            installed = bool(model.get("installed"))

            item = QListWidgetItem()
            item.setData(Qt.ItemDataRole.UserRole, mid)
            # Высота элемента чуть больше для воздуха
            item.setSizeHint(QSize(0, 42))

            widget = AsrModelListItemWidget(mid, installed)
            self.list_widget.addItem(item)
            self.list_widget.setItemWidget(item, widget)

            if mid == current_id:
                self.list_widget.setCurrentItem(item)

        # Выбор первого, если ничего не выбрано
        if not self.list_widget.currentItem() and self.list_widget.count() > 0:
            self.list_widget.setCurrentRow(0)
        elif self.list_widget.count() == 0:
            self._clear_details()

    def _on_selection_changed(self):
        item = self.list_widget.currentItem()
        if not item:
            self._current_engine = None
            self._clear_details()
            return

        engine_id = item.data(Qt.ItemDataRole.UserRole)
        self._current_engine = engine_id
        
        model_data = next((m for m in self._models if m.get("id") == engine_id), {})
        self._populate_details(engine_id, model_data)

    def _clear_details(self):
        self.lbl_model_name.setText("")
        self.lbl_status_chip.setVisible(False)
        self.btn_install.setVisible(False)
        self.deps_widget.setVisible(False)
        
        # Очистка настроек
        while self.settings_layout.count():
            item = self.settings_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        self.settings_layout.addStretch()

    def _populate_details(self, engine_id: str, data: dict):
        installed = data.get("installed", False)
        
        # Заголовок
        self.lbl_model_name.setText(engine_id.upper() if len(engine_id) < 4 else engine_id.capitalize())
        
        # Чип статуса
        self.lbl_status_chip.setVisible(True)
        if installed:
            self.lbl_status_chip.setText(_("Установлено", "Installed"))
            self.lbl_status_chip.setStyleSheet(f"background: rgba(61,166,110,0.15); color: #9be2bc; border: 1px solid rgba(61,166,110,0.3);")
        else:
            self.lbl_status_chip.setText(_("Доступно", "Available"))
            self.lbl_status_chip.setStyleSheet(f"background: {self.theme['chip_bg']}; color: {self.theme['muted']}; border: 1px solid {self.theme['outline']};")

        # Кнопка установки
        self.btn_install.setVisible(not installed)
        self.btn_install.setEnabled(True)
        self.lbl_progress.setVisible(False)

        # Зависимости
        self._render_dependencies(data)

        # Настройки
        self._render_settings(engine_id)

    def _render_settings(self, engine_id: str):
        # Очистка
        while self.settings_layout.count():
            item = self.settings_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        # Запрос схемы
        schema_res = self.event_bus.emit_and_wait(Events.Speech.GET_RECOGNIZER_SETTINGS_SCHEMA, {'engine': engine_id}, timeout=0.5)
        schema = schema_res[0] if schema_res else []
        
        # Запрос значений
        val_res = self.event_bus.emit_and_wait(Events.Speech.GET_RECOGNIZER_SETTINGS, {'engine': engine_id}, timeout=0.5)
        values = val_res[0] if val_res else {}

        if not schema:
            lbl = QLabel(_("Нет доступных настроек.", "No settings available."))
            lbl.setStyleSheet(f"color: {self.theme['muted']}; font-style: italic; padding: 10px;")
            self.settings_layout.addWidget(lbl)
            self.settings_layout.addStretch()
            return

        for field in schema:
            key = field.get("key")
            label = _(field.get("label_ru", key), field.get("label_en", key))
            ftype = field.get("type", "entry")
            val = values.get(key, field.get("default"))

            row = QFrame()
            row.setObjectName("SettingRow")
            rl = QHBoxLayout(row)
            rl.setContentsMargins(0, 4, 0, 4)
            rl.setSpacing(12)

            lbl_w = QLabel(label)
            lbl_w.setObjectName("SettingLabel")
            lbl_w.setMinimumWidth(150)
            rl.addWidget(lbl_w)

            widget = None
            if ftype == "combobox":
                widget = QComboBox()
                opts = field.get("options", [])
                widget.addItems([str(x) for x in opts])
                idx = widget.findText(str(val))
                if idx >= 0: widget.setCurrentIndex(idx)
                widget.currentTextChanged.connect(lambda v, k=key: self._on_setting_change(engine_id, k, v))
                rl.addWidget(widget, 1)

            elif ftype == "check":
                widget = QCheckBox()
                widget.setChecked(bool(val))
                widget.toggled.connect(lambda c, k=key: self._on_setting_change(engine_id, k, c))
                rl.addWidget(widget)
                rl.addStretch()

            else:
                widget = QLineEdit(str(val))
                widget.editingFinished.connect(lambda w=widget, k=key: self._on_setting_change(engine_id, k, w.text()))
                rl.addWidget(widget, 1)

            self.settings_layout.addWidget(row)
        
        self.settings_layout.addStretch()

    def _on_setting_change(self, engine, key, value):
        self.event_bus.emit(Events.Speech.SET_RECOGNIZER_OPTION, {'engine': engine, 'key': key, 'value': value})

    def _render_dependencies(self, data):
        # Очистка сетки
        while self.deps_items_layout.count():
            child = self.deps_items_layout.takeAt(0)
            if child.widget(): child.widget().deleteLater()

        details = data.get("details", [])
        if not details:
            self.deps_widget.setVisible(False)
            return
        
        self.deps_widget.setVisible(True)
        
        col = 0
        row = 0
        for dep in details:
            d_id = dep.get("id")
            ok = dep.get("ok", False)
            
            # Создаем "чип" (рамку) для каждой зависимости
            chip = QFrame()
            chip.setObjectName("DepChip")
            cl = QHBoxLayout(chip)
            cl.setContentsMargins(8, 6, 8, 6) # Внутренние отступы (padding)
            cl.setSpacing(8)
            
            icon = QLabel()
            icon.setFixedSize(14, 14)
            if qta:
                ic_name = 'fa5s.check' if ok else 'fa5s.times'
                ic_col = '#4caf50' if ok else '#e74c3c'
                icon.setPixmap(qta.icon(ic_name, color=ic_col).pixmap(14, 14))
            else:
                icon.setText("✓" if ok else "✗")
                icon.setStyleSheet(f"color: {'#4caf50' if ok else '#e74c3c'}; font-weight: bold;")
            cl.addWidget(icon)
            
            lbl = QLabel(d_id)
            lbl.setStyleSheet(f"color: {self.theme['text']}; font-size: 9pt; font-weight: 500;")
            cl.addWidget(lbl)
            
            cl.addStretch()
            
            # Добавляем чип в сетку
            self.deps_items_layout.addWidget(chip, row, col)
            
            col += 1
            if col > 1: # 2 колонки
                col = 0
                row += 1

    # --- Обработчики установки ---

    def _on_install_clicked(self):
        if self._current_engine:
            self.btn_install.setEnabled(False)
            self.lbl_progress.setVisible(True)
            self.lbl_progress.setText(_("Подготовка...", "Preparing..."))
            self.request_install.emit(self._current_engine)

    # --- ВНУТРЕННИЕ Callbacks от сигналов (Thread-Safe) ---

    def _on_install_progress_internal(self, data: dict):
        model = data.get("model")
        if model != self._current_engine:
            return
        
        status = data.get("status", "")
        progress = int(data.get("progress", 0))
        self.lbl_progress.setText(f"{status} ({progress}%)")

    def _on_install_finished_internal(self, data):
        model = data.get("model")
        logger.notify(f"[DEBUG] View: Получен сигнал finished для {model}")
        if model == self._current_engine:
            self.lbl_progress.setText(_("Успешно!", "Success!"))
            self.btn_install.setVisible(False)
            # Обновить UI через таймер
            logger.notify("[DEBUG] View: Запуск таймера обновления refresh через 1с")
            QTimer.singleShot(1000, self.refresh)

    def _on_install_failed_internal(self, data):
        model = data.get("model")
        if model == self._current_engine:
            err = data.get("error", "")
            self.lbl_progress.setText(_("Ошибка: ", "Error: ") + err)
            self.lbl_progress.setStyleSheet(f"color: {self.theme['danger']};")
            self.btn_install.setEnabled(True)