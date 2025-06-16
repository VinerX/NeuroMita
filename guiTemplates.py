import tkinter as tk
from tkinter import ttk
from tkinter import messagebox

from Logger import logger
from SettingsManager import SettingsManager, CollapsibleSection
import os # Добавлено для os.path.exists
from utils import getTranslationVariant as _
from SettingsManager import CollapsibleSection


def create_settings_section(self, parent, title, settings_config):
    section = CollapsibleSection(parent, title)
    section.pack(fill=tk.X, padx=5, pady=5, expand=True)

    for config in settings_config:
        widget = create_setting_widget(
            gui=self,
            parent=section.content_frame,
            label=config['label'],
            setting_key=config.get('key', ''),
            widget_type=config.get('type', 'entry'),
            options=config.get('options', None),
            default=config.get('default', ''),
            default_checkbutton=config.get('default_checkbutton', False),
            validation=config.get('validation', None),
            tooltip=config.get('tooltip', ""),
            hide=config.get('hide', False),
            command=config.get('command', None),
            widget_name = config.get('widget_name', None)
        )
        section.add_widget(widget)

    return section


def create_setting_widget(gui, parent, label, setting_key, widget_type='entry',
                          options=None, default='', default_checkbutton=False, validation=None, tooltip=None,
                          width=None, height=None, command=None, hide=False, widget_name=None):
    """
    Creates a setting widget with various parameters.

    Параметры:
        parent: Родительский контейнер
        label: Текст метки
        setting_key: Ключ настройки
        widget_type: Тип виджета ('entry', 'combobox', 'checkbutton', 'button', 'scale', 'text')
        options: Опции для combobox
        default: Значение по умолчанию
        validation: Функция валидации
        tooltip: Текст подсказки
        width: Ширина виджета
        height: Высота виджета (для текстовых полей)
        command: Функция, вызываемая при изменении значения
        hide: не выводит при перезагрузке скрытые поля
    """
    # Применяем default при первом запуске
    if not gui.settings.get(setting_key):
        gui.settings.set(setting_key, default_checkbutton if widget_type == 'checkbutton' else default)

    frame = tk.Frame(parent, bg="#2c2c2c")
    frame.pack(fill=tk.X, pady=2)

    # Label
    lbl = tk.Label(frame, text=label, bg="#2c2c2c", fg="#ffffff", width=25, anchor='w')
    lbl.pack(side=tk.LEFT, padx=5)

    # Widgets
    if widget_type == 'entry':
        entry = tk.Entry(frame, bg="#1e1e1e", fg="#ffffff", insertbackground="white")
        if width:
            entry.config(width=width)

        if not hide:
            entry.insert(0, gui.settings.get(setting_key, default))
        entry.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=5)

        def save_entry():
            gui._save_setting(setting_key, entry.get())
            if command:
                command(entry.get())

        # Явная привязка горячих клавиш для Entry
        # entry.bind("<Control-v>", lambda e: self.cmd_paste(e.widget))
        # entry.bind("<Control-c>", lambda e: self.cmd_copy(e.widget))
        # entry.bind("<Control-x>", lambda e: self.cmd_cut(e.widget))

        entry.bind("<FocusOut>", lambda e: save_entry())
        entry.bind("<Return>", lambda e: save_entry())

        if validation:
            entry.config(validate="key", validatecommand=(parent.register(validation), '%P'))

    elif widget_type == 'combobox':
        var = tk.StringVar(value=gui.settings.get(setting_key, default))
        cb = ttk.Combobox(frame, textvariable=var, values=options, state="readonly")
        if width:
            cb.config(width=width)
        cb.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=5)

        def save_combobox():
            gui._save_setting(setting_key, var.get())
            if command:
                command()

        cb.bind("<<ComboboxSelected>>", lambda e: [save_combobox(), command()] if command else save_combobox())

    elif widget_type == 'checkbutton':
        var = tk.BooleanVar(value=gui.settings.get(setting_key, default_checkbutton))
        cb = tk.Checkbutton(frame, variable=var, bg="#2c2c2c",
                            command=lambda: [gui._save_setting(setting_key, var.get()),
                                             command(var.get()) if command else None])
        cb.pack(side=tk.LEFT, padx=5)

    elif widget_type == 'button':

        btn = tk.Button(
            frame,
            text=label,
            bg="#8a2be2",
            fg="#ffffff",
            activebackground="#6a1bcb",
            activeforeground="#ffffff",
            relief=tk.RAISED,
            bd=2,
            command=command
        )

        if width:
            btn.config(width=width)

        btn.pack(side=tk.LEFT, padx=5, ipadx=5, ipady=2)

        # Сохраняем ссылку на кнопку, если нужно
        if setting_key:
            gui._save_setting(setting_key, False)

    elif widget_type == 'scale':
        var = tk.DoubleVar(value=gui.settings.get(setting_key, default))
        scale = tk.Scale(frame, from_=options[0], to=options[1], orient=tk.HORIZONTAL,
                         variable=var, bg="#2c2c2c", fg="#ffffff", highlightbackground="#2c2c2c",
                         length=200 if not width else width)
        scale.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=5)

        def save_scale(value):
            gui._save_setting(setting_key, float(value))
            if command:
                command(float(value))

        scale.config(command=save_scale)

    elif widget_type == 'text':

        if setting_key != "":
            def save_text():
                gui._save_setting(setting_key, text.get('1.0', 'end-1c'))
                if command:
                    command(text.get('1.0', 'end-1c'))

            text = tk.Text(frame, bg="#1e1e1e", fg="#ffffff", insertbackground="white",
                           height=height if height else 5, width=width if width else 50)
            text.insert('1.0', gui.settings.get(setting_key, default))
            text.bind("<FocusOut>", lambda e: save_text())
            text.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=5)


        else:
            lbl.config(width=100)

    # Добавляем tooltip если указан
    if tooltip:
        gui.create_tooltip(frame, tooltip)

    if widget_name:
        setattr(frame, "widget_name", widget_name)
    else:
        setattr(frame, "widget_name", setting_key)


    return frame

