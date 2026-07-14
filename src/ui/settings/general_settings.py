from ui.gui_templates import create_settings_section, create_section_header
from ui.settings.settings_access import get_setting, settings_store
from utils import getTranslationVariant as _


def _on_section_toggled(gui, category=None, value=None):
    """Re-apply sidebar/tab visibility whenever a section checkbox flips."""
    try:
        from ui.widgets.settings_panel import apply_section_visibility, set_section_enabled
        if category is not None:
            set_section_enabled(str(category), bool(value), settings_store(gui))
        apply_section_visibility(gui)
    except Exception:
        pass


def _on_language_changed(gui, value=None):
    """Смена языка требует перезапуска — предлагаем его сразу.

    Значение уже сохранено комбобоксом до вызова command, поэтому здесь только
    спрашиваем и при согласии перезапускаем приложение.
    """
    try:
        from ui.language_restart import prompt_language_restart

        parent = gui if hasattr(gui, "window") else gui
        prompt_language_restart(parent)
    except Exception:
        pass


def _on_sandbox_panel_toggled(gui, key=None, value=None):
    """Re-apply the Sandbox inspector panel visibility when a checkbox flips."""
    try:
        from ui.widgets.sandbox_panels import apply_sandbox_panel_visibility, set_panel_enabled
        if key is not None:
            set_panel_enabled(str(key), bool(value), settings_store(gui))
        apply_sandbox_panel_visibility(gui)
    except Exception:
        pass


def _build_sandbox_panels_config(gui):
    """Build the Sandbox-panel toggle list dynamically from the central
    sandbox_panels registry — same pattern as the section-visibility block,
    but governs the right-hand inspector panels in the Sandbox. All ON by
    default."""
    from ui.widgets.sandbox_panels import (
        SANDBOX_PANEL_DEFAULTS,
        SANDBOX_PANEL_LABELS,
        TOGGLEABLE_SANDBOX_PANELS,
        _panel_key,
    )

    items = [
        {
            'label': _('Показывайте только нужные панели в правой части Песочницы.',
                       'Show only the panels you need in the Sandbox inspector.'),
            'type': 'text',
        },
    ]
    for key in TOGGLEABLE_SANDBOX_PANELS:
        label_pair = SANDBOX_PANEL_LABELS.get(key, (key.capitalize(), key.capitalize()))
        items.append({
            'label': _(label_pair[0], label_pair[1]),
            'key': _panel_key(key),
            'type': 'checkbutton',
            'default_checkbutton': SANDBOX_PANEL_DEFAULTS[key],
            'command': lambda value, _gui=gui, _key=key: _on_sandbox_panel_toggled(_gui, _key, value),
        })
    return items


def _build_section_visibility_config(gui):
    """Build the section-toggle checkbox list dynamically from the central
    SECTION_DEFAULTS map so the checkboxes can never go out of sync with the
    settings tabs / sidebar. Replaces the old Basic/Advanced/Full dropdown."""
    from ui.widgets.settings_panel import (
        SECTION_DEFAULTS,
        SECTION_LABELS,
        TOGGLEABLE_SECTIONS,
        _section_key,
    )

    items = [
        {
            'label': _('Включите только те разделы, которыми пользуетесь — '
                       'остальные спрячутся из настроек и боковой панели.',
                       'Enable only the sections you use — the rest are hidden '
                       'from the settings and the sidebar.'),
            'type': 'text',
        },
    ]
    for cat in TOGGLEABLE_SECTIONS:
        label_pair = SECTION_LABELS.get(cat, (cat.capitalize(), cat.capitalize()))
        items.append({
            'label': _(label_pair[0], label_pair[1]),
            'key': _section_key(cat),
            'type': 'checkbutton',
            'default_checkbutton': SECTION_DEFAULTS[cat],
            'command': lambda value, _gui=gui, _cat=cat: _on_section_toggled(_gui, _cat, value),
        })
    return items


