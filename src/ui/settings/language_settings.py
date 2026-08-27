"""Отдельная вкладка настроек языка интерфейса.

Содержит выбор языка (с предложением перезапуска) и работу с кастомными
переводами: кнопку «Открыть папку с языками» и краткую инструкцию. Языки
строятся динамически из доступных JSON-локалей (встроенные + внешняя папка
``NEUROMITA_BASE_DIR/Localization``)."""

from __future__ import annotations

from ui.gui_templates import create_settings_section, create_section_header
from ui.settings.settings_access import get_setting
from utils import getTranslationVariant as _


def _on_language_changed(gui, value=None):
    """Живая смена языка: применяем сразу, без перезапуска."""
    code = str(value or "").strip().upper()
    if not code:
        code = str(get_setting(gui, "LANGUAGE", "RU") or "RU").upper()
    try:
        from localization.live import set_language
        set_language(code)
    except Exception:
        # Фолбэк на старое поведение, если live-слой недоступен.
        try:
            from ui.language_restart import prompt_language_restart
            prompt_language_restart(gui)
        except Exception:
            pass


def _open_language_folder(gui=None):
    """Создаёт (при необходимости) и открывает внешнюю папку кастомных локалей."""
    try:
        from localization import ensure_external_localization_dir
        path = ensure_external_localization_dir()
        if not path:
            from PyQt6.QtWidgets import QMessageBox
            QMessageBox.information(
                gui,
                _("Папка с языками", "Language folder"),
                _("Папка для кастомных языков недоступна (не задан базовый каталог).",
                  "The custom-language folder is unavailable (base directory is not set)."),
            )
            return
        from PyQt6.QtCore import QUrl
        from PyQt6.QtGui import QDesktopServices
        QDesktopServices.openUrl(QUrl.fromLocalFile(path))
    except Exception:
        pass


def setup_language_settings_controls(self, parent):
    create_section_header(parent, _("Язык интерфейса", "Interface language"))

    # Список языков — динамически из доступных JSON-локалей (RU + найденные).
    try:
        from localization import available_languages, language_display_name
        _lang_codes = available_languages()
    except Exception:
        _lang_codes = ["RU", "EN"]
        language_display_name = lambda c: c
    _lang_codes = ["RU"] + sorted(c for c in _lang_codes if c != "RU")
    # Пункты вида (display, value): показываем «RU — Русский», но значение
    # (сохраняемая настройка) остаётся голым кодом языка.
    _lang_options = [(f"{code} — {language_display_name(code)}", code) for code in _lang_codes]

    language_config = [
        {'label': _('Выбор языка интерфейса приложения.', 'Select the application interface language.'),
         'type': 'text'},
        {'label': 'Язык / Language', 'key': 'LANGUAGE', 'type': 'combobox',
         'options': _lang_options, 'default': "RU",
         'command': lambda v: _on_language_changed(self, v),
         'tooltip': _('Язык интерфейса. Применяется после перезапуска.',
                      'Interface language. Applied after a restart.')},
    ]
    create_settings_section(
        self, parent,
        "Язык / Language",
        language_config,
        icon_name='fa5s.globe',
    )

    # ── Кастомные переводы ──────────────────────────────────────────────────
    custom_config = [
        {'label': _(
            'Внешние JSON-локали подключаются из папки языков после перезапуска.',
            'External JSON locales are loaded from the language folder after restart.'),
         'type': 'text'},
        {'label': _(
            'Можно добавить свой язык: киньте файл «<код>.json» (например pl.json)\n'
            'в папку с языками и перезапустите приложение — он появится в списке выше.\n'
            'Ключи — русские строки, переводите только значения.\n'
            'Имя языка в списке задаётся ключом «_name».',
            'You can add your own language: drop a "<code>.json" file (e.g. pl.json)\n'
            'into the language folder and restart — it will appear in the list above.\n'
            'Keys are the Russian source strings, translate only the values.\n'
            'The display name is set via the "_name" key.'),
         'type': 'text'},
        {'label': _('Открыть папку с языками', 'Open language folder'),
         'type': 'button',
         'command': lambda: _open_language_folder(self)},
    ]
    create_settings_section(
        self, parent,
        _('Кастомные переводы', 'Custom translations'),
        custom_config,
        icon_name='fa5s.folder-open',
    )
