import tkinter as tk

from SettingsManager import CollapsibleSection
from utils import getTranslationVariant as _

def setup_g4f_controls(self, parent):
    """Создает секцию настроек для управления версией g4f."""
    section = CollapsibleSection(parent, _("Настройки g4f", "g4f Settings"))
    section.pack(fill=tk.X, padx=5, pady=5, expand=True)

    use_g4f = self.create_setting_widget(
        parent=section.content_frame,
        label=_('Использовать gpt4free', 'Use gpt4free'),
        setting_key='gpt4free',  # Этот ключ теперь просто хранит последнюю введенную/установленную версию
        widget_type='checkbutton',
        default_checkbutton=False,
        # tooltip=_('Укажите версию g4f (например, 0.4.7.7 или latest). Обновление произойдет при следующем запуске.',
        #          'Specify the g4f version (e.g., 0.4.7.7 or latest). The update will occur on the next launch.')
    )
    section.add_widget(use_g4f)

    model_g4f = self.create_setting_widget(
        parent=section.content_frame,
        label=_('Модель gpt4free', 'model gpt4free'),
        setting_key='gpt4free_model',  # Этот ключ теперь просто хранит последнюю введенную/установленную версию
        widget_type='entry',
        default="gemini-1.5-flash",
    )
    section.add_widget(model_g4f)
    # {'label': , 'key': 'gpt4free', 'type': 'checkbutton',
    #      'default_checkbutton': False},
    #      {'label': _('gpt4free | Модель gpt4free', 'gpt4free | model gpt4free'), 'key': 'gpt4free_model',
    #       'type': 'entry', 'default': "gemini-1.5-flash"},

    version_frame = self.create_setting_widget(
        parent=section.content_frame,
        label=_('Версия gpt4free', 'gpt4free Version'),
        setting_key='G4F_VERSION',  # Этот ключ теперь просто хранит последнюю введенную/установленную версию
        widget_type='entry',
        default='0.4.7.7',
        tooltip=_('Укажите версию g4f (например, 0.4.7.7 или latest). Обновление произойдет при следующем запуске.',
                  'Specify the g4f version (e.g., 0.4.7.7 or latest). The update will occur on the next launch.')
    )
    self.g4f_version_entry = None
    for widget in version_frame.winfo_children():
        if isinstance(widget, tk.Entry):
            self.g4f_version_entry = widget
            break
    if not self.g4f_version_entry:
        logger.error("Не удалось найти виджет Entry для версии g4f!")
    section.add_widget(version_frame)

    # Кнопка теперь вызывает trigger_g4f_reinstall_schedule
    button_frame = self.create_setting_widget(
        parent=section.content_frame,
        label=_('Запланировать обновление g4f', 'Schedule g4f Update'),  # Текст кнопки изменен
        setting_key='',
        widget_type='button',
        command=self.trigger_g4f_reinstall_schedule  # Привязываем к новой функции
    )
    section.add_widget(button_frame)