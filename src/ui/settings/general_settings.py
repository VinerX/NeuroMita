from ui.gui_templates import create_settings_section, create_section_header
from utils import getTranslationVariant as _


def _apply_interface_mode_cb(gui, value):
    try:
        from ui.widgets.settings_panel import apply_interface_mode
        apply_interface_mode(gui, value)
    except Exception:
        pass


def setup_general_settings_controls(self, parent):
    create_section_header(parent, _("Основные настройки", "General Settings"))

    # ── Режим отображения настроек ──────────────────────────────────────────
    interface_mode_config = [
        {
            'label': _('Режим интерфейса', 'Interface mode'),
            'key': 'INTERFACE_MODE', 'type': 'combobox',
            'options': [_('Базовый', 'Basic'), _('Продвинутый', 'Advanced'), _('Полный', 'Full')],
            'default': _('Базовый', 'Basic'),
            'command': lambda v: _apply_interface_mode_cb(self, v),
            'tooltip': _(
                'Базовый — только самое нужное.\n'
                'Продвинутый — добавляет озвучку, микрофон и связь с игрой.\n'
                'Полный — все разделы настроек.',
                'Basic — essentials only.\n'
                'Advanced — adds voice, mic and game connection.\n'
                'Full — all settings sections.'),
        },
    ]
    create_settings_section(
        self, parent,
        _('Режим отображения настроек', 'Settings UI mode'),
        interface_mode_config,
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
         'type': 'checkbutton', 'default_checkbutton': True},
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