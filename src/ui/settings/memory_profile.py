from ui.settings.settings_access import get_setting

# src/ui/settings/memory_profile.py
"""
Профили памяти — быстрый выбор объёма: лимит сообщений, воспоминаний и результатов RAG.
"""

PRESETS = {
    'optimized': (20, 20, 20),   # Оптимизированный — экономия токенов
    'balanced':  (35, 50, 50),   # Сбалансированный — дефолт
    'large':     (50, 75, 75),   # Большой — максимальная память
}

LABEL_TO_KEY = {
    'Оптимизированный': 'optimized', 'Optimized': 'optimized',
    'Сбалансированный': 'balanced',  'Balanced':  'balanced',
    'Большой':          'large',     'Large':     'large',
    'Своё':             'custom',    'Custom':    'custom',
}

KEY_TO_LABEL_RU = {
    'optimized': 'Оптимизированный',
    'balanced':  'Сбалансированный',
    'large':     'Большой',
    'custom':    'Своё',
}

KEY_TO_LABEL_EN = {
    'optimized': 'Optimized',
    'balanced':  'Balanced',
    'large':     'Large',
    'custom':    'Custom',
}


def apply_memory_profile(gui, label: str) -> None:
    """Применить пресет памяти по метке (ру/ен). При 'custom' ничего не делает."""
    key = LABEL_TO_KEY.get(label, 'custom')
    if key == 'custom':
        return
    msg, cap, rag = PRESETS[key]
    gui._save_setting('MODEL_MESSAGE_LIMIT', msg)
    gui._save_setting('MEMORY_CAPACITY', cap)
    gui._save_setting('RAG_MAX_RESULTS', rag)
    # обновить QLineEdit-виджеты напрямую (QLineEdit.setText не эмитит editingFinished)
    for attr_name, val in (
        ('MODEL_MESSAGE_LIMIT', msg),
        ('MEMORY_CAPACITY', cap),
        ('RAG_MAX_RESULTS', rag),
    ):
        widget = getattr(gui, attr_name, None)
        if widget is not None and hasattr(widget, 'setText'):
            widget.setText(str(val))


def detect_memory_profile(gui) -> str:
    """Вернуть ключ пресета ('optimized'/'balanced'/'large'/'custom') по текущим настройкам."""
    try:
        vals = (
            int(get_setting(gui, 'MODEL_MESSAGE_LIMIT', 35)),
            int(get_setting(gui, 'MEMORY_CAPACITY', 50)),
            int(get_setting(gui, 'RAG_MAX_RESULTS', 50)),
        )
    except (TypeError, ValueError):
        return 'custom'
    for key, preset in PRESETS.items():
        if preset == vals:
            return key
    return 'custom'


def sync_profile_label(gui) -> None:
    """
    Пересчитать текущий профиль по значениям настроек и обновить
    combobox MEMORY_PROFILE если он изменился.
    """
    try:
        key = detect_memory_profile(gui)
        lang = get_setting(gui, 'LANGUAGE', 'RU')
        label = KEY_TO_LABEL_EN[key] if lang == 'EN' else KEY_TO_LABEL_RU[key]
        combo = getattr(gui, 'MEMORY_PROFILE', None)
        if combo is not None and hasattr(combo, 'currentText'):
            if combo.currentText() != label:
                combo.blockSignals(True)
                combo.setCurrentText(label)
                combo.blockSignals(False)
        gui._save_setting('MEMORY_PROFILE', label)
    except Exception:
        pass
