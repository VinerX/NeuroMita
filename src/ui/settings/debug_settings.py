from PyQt6.QtWidgets import (
    QComboBox, QCheckBox, QHBoxLayout, QLabel,
    QPlainTextEdit, QPushButton, QVBoxLayout,
)
from utils import getTranslationVariant as _
from localization.live import register_if_tr, tr_set
from ui.widgets.tr_combobox import TRQComboBox


def setup_debug_panel_controls(
    parent_layout,
    *,
    settings,
    insert_system_message,
    save_snapshot,
    load_snapshot,
    view_context,
):
    """Build a passive debug panel from explicit settings and action ports."""

    def _get(key, default=None):
        getter = getattr(settings, "get", None)
        return getter(str(key), default) if callable(getter) else default

    def _set(key, value) -> None:
        setter = getattr(settings, "set", None)
        if callable(setter):
            setter(str(key), value)

    def _make_toggle(text: str, tooltip: str | None = None) -> QCheckBox:
        cb = QCheckBox(text)
        register_if_tr(cb, text)
        cb.setObjectName("SandboxCaptureToggle")
        if tooltip:
            cb.setToolTip(tooltip)
            register_if_tr(cb, tooltip, "setToolTip")
        return cb

    def _style_action_button(button: QPushButton) -> QPushButton:
        button.setObjectName("SandboxQuickAction")
        return button

    # ── Structured output display ────────────────────────────────────────────
    struct_label = tr_set(QLabel(), 'Structured output (дебаг)', 'Structured output (debug)')
    struct_label.setObjectName('SeparatorLabel')
    parent_layout.addWidget(struct_label)

    # Значения канонические ru ("Выкл"/"Кратко"/"JSON") — потребитель
    # (message_renderer) понимает и ru, и en варианты, подписи переводятся вживую.
    struct_combo = TRQComboBox()
    struct_combo.add_tr_item('Выкл', 'Off', value='Выкл')
    struct_combo.add_tr_item('Кратко', 'Brief', value='Кратко')
    struct_combo.add_data_item('JSON', value='JSON')
    struct_combo.set_current_value(_get("SHOW_STRUCTURED_IN_GUI", 'Выкл'))
    tr_set(struct_combo, 'Выкл — не показывать; Кратко — сегменты с командами; JSON — сырой ответ.',
          'Off — hidden; Brief — segments with commands; JSON — raw response.', "setToolTip")
    struct_combo.currentIndexChanged.connect(
        lambda _i: _set("SHOW_STRUCTURED_IN_GUI", struct_combo.current_value())
    )
    combo_row = QHBoxLayout()
    combo_row.addWidget(struct_combo)
    combo_row.addStretch()
    parent_layout.addLayout(combo_row)

    struct_expanded_cb = tr_set(QCheckBox(), 'Развёрнуто по умолчанию', 'Expanded by default')
    tr_set(struct_expanded_cb, 'Если включено — блок с данными открыт сразу, иначе свёрнут.',
          'If enabled — the data block is open immediately, otherwise collapsed.', "setToolTip")
    struct_expanded_cb.setObjectName("SandboxCaptureToggle")
    struct_expanded_cb.setChecked(bool(_get("STRUCTURED_EXPANDED_DEFAULT", False)))
    struct_expanded_cb.toggled.connect(
        lambda checked: _set("STRUCTURED_EXPANDED_DEFAULT", checked)
    )
    parent_layout.addWidget(struct_expanded_cb)

    sandbox_structured_limits_cb = tr_set(
        QCheckBox(),
        'Ограничивать structured output в sandbox',
        'Restrict structured output in sandbox',
    )
    tr_set(
        sandbox_structured_limits_cb,
        'Убирать emotions, animations и idle_animations без подключённой игры. '
        'Снимите галку для отладки и возврата этих полей. Поле commands не отключается.',
        'Remove emotions, animations and idle_animations when the game is disconnected. '
        'Uncheck for debugging and restore these fields. The commands field remains available.',
        "setToolTip",
    )
    sandbox_structured_limits_cb.setObjectName("SandboxCaptureToggle")
    sandbox_structured_limits_cb.setChecked(bool(_get(
        "REMOTE_ONLY_STRUCTURED_FIELDS_EXCLUSION_ENABLED", True
    )))
    sandbox_structured_limits_cb.toggled.connect(
        lambda checked: _set(
            "REMOTE_ONLY_STRUCTURED_FIELDS_EXCLUSION_ENABLED", checked
        )
    )
    parent_layout.addWidget(sandbox_structured_limits_cb)

    # ── System message insertion ─────────────────────────────────────────────
    sys_label = tr_set(QLabel(), 'Вставить system-сообщение в историю', 'Insert system message into history')
    sys_label.setObjectName('SeparatorLabel')
    parent_layout.addWidget(sys_label)

    system_input = QPlainTextEdit()
    tr_set(system_input, 'Текст system-сообщения...', 'System message text...', "setPlaceholderText")
    system_input.setFixedHeight(70)
    parent_layout.addWidget(system_input)

    as_user_cb = QCheckBox(
        _('Как пользователь [Системное]: (видно Gemini)', 'As user [System]: (visible to Gemini)')
    )
    tr_set(as_user_cb, 'Сохранить как role=user с префиксом [Системное]:, чтобы Gemini видел сообщение в контексте',
          'Save as role=user with [System]: prefix so Gemini sees it in context', "setToolTip")
    as_user_cb.setObjectName("SandboxCaptureToggle")
    as_user_cb.setChecked(bool(_get("DEBUG_INSERT_AS_USER", False)))
    as_user_cb.toggled.connect(
        lambda checked: _set("DEBUG_INSERT_AS_USER", checked)
    )
    parent_layout.addWidget(as_user_cb)

    sys_btn = tr_set(QPushButton(), 'Отправить системное', 'Send as system')
    sys_btn.setObjectName("SandboxQuickAction")
    def _submit_system_message() -> None:
        text = system_input.toPlainText().strip()
        if not text:
            return
        insert_system_message(text, as_user=as_user_cb.isChecked())
        system_input.clear()

    sys_btn.clicked.connect(_submit_system_message)
    parent_layout.addWidget(sys_btn)

    # ── Snapshot save / load ─────────────────────────────────────────────────
    snap_label = tr_set(QLabel(), 'Snapshot истории', 'History snapshot')
    snap_label.setObjectName('SeparatorLabel')
    parent_layout.addWidget(snap_label)

    snap_row = QVBoxLayout()
    snap_row.setContentsMargins(0, 0, 0, 0)
    snap_row.setSpacing(6)
    save_snap_btn = tr_set(QPushButton(), 'Сохранить snapshot', 'Save snapshot')
    save_snap_btn.setObjectName("SandboxQuickAction")
    save_snap_btn.clicked.connect(save_snapshot)
    load_snap_btn = tr_set(QPushButton(), 'Загрузить snapshot', 'Load snapshot')
    load_snap_btn.setObjectName("SandboxQuickAction")
    load_snap_btn.clicked.connect(load_snapshot)
    snap_row.addWidget(save_snap_btn)
    snap_row.addWidget(load_snap_btn)
    parent_layout.addLayout(snap_row)

    # ── Context viewer ───────────────────────────────────────────────────────────
    ctx_label = tr_set(QLabel(), 'Просмотр контекста запроса', 'Request context viewer')
    ctx_label.setObjectName('SeparatorLabel')
    parent_layout.addWidget(ctx_label)

    ctx_req_btn = tr_set(QPushButton(), 'Посмотреть последний запрос', 'View last request')
    tr_set(ctx_req_btn, 'Открыть просмотр контекста последнего запроса к нейросети (сообщения, системные промты, параметры)',
          'Open context viewer for the last request sent to the neural network', "setToolTip")
    ctx_req_btn.setObjectName("SandboxQuickAction")
    ctx_req_btn.clicked.connect(lambda: view_context("request"))

    ctx_resp_btn = tr_set(QPushButton(), 'Посмотреть последний ответ', 'View last response')
    tr_set(ctx_resp_btn, 'Открыть просмотр последнего ответа модели и usage-метрик, если они сохранены.',
          'Open the latest model response and usage metrics if they were saved.', "setToolTip")
    ctx_resp_btn.setObjectName("SandboxQuickAction")
    ctx_resp_btn.clicked.connect(lambda: view_context("response"))

    ctx_row = QVBoxLayout()
    ctx_row.setContentsMargins(0, 0, 0, 0)
    ctx_row.setSpacing(6)
    ctx_row.addWidget(ctx_req_btn)
    ctx_row.addWidget(ctx_resp_btn)
    parent_layout.addLayout(ctx_row)

    capture_cb = tr_set(QCheckBox(), 'Сохранять вход генерации', 'Capture generation input')
    tr_set(capture_cb, 'Сохранять вход события GENERATE_RESPONSE до сборки промпта: сырой payload, состояние перед BUILD_PROMPT и краткую сводку по изображениям.',
          'Save GENERATE_RESPONSE ingress before prompt build: raw payload, pre-BUILD_PROMPT state, and compact image summaries.', "setToolTip")
    capture_cb.setObjectName("SandboxCaptureToggle")
    capture_cb.setChecked(bool(_get("DEBUG_CAPTURE_GENERATION_INPUT_ENABLED", False)))
    capture_cb.toggled.connect(
        lambda checked: _set("DEBUG_CAPTURE_GENERATION_INPUT_ENABLED", checked)
    )
    parent_layout.addWidget(capture_cb)
