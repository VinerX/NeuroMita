from PyQt6.QtWidgets import (QWidget, QHBoxLayout, QVBoxLayout, QLabel, QLineEdit, QComboBox, 
                             QCheckBox, QPushButton, QTextEdit, QSizePolicy, QFrame)
from PyQt6.QtCore import QSignalBlocker, Qt

from main_logger import logger
from ui.widgets.settings_sections import CollapsibleSection, InnerCollapsibleSection
from ui.widgets.tr_combobox import TRQComboBox
from ui.settings.settings_access import get_setting, set_setting
from utils import getTranslationVariant as _
from localization.live import register_if_tr


class SettingsBodyWidget(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("SettingsBodyWidget")


def _bind_setting_value(gui, key: str, widget: QWidget, apply_value) -> None:
    if not key:
        return
    binding = getattr(gui, "settings_binding", None)
    if binding is None:
        return

    def _apply(value):
        blocker = QSignalBlocker(widget)
        try:
            apply_value(value)
        finally:
            del blocker

    binding.bind(key, widget, _apply)


def _bind_setting_two_way(
    gui,
    key: str,
    widget: QWidget,
    changed_signal,
    read_value,
    apply_value,
    *,
    default=None,
    transform=None,
    after_write=None,
) -> bool:
    if not key:
        return False
    binding = getattr(gui, "settings_binding", None)
    if binding is None or not hasattr(binding, "bind_two_way"):
        return False

    def _apply(value):
        blocker = QSignalBlocker(widget)
        try:
            apply_value(value)
        finally:
            del blocker

    binding.bind_two_way(
        key,
        widget,
        changed_signal,
        read_value,
        _apply,
        default=default,
        transform=transform,
        after_write=after_write,
    )
    return True


def create_settings_section(gui, parent_layout, title, cfg_list, *, icon_name=None):
    items = list(cfg_list or [])
    subtitle = None
    if items and items[0].get('type') == 'text':
        subtitle = items.pop(0).get('label', '')

    root = CollapsibleSection(title, gui, icon_name=icon_name, subtitle=subtitle)
    register_if_tr(root.title_label, title)
    if subtitle and getattr(root, "subtitle_label", None) is not None:
        register_if_tr(root.subtitle_label, subtitle)
    parent_layout.addWidget(root)
    current_sub = None

    for cfg in items:
        t = cfg.get('type')

        if t == 'subsection':
            current_sub = InnerCollapsibleSection(cfg.get('label', ''), gui)
            register_if_tr(current_sub.title_label, cfg.get('label', ''))
            root.add_widget(current_sub)
            continue

        if t == 'end':
            current_sub = None
            continue

        if t == 'text':
            lbl = QLabel(cfg['label'])
            lbl.setObjectName('SeparatorLabel')
            # Авто-перенос: вёрстка не должна зависеть от ручных \n в переводах
            # (в не-русских локалях их нет — иначе текст уезжает за край).
            lbl.setWordWrap(True)
            lbl.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
            register_if_tr(lbl, cfg['label'])
            (current_sub or root).add_widget(lbl)
            continue

        parent = (current_sub or root).content

        if t == 'button_group':
            w = create_button_group(gui, parent, cfg.get('buttons', []))
        elif t == 'widget':
            factory = cfg.get('factory')
            w = factory(gui) if callable(factory) else cfg.get('widget')
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
    if title:
        create_section_header(parent_layout, title)
    
    current_sub = None
    
    # Получаем родительский виджет для создания дочерних виджетов
    parent_widget = parent_layout.parent() if hasattr(parent_layout, 'parent') else None
    
    for cfg in cfg_list:
        t = cfg.get('type')

        if t == 'subsection':
            current_sub = InnerCollapsibleSection(cfg.get('label', ''), parent_widget)
            register_if_tr(current_sub.title_label, cfg.get('label', ''))
            parent_layout.addWidget(current_sub)
            continue

        if t == 'end':
            current_sub = None
            continue

        if t == 'text':
            lbl = QLabel(cfg['label'], parent_widget)
            lbl.setObjectName('SeparatorLabel')
            register_if_tr(lbl, cfg['label'])
            lbl.setWordWrap(True)
            lbl.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
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
    """Создаёт компактный заголовок внутренней группы."""
    header_widget = QWidget()
    header_widget.setObjectName("SettingsSubsectionHeader")
    header_layout = QVBoxLayout(header_widget)
    header_layout.setContentsMargins(0, 8, 0, 8)
    header_layout.setSpacing(6)

    title_label = QLabel(title)
    register_if_tr(title_label, title)
    title_label.setObjectName("SettingsSubsectionTitle")
    title_label.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
    header_layout.addWidget(title_label)

    separator = QFrame()
    separator.setObjectName("SettingsSubsectionLine")
    separator.setFixedHeight(1)
    header_layout.addWidget(separator)

    parent_layout.addWidget(header_widget)

def create_button_group(gui, parent, buttons_config):
    frame = QWidget(parent)
    frame.setObjectName('SettingRow')
    frame.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
    layout = QHBoxLayout(frame)
    layout.setContentsMargins(0, 2, 0, 2)
    layout.setSpacing(10)
    
    for btn_config in buttons_config:
        button = QPushButton(btn_config['label'])
        register_if_tr(button, btn_config['label'])
        if 'command' in btn_config:
            button.clicked.connect(btn_config['command'])
        if 'widget_name' in btn_config:
            setattr(gui, btn_config['widget_name'], button)
        layout.addWidget(button)
        
    return frame


def _apply_setting_row_disabled(frame: QWidget, disabled: bool) -> None:
    frame.setProperty("disabled", "true" if disabled else "false")
    style = frame.style()
    if style is not None:
        style.unpolish(frame)
        style.polish(frame)
    frame.update()


def _fmt_tooltip(text: str) -> str:
    if not text:
        return text
    escaped = (text.replace('&', '&amp;')
                   .replace('<', '&lt;')
                   .replace('>', '&gt;')
                   .replace('\n', '<br>'))
    return f'<p style="max-width:350px;">{escaped}</p>'


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
    if setting_key and get_setting(gui, setting_key) is None:
        init_val = default_checkbutton if widget_type == 'checkbutton' else default
        set_setting(gui, setting_key, init_val)

    if toggle_key and get_setting(gui, toggle_key) is None:
        set_setting(
            gui,
            toggle_key,
            toggle_default if toggle_default is not None else True,
        )
        
    if widget_type in ('textarea', 'textedit'):
        frame = QWidget(parent)
        frame.setObjectName('SettingRow')
        frame.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        vlay = QVBoxLayout(frame)
        vlay.setContentsMargins(0, 2, 0, 2)
        vlay.setSpacing(4)

        lbl = QLabel(label)
        register_if_tr(lbl, label)
        lbl.setWordWrap(True)
        vlay.addWidget(lbl)

        widget = QTextEdit()
        widget.setPlainText(str(get_setting(gui, setting_key, default)))
        widget.setMinimumHeight(50)
        widget.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)

        vlay.addWidget(widget)

        if not _bind_setting_two_way(
            gui,
            setting_key,
            widget,
            widget.textChanged,
            widget.toPlainText,
            lambda value: widget.setPlainText(str(value if value is not None else default)),
            default=default,
        ):
            widget.textChanged.connect(
                lambda w=widget: gui._save_setting(setting_key, w.toPlainText())
            )
            _bind_setting_value(
                gui,
                setting_key,
                widget,
                lambda value: widget.setPlainText(str(value if value is not None else default)),
            )

        if tooltip:
            _tt = _fmt_tooltip(tooltip)
            lbl.setToolTip(_tt)
            widget.setToolTip(_tt)
            register_if_tr(lbl, tooltip, "setToolTip", _fmt_tooltip)
            register_if_tr(widget, tooltip, "setToolTip", _fmt_tooltip)

        if widget_name:
            setattr(gui, widget_name, widget)
            setattr(gui, f"{widget_name}_frame", frame)

        return frame

    frame = QWidget(parent)
    frame.setObjectName('SettingRow')
    frame.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
    layout = QHBoxLayout(frame)
    layout.setContentsMargins(0, 2, 0, 2)
    layout.setSpacing(10)
    frame.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed)

    lbl = QLabel(label)
    register_if_tr(lbl, label)
    lbl.setMinimumWidth(140)
    lbl.setMaximumWidth(140)
    lbl.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Preferred)
    lbl.setWordWrap(True)

    widget = None
    toggle_chk = None

    if widget_type == 'entry' and toggle_key:
        toggle_chk = QCheckBox()
        toggle_chk.setChecked(bool(get_setting(gui, toggle_key, True)))

        def _apply_toggle_enabled(enabled: bool):
            if widget:
                widget.setEnabled(bool(enabled))
            lbl.setEnabled(bool(enabled))
            _apply_setting_row_disabled(frame, not bool(enabled))

        def _toggle_slot(state):
            enabled = state == Qt.CheckState.Checked.value
            gui._save_setting(toggle_key, enabled)
            _apply_toggle_enabled(enabled)

        if not _bind_setting_two_way(
            gui,
            toggle_key,
            toggle_chk,
            toggle_chk.stateChanged,
            lambda: toggle_chk.isChecked(),
            lambda value: toggle_chk.setChecked(bool(value)),
            default=toggle_default if toggle_default is not None else True,
            after_write=_apply_toggle_enabled,
        ):
            toggle_chk.stateChanged.connect(_toggle_slot)
            _bind_setting_value(
                gui,
                toggle_key,
                toggle_chk,
                lambda value: toggle_chk.setChecked(bool(value)),
            )
        _apply_toggle_enabled(toggle_chk.isChecked())

    if widget_type == 'checkbutton':
        from ui.widgets.toggle_switch import ToggleSwitch

        widget = ToggleSwitch()
        widget.setChecked(bool(get_setting(gui, setting_key, default_checkbutton)))
        lbl.setMinimumWidth(0)
        lbl.setMaximumWidth(16777215)
        lbl.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)

        def _save_check(state):
            val = state == Qt.CheckState.Checked.value
            gui._save_setting(setting_key, val)
            if command:
                command(val)

        if not _bind_setting_two_way(
            gui,
            setting_key,
            widget,
            widget.stateChanged,
            widget.isChecked,
            lambda value: widget.setChecked(bool(value)),
            default=default_checkbutton,
            after_write=command,
        ):
            widget.stateChanged.connect(_save_check)
            _bind_setting_value(
                gui,
                setting_key,
                widget,
                lambda value: widget.setChecked(bool(value)),
            )

        title_col = QVBoxLayout()
        title_col.setContentsMargins(0, 0, 0, 0)
        title_col.setSpacing(2)
        title_col.addWidget(lbl)
        if tooltip:
            desc = QLabel(str(tooltip))
            register_if_tr(desc, tooltip)
            desc.setObjectName("SettingRowDescription")
            desc.setTextFormat(Qt.TextFormat.PlainText)
            desc.setWordWrap(True)
            title_col.addWidget(desc)

        layout.addLayout(title_col, 1)
        layout.addWidget(widget, 0, Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)

    elif widget_type == 'entry':
        widget = QLineEdit(str(get_setting(gui, setting_key, default)))
        widget.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        widget.setMinimumWidth(60)
        if hide:
            widget.setEchoMode(QLineEdit.EchoMode.Password)

        def _save_entry():
            if validation and not validation(widget.text()):
                widget.setText(str(get_setting(gui, setting_key, default)))
                return
            if not (hide and widget.text() == ''):
                gui._save_setting(setting_key, widget.text())
            if command:
                command(widget.text())

        widget.editingFinished.connect(_save_entry)
        _bind_setting_value(
            gui,
            setting_key,
            widget,
            lambda value: (
                None
                if widget.hasFocus()
                else widget.setText(str(value if value is not None else default))
            ),
        )

        layout.addWidget(lbl)
        if toggle_chk:
            layout.addWidget(toggle_chk, 0, Qt.AlignmentFlag.AlignLeft)
        layout.addWidget(widget, 1)

    elif widget_type == 'combobox':
        # TRQComboBox: значение пункта (itemData) стабильно, переводимые подписи
        # обновляются вживую. Переводимая опция (TrStr из _()) → канонический ключ
        # ru как значение; обычная строка/кортеж (display, value) → данные с
        # сохранённым значением. Работа с выбором — по значению, не по тексту.
        widget = TRQComboBox()
        widget.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        widget.setMinimumWidth(60)

        def _canon(x):
            ru = getattr(x, 'tr_ru', None)
            return ru if ru is not None else x

        widget.blockSignals(True)
        try:
            for o in (options or []):
                if isinstance(o, (tuple, list)) and len(o) == 2:
                    disp, val = o
                    ru = getattr(disp, 'tr_ru', None)
                    if ru is not None:
                        widget.add_tr_item(ru, getattr(disp, 'tr_en', ''), value=val)
                    else:
                        widget.add_data_item(str(disp), value=val)
                else:
                    ru = getattr(o, 'tr_ru', None)
                    if ru is not None:
                        widget.add_tr_item(ru, getattr(o, 'tr_en', ''))
                    else:
                        widget.add_data_item(str(o))
            # выбор: сохранённое значение → default → первый пункт (без ложного save).
            if not widget.set_current_value(_canon(get_setting(gui, setting_key, default))):
                if not widget.set_current_value(_canon(default)) and widget.count():
                    widget.setCurrentIndex(0)
        finally:
            widget.blockSignals(False)

        def _save_combo(*_a):
            val = widget.current_value()
            gui._save_setting(setting_key, val)
            if command:
                command(val)

        if not _bind_setting_two_way(
            gui,
            setting_key,
            widget,
            widget.currentIndexChanged,
            widget.current_value,
            lambda value: widget.set_current_value(_canon(value)),
            default=default,
            after_write=command,
        ):
            widget.currentIndexChanged.connect(_save_combo)
            _bind_setting_value(
                gui,
                setting_key,
                widget,
                lambda value: widget.set_current_value(_canon(value)),
            )

        layout.addWidget(lbl)
        if toggle_chk:
            layout.addWidget(toggle_chk, 0, Qt.AlignmentFlag.AlignLeft)
        layout.addWidget(widget, 1)

    elif widget_type == 'button':
        widget = QPushButton(label)
        register_if_tr(widget, label)
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
        register_if_tr(widget, label)
        widget.setObjectName("SeparatorLabel")
        widget.setWordWrap(True)
        layout.addWidget(widget)

    if tooltip:
        _tt = _fmt_tooltip(tooltip)
        if widget:
            widget.setToolTip(_tt)
            register_if_tr(widget, tooltip, "setToolTip", _fmt_tooltip)
        lbl.setToolTip(_tt)
        register_if_tr(lbl, tooltip, "setToolTip", _fmt_tooltip)

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
                    _apply_setting_row_disabled(frame, not active)

            _dep_sync()

            if isinstance(controller, QCheckBox):
                controller.stateChanged.connect(_dep_sync)
            elif hasattr(controller, "currentTextChanged"):
                controller.currentTextChanged.connect(_dep_sync)

    if toggle_chk and widget_type == 'entry':
        enabled = toggle_chk.isChecked()
        widget.setEnabled(enabled)
        lbl.setEnabled(enabled)
        _apply_setting_row_disabled(frame, not enabled)

    return frame


