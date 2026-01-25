from PyQt6.QtWidgets import (QWidget, QHBoxLayout, QVBoxLayout, QLabel, QLineEdit, QComboBox, 
                             QCheckBox, QPushButton, QTextEdit, QSizePolicy, QFrame)
from PyQt6.QtCore import Qt

from main_logger import logger
from managers.settings_manager import CollapsibleSection, InnerCollapsibleSection
from utils import getTranslationVariant as _

def create_settings_section(gui, parent_layout, title, cfg_list, *, icon_name=None):
    root = CollapsibleSection(title, gui, icon_name=icon_name)
    parent_layout.addWidget(root)
    current_sub = None

    for cfg in cfg_list:
        t = cfg.get('type')

        if t == 'subsection':
            current_sub = InnerCollapsibleSection(cfg.get('label', ''), gui)
            root.add_widget(current_sub)
            continue

        if t == 'end':
            current_sub = None
            continue

        if t == 'text':
            lbl = QLabel(cfg['label'])
            lbl.setObjectName('SeparatorLabel')
            (current_sub or root).add_widget(lbl)
            continue

        parent = (current_sub or root).content

        if t == 'button_group':
            w = create_button_group(gui, parent, cfg.get('buttons', []))
        else:
            w = create_setting_widget(
                gui=gui, parent=parent, label=cfg.get('label'),
                setting_key=cfg.get('key', ''), widget_type=t,
                options=cfg.get('options'), default=cfg.get('default', ''),
                default_checkbutton=cfg.get('default_checkbutton', False),
                validation=cfg.get('validation'), tooltip=cfg.get('tooltip'),
                hide=cfg.get('hide', False), command=cfg.get('command'),
                widget_name=cfg.get('widget_name', cfg.get('key')),
                depends_on=cfg.get('depends_on'),
                depends_on_value=cfg.get('depends_on_value',None),
                hide_when_disabled=cfg.get('hide_when_disabled', False),
                toggle_key=cfg.get('toggle_key'),
                toggle_default=cfg.get('toggle_default'),
            )
        if w:
            (current_sub or root).add_widget(w)

    return root

def create_settings_direct(gui, parent_layout, cfg_list, title=None):
    # Если передан заголовок, создаём его с разделителем
    if title:
        # Создаём контейнер для заголовка
        header_widget = QWidget()
        header_layout = QVBoxLayout(header_widget)
        header_layout.setContentsMargins(0, 0, 0, 10)
        header_layout.setSpacing(5)
        
        # Создаём заголовок
        title_label = QLabel(title)
        title_label.setObjectName('SectionTitle')
        title_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        title_label.setStyleSheet('''
            QLabel#SectionTitle {
                font-size: 14px;
                font-weight: bold;
                color: #ffffff;
                padding: 5px 0;
            }
        ''')
        header_layout.addWidget(title_label)
        
        # Создаём разделитель
        separator = QFrame()
        separator.setFrameShape(QFrame.Shape.HLine)
        separator.setFrameShadow(QFrame.Shadow.Sunken)
        separator.setStyleSheet('''
            QFrame {
                background-color: #4a4a4a;
                max-height: 2px;
                margin: 0 10px;
            }
        ''')
        header_layout.addWidget(separator)
        
        parent_layout.addWidget(header_widget)
    
    current_sub = None
    
    # Получаем родительский виджет для создания дочерних виджетов
    parent_widget = parent_layout.parent() if hasattr(parent_layout, 'parent') else None
    
    for cfg in cfg_list:
        t = cfg.get('type')

        if t == 'subsection':
            current_sub = InnerCollapsibleSection(cfg.get('label', ''), parent_widget)
            parent_layout.addWidget(current_sub)
            continue

        if t == 'end':
            current_sub = None
            continue

        if t == 'text':
            lbl = QLabel(cfg['label'], parent_widget)
            lbl.setObjectName('SeparatorLabel')
            if current_sub:
                current_sub.add_widget(lbl)
            else:
                parent_layout.addWidget(lbl)
            continue

        # Определяем родителя для виджета
        if current_sub:
            widget_parent = current_sub.content
        else:
            widget_parent = parent_widget

        if t == 'button_group':
            w = create_button_group(gui, widget_parent, cfg.get('buttons', []))
        else:
            w = create_setting_widget(
                gui=gui, parent=widget_parent, label=cfg.get('label'),
                setting_key=cfg.get('key', ''), widget_type=t,
                options=cfg.get('options'), default=cfg.get('default', ''),
                default_checkbutton=cfg.get('default_checkbutton', False),
                validation=cfg.get('validation'), tooltip=cfg.get('tooltip'),
                hide=cfg.get('hide', False), command=cfg.get('command'),
                widget_name=cfg.get('widget_name', cfg.get('key')),
                depends_on=cfg.get('depends_on'),
                depends_on_value=cfg.get('depends_on_value',None),
                hide_when_disabled=cfg.get('hide_when_disabled', False),
                toggle_key=cfg.get('toggle_key'),
                toggle_default=cfg.get('toggle_default'),
            )
        
        if w:
            if current_sub:
                current_sub.add_widget(w)
            else:
                parent_layout.addWidget(w)

