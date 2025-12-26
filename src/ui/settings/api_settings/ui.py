from PyQt6.QtCore import Qt, QSize, QStringListModel
from PyQt6.QtWidgets import (
    QWidget, QFrame, QLabel, QVBoxLayout, QHBoxLayout, QListWidget, QPushButton,
    QToolButton, QComboBox, QSpacerItem, QSizePolicy, QCompleter, QLineEdit
)
import qtawesome as qta

from utils import _
from .widgets import ProviderDelegate
from ui.gui_templates import create_section_header

def build_api_settings_ui(self, parent_layout):
    # Главный контейнер
    main_container = QWidget()
    main_layout = QVBoxLayout(main_container)
    main_layout.setContentsMargins(0, 0, 0, 0)
    main_layout.setSpacing(5)
    
    create_section_header(main_layout, _("Каталог промптов", "Prompt Catalogue"))
    
    # Разделитель
    separator = QFrame()
    separator.setFrameShape(QFrame.Shape.HLine)
    separator.setFrameShadow(QFrame.Shadow.Sunken)
    separator.setObjectName("SeparatorH")
    main_layout.addWidget(separator)
    
    # 2. Панель со списком пресетов
    custom_presets_frame = QFrame()
    custom_presets_frame.setObjectName("PresetsPanel")
    custom_presets_frame.setFixedHeight(150)

    presets_layout = QHBoxLayout(custom_presets_frame)
    presets_layout.setContentsMargins(8, 8, 8, 8)
    presets_layout.setSpacing(10)

    # Список пресетов
    self.custom_presets_list = QListWidget()
    self.custom_presets_list.setObjectName("PresetsList")
    presets_layout.addWidget(self.custom_presets_list, 1)

    # Панель с кнопками
    buttons_layout = QVBoxLayout()
    buttons_layout.setContentsMargins(0, 0, 0, 0)
    buttons_layout.setSpacing(0)


    self.add_preset_btn = QPushButton()
    self.add_preset_btn.setObjectName("AddPresetButton")
    self.add_preset_btn.setIcon(qta.icon('fa5s.plus', color='#e6e6e6'))
    self.add_preset_btn.setToolTip(_("Добавить пресет", "Add preset"))
    self.add_preset_btn.setFixedSize(28, 28)
    self.add_preset_btn.setIconSize(QSize(14, 14))

    self.remove_preset_btn = QPushButton()
    self.remove_preset_btn.setObjectName("RemovePresetButton")
    self.remove_preset_btn.setIcon(qta.icon('fa5s.minus', color='#e6e6e6'))
    self.remove_preset_btn.setToolTip(_("Удалить пресет", "Remove preset"))
    self.remove_preset_btn.setEnabled(False)
    self.remove_preset_btn.setFixedSize(28, 28)
    self.remove_preset_btn.setIconSize(QSize(14, 14))

    self.move_up_btn = QPushButton()
    self.move_up_btn.setObjectName("MoveUpButton")
    self.move_up_btn.setIcon(qta.icon('fa5s.arrow-up', color='#e6e6e6'))
    self.move_up_btn.setToolTip(_("Переместить вверх", "Move up"))
    self.move_up_btn.setEnabled(False)
    self.move_up_btn.setFixedSize(28, 28)
    self.move_up_btn.setIconSize(QSize(14, 14))

    self.move_down_btn = QPushButton()
    self.move_down_btn.setObjectName("MoveDownButton")
    self.move_down_btn.setIcon(qta.icon('fa5s.arrow-down', color='#e6e6e6'))
    self.move_down_btn.setToolTip(_("Переместить вниз", "Move down"))
    self.move_down_btn.setEnabled(False)
    self.move_down_btn.setFixedSize(28, 28)
    self.move_down_btn.setIconSize(QSize(14, 14))

    buttons_layout.addWidget(self.add_preset_btn)
    buttons_layout.addWidget(self.remove_preset_btn)
    buttons_layout.addSpacing(6)
    buttons_layout.addWidget(self.move_up_btn)
    buttons_layout.addWidget(self.move_down_btn)
    buttons_layout.addStretch()
    presets_layout.addLayout(buttons_layout)
    main_layout.addWidget(custom_presets_frame)

    # Контейнер для настроек (скрыт по умолчанию)
    self.api_settings_container = QWidget()
    api_container_layout = QVBoxLayout(self.api_settings_container)
    api_container_layout.setContentsMargins(0, 10, 0, 0)
    api_container_layout.setSpacing(5)
    
    # 3. Название пресета и экспорт
    provider_info_layout = QHBoxLayout()
    self.provider_label = QLabel("")
    self.provider_label.setStyleSheet("font-weight: bold; font-size: 12px;")
    provider_info_layout.addWidget(self.provider_label)
    provider_info_layout.addStretch()
    
    self.export_button = QPushButton(_("Экспорт", "Export"))
    self.export_button.setIcon(qta.icon('fa5s.file-export', color='#3498db'))
    self.export_button.setMaximumWidth(100)
    provider_info_layout.addWidget(self.export_button)
    
    api_container_layout.addLayout(provider_info_layout)
    
    # 4. Комбобокс шаблона
    template_layout = QHBoxLayout()
    template_label = QLabel(_("Шаблон:", "Template:"))
    self.template_combo = QComboBox()
    self.template_combo.setMinimumWidth(200)
    template_layout.addWidget(template_label)
    template_layout.addWidget(self.template_combo)
    template_layout.addStretch()
    api_container_layout.addLayout(template_layout)
    api_container_layout.addSpacing(10)
    
    # Конфигурация полей
    from ui.gui_templates import create_settings_direct
    config = [        
        {'label': _('Ссылка API', 'API URL'),
         'key': 'NM_API_URL', 'type': 'entry',
         'widget_name': 'api_url_entry'},
        
        {'label': _('Модель', 'Model'),
         'key': 'NM_API_MODEL', 'type': 'entry',
         'widget_name': 'api_model_entry'},
        
        {'label': _('API Ключ', 'API Key'),
         'key': 'NM_API_KEY', 'type': 'entry',
         'widget_name': 'api_key_entry',
         'hide': True},
        
        {'label': _('Модель Gemini', 'Gemini Model'),
         'key': 'GEMINI_CASE_UI', 'type': 'checkbutton',
         'widget_name': 'gemini_case_checkbox',
         'tooltip': _("Формат сообщений gemini отличается от других",
                      "Gemini message format differs from others")},
        
        {'label': _('Резервные ключи', 'Reserve keys'),
         'key': 'NM_API_KEY_RES', 'type': 'textarea',
         'hide': bool(self.settings.get("HIDE_PRIVATE")),
         'widget_name': 'nm_api_key_res_label'},
        
        {'label': _('Версия g4f', 'g4f version'),
         'key': 'G4F_VERSION', 'type': 'entry',
         'default': '0.4.7.7',
         'widget_name': 'g4f_version_entry',
         'tooltip': _('Версия g4f для установки', 'g4f version to install')},
        
        {'label': _('Обновить g4f', 'Update g4f'),
         'type': 'button',
         'command': self.trigger_g4f_reinstall_schedule,
         'widget_name': 'g4f_update_button',
         'icon': qta.icon('fa5s.download', color='#3498db')},
    ]
    create_settings_direct(self, api_container_layout, config)
    
    # Получаем виджеты
    self.api_url_entry = getattr(self, 'api_url_entry')
    self.api_model_entry = getattr(self, 'api_model_entry')
    self.api_key_entry = getattr(self, 'api_key_entry')
    self.gemini_case_checkbox = getattr(self, 'gemini_case_checkbox', None)
    self.g4f_version_entry = getattr(self, 'g4f_version_entry', None)
    
    # Help labels
    self.url_help_label = QLabel()
    self.url_help_label.setOpenExternalLinks(True)
    self.url_help_label.setObjectName("LinkLabel")
    
    self.model_help_label = QLabel()
    self.model_help_label.setOpenExternalLinks(True)
    self.model_help_label.setObjectName("LinkLabel")
    
    self.key_help_label = QLabel()
    self.key_help_label.setOpenExternalLinks(True)
    self.model_help_label.setObjectName("LinkLabel")
    
    def _reorganize_frame_layout(frame, help_label):
        if not hasattr(frame, 'layout') or not frame.layout():
            return
        old_layout = frame.layout()
        items = []
        while old_layout.count():
            item = old_layout.takeAt(0)
            if item.widget():
                items.append(item.widget())
        new_layout = QVBoxLayout()
        new_layout.setContentsMargins(0, 0, 0, 0)
        new_layout.setSpacing(2)
        new_layout.addWidget(help_label)
        horizontal_layout = QHBoxLayout()
        horizontal_layout.setContentsMargins(0, 0, 0, 0)
        for widget in items:
            horizontal_layout.addWidget(widget)
        new_layout.addLayout(horizontal_layout)
        QWidget().setLayout(old_layout)
        frame.setLayout(new_layout)

    if hasattr(self, 'api_url_entry_frame'):
        _reorganize_frame_layout(self.api_url_entry_frame, self.url_help_label)
    if hasattr(self, 'api_model_entry_frame'):
        _reorganize_frame_layout(self.api_model_entry_frame, self.model_help_label)
    if hasattr(self, 'api_key_entry_frame'):
        _reorganize_frame_layout(self.api_key_entry_frame, self.key_help_label)
    
    self.api_key_entry.setEchoMode(QLineEdit.EchoMode.Password)
    self.key_visibility_button = QToolButton()
    self.key_visibility_button.setIcon(qta.icon('fa5s.eye'))
    if hasattr(self, 'api_key_entry_frame'):
        key_layout = self.api_key_entry_frame.layout()
        if key_layout and key_layout.count() > 1:
            horizontal_layout = key_layout.itemAt(1).layout()
            if horizontal_layout:
                horizontal_layout.addWidget(self.key_visibility_button)
    
    # Кнопки управления
    self.cancel_button = QPushButton(_("Отменить", "Cancel"))
    self.cancel_button.setObjectName("CancelButton")
    self.cancel_button.setIcon(qta.icon('fa5s.undo', color='#ffffff'))
    self.cancel_button.setVisible(False)
    

    self.save_preset_button = QPushButton(_("Сохранить", "Save"))
    self.save_preset_button.setObjectName("SecondaryButton")
    self.save_preset_button.setIcon(qta.icon('fa5s.save', color='#ffffff'))
    self.save_preset_button.setVisible(False)

    # Кнопка теста подключения
    self.test_button = QPushButton(_("Тест подключения", "Test connection"))
    self.test_button.setIcon(qta.icon('fa5s.satellite', color='#3498db'))

    buttons_layout = QHBoxLayout()
    buttons_layout.setSpacing(10)
    buttons_layout.addWidget(self.cancel_button, 1)
    buttons_layout.addWidget(self.save_preset_button, 1)

    api_container_layout.addWidget(self.test_button)
    api_container_layout.addLayout(buttons_layout)
    api_container_layout.addStretch()
    
    main_layout.addWidget(self.api_settings_container)
    self.api_settings_container.setVisible(False)
    main_layout.addStretch()

    # Добавляем корневой контейнер в переданный layout
    parent_layout.addWidget(main_container)
    
    # Completer для модели
    self.api_model_completer = QCompleter()
    self.api_model_list_model = QStringListModel()
    self.api_model_completer.setModel(self.api_model_list_model)
    self.api_model_completer.setCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)
    # Включаем режим всплывающего списка
    self.api_model_completer.setCompletionMode(QCompleter.CompletionMode.PopupCompletion)
    self.api_model_completer.setFilterMode(Qt.MatchFlag.MatchContains)
    self.api_model_entry.setCompleter(self.api_model_completer)
    
    completer = self.api_model_completer
    
    # Создаём свою функцию для обработки клика мышью
    def show_completer_on_click(event):
        # 1. Сначала вызываем стандартную обработку клика от QLineEdit
        from PyQt6.QtWidgets import QLineEdit
        QLineEdit.mousePressEvent(self.api_model_entry, event)
        
        # 2. Если поле ввода пустое - принудительно показываем ВСЕ варианты
        if self.api_model_entry.text() == "":
            # Убираем любой фильтр (устанавливаем пустой префикс)
            completer.setCompletionPrefix("")
            # Команда для показа всплывающего окна со всеми вариантами
            completer.complete()
    
    # Подменяем стандартный обработчик клика на нашу функцию
    self.api_model_entry.mousePressEvent = show_completer_on_click
    
    # Делегат для шаблонов
    self.provider_delegate = ProviderDelegate(self.template_combo)
    self.template_combo.view().setItemDelegate(self.provider_delegate)