def create_gui_settings_config():
    """Определяет конфигурацию для секции настроек GUI."""
    return [
        {'label': _('Настройки изображений в чате', 'Chat Image Settings'), 'type': 'text'},
        {'label': _('Заменять изображения заглушками', 'Replace images with placeholders'), 'key': 'REPLACE_IMAGES_WITH_PLACEHOLDERS',
         'type': 'checkbutton', 'default_checkbutton': False,
         'tooltip': _('Заменять отображение изображений в истории чата на текстовые заглушки.',
                      'Replace image display in chat history with text placeholders.')},
    ]

def create_tooltip(self, widget, text):
    """Создает всплывающую подсказку для виджета"""
    tooltip = tk.Toplevel(widget)
    tooltip.wm_overrideredirect(True)
    tooltip.wm_geometry("+0+0")
    tooltip.withdraw()

    label = tk.Label(tooltip, text=text, bg="#ffffe0", relief='solid', borderwidth=1)
    label.pack()

    def enter(event):
        x = widget.winfo_rootx() + widget.winfo_width() + 5
        y = widget.winfo_rooty()
        tooltip.wm_geometry(f"+{x}+{y}")
        tooltip.deiconify()

    def leave(event):
        tooltip.withdraw()

    widget.bind("<Enter>", enter)
    widget.bind("<Leave>", leave)

def find_widget_child_by_type(section, widget_name, widget_type = ttk.Combobox):
    """
    Ищет виджет с указанным именем и типом в указанной секции.

    Параметры:
        section: Секция, в которой нужно искать виджет.
        widget_name: Имя виджета, который нужно найти.
        widget_type: Тип виджета, который нужно найти (например, ttk.Combobox).

    Возвращает:
        Виджет, если он найден, или None, если нет.
    """
    for widget in section.content_frame.winfo_children():
        if hasattr(widget, 'widget_name') and widget.widget_name == widget_name:
            for child in widget.winfo_children():
                if isinstance(child, widget_type):
                    return child
    logger.warning(f"Виджет с именем '{widget_name}' и типом '{widget_type}' не найден в секции '{section.title}'.")
    return None


def find_widget_by_name(section, widget_name):
    """
    Ищет виджет с указанным именем в указанной секции.

    Параметры:
        section: Секция, в которой нужно искать виджет.
        widget_name: Имя виджета, который нужно найти.

    Возвращает:
        Виджет, если он найден, или None, если нет.
    """
    for widget in section.content_frame.winfo_children():
        if hasattr(widget, 'widget_name') and widget.widget_name == widget_name:
            return widget
    logger.warning(f"Виджет с именем '{widget_name}' не найден в секции '{section.title}'.")
    return None