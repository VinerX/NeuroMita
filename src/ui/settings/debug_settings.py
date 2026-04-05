from PyQt6.QtWidgets import (
    QComboBox, QCheckBox, QHBoxLayout, QLabel,
    QPlainTextEdit, QPushButton,
)
from utils import getTranslationVariant as _


def setup_debug_panel_controls(view, parent_layout):
    """Build all interactive controls for the Debug panel.

    Creates widgets and stores the ones referenced by view's handlers as
    attributes on *view* (e.g. view._debug_system_input).

    Args:
        view: MainView instance — used to read/write settings and to attach
              widget references needed by handler methods.
        parent_layout: QVBoxLayout of the debug panel.
    """

    # ── Structured output display ────────────────────────────────────────────
    struct_label = QLabel(_('Structured output (дебаг)', 'Structured output (debug)'))
    struct_label.setObjectName('SeparatorLabel')
    parent_layout.addWidget(struct_label)

    _struct_options = [_('Выкл', 'Off'), _('Кратко', 'Brief'), 'JSON']
    struct_combo = QComboBox()
    struct_combo.addItems(_struct_options)
    _cur = view._get_setting("SHOW_STRUCTURED_IN_GUI", _('Выкл', 'Off'))
    _idx = struct_combo.findText(str(_cur))
    if _idx >= 0:
        struct_combo.setCurrentIndex(_idx)
    struct_combo.setToolTip(
        _('Выкл — не показывать; Кратко — сегменты с командами; JSON — сырой ответ.',
          'Off — hidden; Brief — segments with commands; JSON — raw response.')
    )
    struct_combo.currentTextChanged.connect(
        lambda text: view._save_setting("SHOW_STRUCTURED_IN_GUI", text)
    )
    combo_row = QHBoxLayout()
    combo_row.addWidget(struct_combo)
    combo_row.addStretch()
    parent_layout.addLayout(combo_row)

    struct_expanded_cb = QCheckBox(_('Развёрнуто по умолчанию', 'Expanded by default'))
    struct_expanded_cb.setToolTip(
        _('Если включено — блок с данными открыт сразу, иначе свёрнут.',
          'If enabled — the data block is open immediately, otherwise collapsed.')
    )
    struct_expanded_cb.setChecked(bool(view._get_setting("STRUCTURED_EXPANDED_DEFAULT", False)))
    struct_expanded_cb.toggled.connect(
        lambda checked: view._save_setting("STRUCTURED_EXPANDED_DEFAULT", checked)
    )
    parent_layout.addWidget(struct_expanded_cb)

    # ── System message insertion ─────────────────────────────────────────────
    sys_label = QLabel(_('Вставить system-сообщение в историю', 'Insert system message into history'))
    sys_label.setObjectName('SeparatorLabel')
    parent_layout.addWidget(sys_label)

    view._debug_system_input = QPlainTextEdit()
    view._debug_system_input.setPlaceholderText(_('Текст system-сообщения...', 'System message text...'))
    view._debug_system_input.setFixedHeight(70)
    parent_layout.addWidget(view._debug_system_input)

    view._debug_as_user_cb = QCheckBox(
        _('Как пользователь [Системное]: (видно Gemini)', 'As user [System]: (visible to Gemini)')
    )
    view._debug_as_user_cb.setToolTip(
        _('Сохранить как role=user с префиксом [Системное]:, чтобы Gemini видел сообщение в контексте',
          'Save as role=user with [System]: prefix so Gemini sees it in context')
    )
    view._debug_as_user_cb.setChecked(bool(view._get_setting("DEBUG_INSERT_AS_USER", False)))
    view._debug_as_user_cb.toggled.connect(
        lambda checked: view._save_setting("DEBUG_INSERT_AS_USER", checked)
    )
    parent_layout.addWidget(view._debug_as_user_cb)

    sys_btn = QPushButton(_('Отправить системное', 'Send as system'))
    sys_btn.clicked.connect(view._on_debug_insert_system_message)
    parent_layout.addWidget(sys_btn)

    # ── Snapshot save / load ─────────────────────────────────────────────────
    snap_label = QLabel(_('Snapshot истории', 'History snapshot'))
    snap_label.setObjectName('SeparatorLabel')
    parent_layout.addWidget(snap_label)

    snap_row = QHBoxLayout()
    save_snap_btn = QPushButton(_('Сохранить snapshot', 'Save snapshot'))
    save_snap_btn.clicked.connect(view._on_debug_save_snapshot)
    load_snap_btn = QPushButton(_('Загрузить snapshot', 'Load snapshot'))
    load_snap_btn.clicked.connect(view._on_debug_load_snapshot)
    snap_row.addWidget(save_snap_btn)
    snap_row.addWidget(load_snap_btn)
    parent_layout.addLayout(snap_row)
