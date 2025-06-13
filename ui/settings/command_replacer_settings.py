import tkinter as tk
from utils import _


def setup_command_replacer_controls(self, parent):
    """Создает секцию настроек для Command Replacer."""
    command_replacer_config = [
        {'label': _('Использовать Command Replacer', 'Use Command Replacer'), 'key': 'USE_COMMAND_REPLACER',
         'type': 'checkbutton',
         'default_checkbutton': False, 'tooltip': _('Включает замену команд в ответе модели на основе схожести.',
                                                    'Enables replacing commands in the model response based on similarity.')},
        {'label': _('Мин. порог схожести', 'Min Similarity Threshold'), 'key': 'MIN_SIMILARITY_THRESHOLD',
         'type': 'entry',
         'default': 0.40, 'tooltip': _('Минимальный порог схожести для замены команды (0.0-1.0).',
                                       'Minimum similarity threshold for command replacement (0.0-1.0).')},
        {'label': _('Порог смены категории', 'Category Switch Threshold'), 'key': 'CATEGORY_SWITCH_THRESHOLD',
         'type': 'entry',
         'default': 0.18,
         'tooltip': _('Дополнительный порог для переключения на другую категорию команд (0.0-1.0).',
                      'Additional threshold for switching to a different command category (0.0-1.0).')},
        {'label': _('Пропускать параметры с запятой', 'Skip Comma Parameters'), 'key': 'SKIP_COMMA_PARAMETERS',
         'type': 'checkbutton',
         'default_checkbutton': True, 'tooltip': _('Пропускать параметры, содержащие запятую, при замене.',
                                                   'Skip parameters containing commas during replacement.')},
    ]

    self.create_settings_section(parent,
                                 _("Настройки Command Replacer (БЕТА)", "Command Replacer Settings (BETA)"),
                                 command_replacer_config)