def create_section_header(parent_layout, title):
    """Создаёт заголовок секции с разделителем"""
    header_widget = QWidget()
    header_layout = QVBoxLayout(header_widget)
    header_layout.setContentsMargins(0, 0, 0, 10)
    header_layout.setSpacing(5)
    
    title_label = QLabel(title)
    title_label.setObjectName('SectionTitle')
    title_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
    title_label.setStyleSheet('''
        QLabel#SectionTitle {
            font-size: 14px;
            font-weight: bold;
            color: #ffffff;
            padding: 5px 0;
        }
    ''')
    header_layout.addWidget(title_label)
    
    separator = QFrame()
    separator.setFrameShape(QFrame.Shape.HLine)
    separator.setFrameShadow(QFrame.Shadow.Sunken)
    separator.setStyleSheet('''
        QFrame {
            background-color: #4a4a4a;
            max-height: 2px;
            margin: 0 10px;
        }
    ''')
    header_layout.addWidget(separator)
    
    parent_layout.addWidget(header_widget)

def create_button_group(gui, parent, buttons_config):
    frame = QWidget(parent)
    layout = QHBoxLayout(frame)
    layout.setContentsMargins(0, 2, 0, 2)
    layout.setSpacing(10)
    
    for btn_config in buttons_config:
        button = QPushButton(btn_config['label'])
        if 'command' in btn_config:
            button.clicked.connect(btn_config['command'])
        layout.addWidget(button)
        
    return frame