def setup_general_settings_controls(self, parent):
    create_section_header(parent, _("Основные настройки", "General Settings"))

    # ── Видимость разделов настроек ─────────────────────────────────────────
    # Replaces the old "Interface mode" Basic/Advanced/Full dropdown. Each
    # non-general category gets its own checkbox; toggling rebuilds the
    # settings tabs / sidebar visibility on the spot.
    create_settings_section(
        self, parent,
        _('Видимые разделы', 'Visible sections'),
        _build_section_visibility_config(self),
        icon_name='fa5s.sliders-h',
    )

    # ── Видимость панелей Песочницы ─────────────────────────────────────────
    # Same per-toggle pattern, but governs the right-hand inspector panels in
    # the Sandbox (e.g. context budget, last-request diagnostics). All on by
    # default; toggling updates the live Sandbox page on the spot.
    create_settings_section(
        self, parent,
        _('Панели песочницы', 'Sandbox panels'),
        _build_sandbox_panels_config(self),
        icon_name='fa5s.flask',
    )

    privacy_config = [
        {'label': _('Скрывать (приватные) данные', 'Hide (private) data'), 
         'key': 'HIDE_PRIVATE',
         'type': 'checkbutton', 
         'default_checkbutton': True},
    ]
    create_settings_section(
        self, 
        parent, 
        _("Приватность", "Privacy"), 
        privacy_config, 
        icon_name='fa5s.user-shield'
    )

    chat_settings_config = [
        {'label': _('Размер шрифта чата', 'Chat Font Size'), 'key': 'CHAT_FONT_SIZE', 'type': 'entry',
         'default': 12, 'validation': self.validate_positive_integer,
         'tooltip': _('Размер шрифта в окне чата.', 'Font size in the chat window.')},
        {'label': _('Макс. ширина пузыря', 'Max bubble width'), 'key': 'CHAT_MAX_BUBBLE_WIDTH', 'type': 'entry',
         'default': 600, 'validation': self.validate_non_negative_integer,
         'tooltip': _('Максимальная ширина пузыря сообщения в пикселях. 0 = без ограничения.',
                      'Max message bubble width in pixels. 0 = no limit.')},
        {'label': _('Показывать метки времени', 'Show Timestamps'), 'key': 'SHOW_CHAT_TIMESTAMPS',
         'type': 'checkbutton', 'default_checkbutton': True,
         'tooltip': _('Показывать метки времени рядом с сообщениями в чате.',
                      'Show timestamps next to messages in chat.')},
        {'label': _('Скрывать теги', 'Hide Tags'), 'key': 'HIDE_CHAT_TAGS',
         'type': 'checkbutton', 'default_checkbutton': True,
         'tooltip': _('Скрывать теги (<e>, <c>, <a>, [b], [i], [color]) в отображаемом тексте чата.',
                      'Hide tags (<e>, <c>, <a>, [b], [i], [color]) in the displayed chat text.')},

        {'label': _('Выводить мышление', 'Show thinking'), 'key': 'SHOW_THINK_IN_GUI',
         'type': 'checkbutton', 'default_checkbutton': False,
         'tooltip': _('Отображать блок «мышления» модели как отдельное сообщение. '
                      'Дублируется в Песочнице → Отладка.',
                      "Display the model's thinking block as a separate message. "
                      'Also available in Sandbox → Debug.')},

        {'label': _('Показывать системные сообщения', 'Show system messages'), 'key': 'SHOW_SYSTEM_MESSAGES',
         'type': 'checkbutton', 'default_checkbutton': False,
         'tooltip': _('Показывать системные/контекстные заметки (например «[Easel drawing]…») в чате. '
                      'По умолчанию скрыты. Дублируется в Песочнице → Отладка.',
                      'Show system/context notes (e.g. "[Easel drawing]…") in chat. '
                      'Hidden by default. Also available in Sandbox → Debug.')},

        {'label': _('Показывать статистику токенов/стоимости', 'Show token/cost stats'), 'key': 'SHOW_TOKEN_INFO',
         'type': 'checkbutton', 'default_checkbutton': False,
         'tooltip': _('Строка снизу чата с токенами, заполнением контекста, кешем и стоимостью. '
                      'По умолчанию выключена.',
                      'Bottom-of-chat line with tokens, context fill, cache and cost. '
                      'Off by default.')},
    ]

    create_settings_section(
        self, 
        parent,
        _("Настройки чата", "Chat Settings"),
        chat_settings_config,
        icon_name='fa5s.comments'
    )

    # ── Профиль памяти ──────────────────────────────────────────────────────
    from ui.settings.memory_profile import apply_memory_profile, detect_memory_profile, KEY_TO_LABEL_RU, KEY_TO_LABEL_EN
    _lang = get_setting(self, 'LANGUAGE', 'RU')
    _key_map = KEY_TO_LABEL_EN if _lang == 'EN' else KEY_TO_LABEL_RU
    _detected_key = detect_memory_profile(self)
    _detected_label = _key_map.get(_detected_key, _('Сбалансированный', 'Balanced'))

    memory_profile_config = [
        {
            'label': _('Профиль памяти', 'Memory profile'),
            'key': 'MEMORY_PROFILE', 'type': 'combobox',
            'widget_name': 'MEMORY_PROFILE',
            'options': [
                _('Оптимизированный', 'Optimized'),
                _('Сбалансированный', 'Balanced'),
                _('Большой', 'Large'),
                _('Своё', 'Custom'),
            ],
            'default': _detected_label,
            'command': lambda v: apply_memory_profile(self, v),
            'tooltip': _(
                'Быстрый выбор объёма памяти: лимит сообщений, воспоминаний и результатов RAG.\n'
                'Оптимизированный: 20 / 20 / 20 — экономия токенов.\n'
                'Сбалансированный: 35 / 50 / 50 — дефолт.\n'
                'Большой: 50 / 75 / 75 — максимальная память, дороже и медленнее.',
                'Quick memory sizing: message limit / memory capacity / RAG results.\n'
                'Optimized: 20 / 20 / 20 — token-saving.\n'
                'Balanced: 35 / 50 / 50 — default.\n'
                'Large: 50 / 75 / 75 — max memory, more tokens, slower.'),
        },
    ]
    create_settings_section(
        self, parent,
        _('Память', 'Memory'),
        memory_profile_config,
        icon_name='fa5s.brain',
    )
    # синхронизировать combobox с реальными значениями
    try:
        from ui.settings.memory_profile import sync_profile_label
        sync_profile_label(self)
    except Exception:
        pass

    # Выбор языка вынесен в отдельную вкладку настроек («Язык» / language_settings).
