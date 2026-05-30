from ui.gui_templates import create_settings_section, create_section_header
from utils import getTranslationVariant as _


def _on_section_toggled(gui, category=None, value=None):
    """Re-apply sidebar/tab visibility whenever a section checkbox flips."""
    try:
        from ui.widgets.settings_panel import apply_section_visibility, set_section_enabled
        if category is not None:
            set_section_enabled(str(category), bool(value))
        apply_section_visibility(gui)
    except Exception:
        pass


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
    from managers.settings_manager import SettingsManager as _SM

    _lang = _SM.get('LANGUAGE', 'RU')
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

    language_config = [
        {'label': 'Язык / Language', 'key': 'LANGUAGE', 'type': 'combobox',
         'options': ["RU", "EN"], 'default': "RU"},
        {'label': 'Перезапусти программу после смены!', 'type': 'text'},
        {'label': 'Restart program after change!', 'type': 'text'},
    ]

    create_settings_section(
        self, 
        parent,
        "Язык / Language",
        language_config,
        icon_name='fa5s.globe'
    )
