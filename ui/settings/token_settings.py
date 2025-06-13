import tkinter as tk
from utils import getTranslationVariant as _


def setup_token_settings_controls(self, parent):
    """Создает секцию настроек для управления параметрами токенов."""
    token_settings_config = [
        {'label': _('Показывать информацию о токенах', 'Show Token Info'), 'key': 'SHOW_TOKEN_INFO',
         'type': 'checkbutton', 'default_checkbutton': True,
         'tooltip': _('Отображать количество токенов и ориентировочную стоимость в интерфейсе чата.',
                      'Display token count and approximate cost in the chat interface.')},
        {'label': _('Стоимость токена (вход, ₽)', 'Token Cost (input, ₽)'), 'key': 'TOKEN_COST_INPUT',
         'type': 'entry', 'default': 0.000001, 'validation': self.validate_float_positive_or_zero,
         'tooltip': _('Стоимость одного токена для входных данных (например, 0.000001 ₽ за токен).',
                      'Cost of one token for input data (e.g., 0.000001 ₽ per token).')},
        {'label': _('Стоимость токена (выход, ₽)', 'Token Cost (output, ₽)'), 'key': 'TOKEN_COST_OUTPUT',
         'type': 'entry', 'default': 0.000002, 'validation': self.validate_float_positive_or_zero,
         'tooltip': _('Стоимость одного токена для выходных данных (например, 0.000002 ₽ за токен).',
                      'Cost of one token for output data (e.g., 0.000002 ₽ per token).')},
        {'label': _('Максимальное количество токенов модели', 'Max Model Tokens'), 'key': 'MAX_MODEL_TOKENS',
         'type': 'entry', 'default': 32000, 'validation': self.validate_positive_integer,
         'tooltip': _('Максимальное количество токенов, которое может обработать модель.',
                      'Maximum number of tokens the model can process.')},
    ]

    self.create_settings_section(parent,
                                 _("Настройки токенов", "Token Settings"),
                                 token_settings_config)