def create_setting_widget(
        gui,
        parent,
        label,
        *,
        setting_key: str = '',
        widget_type: str = 'entry',
        options=None,
        default='',
        default_checkbutton=False,
        validation=None,
        tooltip=None,
        hide=False,
        command=None,
        widget_name=None,
        depends_on: str | None = None,
        depends_on_value: str | None = None,
        hide_when_disabled: bool = False,
        toggle_key: str | None = None,
        toggle_default: bool | None = None,
        **kwargs
):
    if setting_key and gui.settings.get(setting_key) is None:
        init_val = default_checkbutton if widget_type == 'checkbutton' else default
        gui.settings.set(setting_key, init_val)

    if toggle_key and gui.settings.get(toggle_key) is None:
        gui.settings.set(toggle_key,
                         toggle_default if toggle_default is not None else True)
        
    if widget_type in ('textarea', 'textedit'):
        frame = QWidget(parent)
        vlay = QVBoxLayout(frame)
        vlay.setContentsMargins(0, 2, 0, 2)
        vlay.setSpacing(4)

        lbl = QLabel(label)
        lbl.setWordWrap(True)
        vlay.addWidget(lbl)

        widget = QTextEdit()
        widget.setPlainText(str(gui.settings.get(setting_key, default)))
        widget.setMinimumHeight(50)
        widget.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)

        vlay.addWidget(widget)

        widget.textChanged.connect(
            lambda w=widget: gui._save_setting(setting_key, w.toPlainText())
        )

        if widget_name:
            setattr(gui, widget_name, widget)
            setattr(gui, f"{widget_name}_frame", frame)

        return frame

    frame = QWidget(parent)
    layout = QHBoxLayout(frame)
    layout.setContentsMargins(0, 2, 0, 2)
    layout.setSpacing(10)

    lbl = QLabel(label)
    lbl.setMinimumWidth(140)
    lbl.setMaximumWidth(140)
    lbl.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Preferred)
    lbl.setWordWrap(True)

    widget = None
    toggle_chk = None

    if widget_type == 'entry' and toggle_key:
        toggle_chk = QCheckBox()
        toggle_chk.setChecked(bool(gui.settings.get(toggle_key, True)))

        def _toggle_slot(state):
            enabled = state == Qt.CheckState.Checked.value
            gui._save_setting(toggle_key, enabled)
            if widget:
                widget.setEnabled(enabled)
            lbl.setEnabled(enabled)

        toggle_chk.stateChanged.connect(_toggle_slot)

    if widget_type == 'checkbutton':
        widget = QCheckBox()
        widget.setChecked(bool(gui.settings.get(setting_key, default_checkbutton)))

        def _save_check(state):
            val = state == Qt.CheckState.Checked.value
            gui._save_setting(setting_key, val)
            if command:
                command(val)

        widget.stateChanged.connect(_save_check)

        layout.addWidget(lbl)
        layout.addWidget(widget, 0, Qt.AlignmentFlag.AlignLeft)
        layout.addStretch(1)

    elif widget_type == 'entry':
        widget = QLineEdit(str(gui.settings.get(setting_key, default)))
        widget.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        if hide:
            widget.setEchoMode(QLineEdit.EchoMode.Password)

        def _save_entry():
            if validation and not validation(widget.text()):
                widget.setText(str(gui.settings.get(setting_key, default)))
                return
            if not (hide and widget.text() == ''):
                gui._save_setting(setting_key, widget.text())
            if command:
                command(widget.text())

        widget.editingFinished.connect(_save_entry)

        layout.addWidget(lbl)
        if toggle_chk:
            layout.addWidget(toggle_chk, 0, Qt.AlignmentFlag.AlignLeft)
        layout.addWidget(widget, 1)

    elif widget_type == 'combobox':
        widget = QComboBox()
        widget.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        if options:
            widget.addItems([str(o) for o in options])
        widget.setCurrentText(str(gui.settings.get(setting_key, default)))

        def _save_combo(text):
            gui._save_setting(setting_key, text)
            if command:
                command(text)

        widget.currentTextChanged.connect(_save_combo)

        layout.addWidget(lbl)
        if toggle_chk:
            layout.addWidget(toggle_chk, 0, Qt.AlignmentFlag.AlignLeft)
        layout.addWidget(widget, 1)

    elif widget_type == 'button':
        widget = QPushButton(label)
        if command:
            widget.clicked.connect(command)
        button_layout = QHBoxLayout()
        button_layout.setContentsMargins(0, 0, 0, 0)
        button_layout.addStretch()
        button_layout.addWidget(widget)
        button_layout.addStretch()
        layout.addLayout(button_layout)

    elif widget_type == 'text':
        widget = QLabel(label)
        widget.setObjectName("SeparatorLabel")
        widget.setWordWrap(True)
        layout.addWidget(widget)

    if tooltip and widget:
        widget.setToolTip(tooltip)

    if widget_name and widget is not None:
        setattr(gui, widget_name, widget)
        setattr(gui, f"{widget_name}_frame", frame)

    if depends_on and widget:
        controller = getattr(gui, depends_on, None)

        if not controller:
            logger.warning(f"[depends_on] controller '{depends_on}' not found for '{setting_key}'")
        else:
            def _dep_sync(_=None):
                active = True
                if isinstance(controller, QCheckBox):
                    active = controller.isChecked()
                elif isinstance(controller, QComboBox):
                    if depends_on_value is not None:
                        if isinstance(depends_on_value, (list, tuple, set)):
                            active = controller.currentText() in depends_on_value
                        else:
                            active = (controller.currentText() == depends_on_value)
                    else:
                        active = bool(controller.currentText())
                elif hasattr(controller, "currentText"):
                    active = bool(controller.currentText())

                if hide_when_disabled:
                    frame.setVisible(active)
                else:
                    widget.setEnabled(active)
                    lbl.setEnabled(active)

            _dep_sync()

            if isinstance(controller, QCheckBox):
                controller.stateChanged.connect(_dep_sync)
            elif hasattr(controller, "currentTextChanged"):
                controller.currentTextChanged.connect(_dep_sync)

    if toggle_chk and widget_type == 'entry':
        enabled = toggle_chk.isChecked()
        widget.setEnabled(enabled)
        lbl.setEnabled(enabled)

    return frame


