import tkinter as tk
from utils import getTranslationVariant as _

def setup_general_settings_control(self, parent):
    general_config = [
        # здесь настройки из setup_model_controls
        {'label': _('Настройки сообщений', 'Message settings'), 'type': 'text'},
        {'label': _('Промты раздельно', 'Separated prompts'), 'key': 'SEPARATE_PROMPTS',
         'type': 'checkbutton', 'default_checkbutton': True},

        {'label': _('Лимит сообщений', 'Message limit'), 'key': 'MODEL_MESSAGE_LIMIT',
         'type': 'entry', 'default': 40,
         'tooltip': _('Сколько сообщений будет помнить мита', 'How much messages Mita will remember')},
        {'label': _('Сохранять утерянную историю ', 'Save lost history'),
         'key': 'GPT4FREE_LAST_ATTEMPT', 'type': 'checkbutton', 'default_checkbutton': False},

        {'label': _('Кол-во попыток', 'Attempt count'), 'key': 'MODEL_MESSAGE_ATTEMPTS_COUNT',
         'type': 'entry', 'default': 3},
        {'label': _('Время между попытками', 'time between attempts'),
         'key': 'MODEL_MESSAGE_ATTEMPTS_TIME', 'type': 'entry', 'default': 0.20},
        {'label': _('Включить стриминговую передачу', 'Enable Streaming'), 'key': 'ENABLE_STREAMING',
         'type': 'checkbutton',
         'default_checkbutton': False},
        {'label': _('Использовать gpt4free последней попыткой ', 'Use gpt4free as last attempt'),
         'key': 'GPT4FREE_LAST_ATTEMPT', 'type': 'checkbutton', 'default_checkbutton': False},

        {'label': _('Настройки ожидания', 'Waiting settings'), 'type': 'text'},
        {'label': _('Время ожидания текста (сек)', 'Text waiting time (sec)'),
         'key': 'TEXT_WAIT_TIME', 'type': 'entry', 'default': 40,
         'tooltip': _('время ожидания ответа', 'response waiting time')},
        {'label': _('Время ожидания звука (сек)', 'Voice waiting time (sec)'),
         'key': 'VOICE_WAIT_TIME', 'type': 'entry', 'default': 40,
         'tooltip': _('время ожидания озвучки', 'voice generation waiting time')},

        {'label': _('Настройки генерации текста', 'Text Generation Settings'), 'type': 'text'},

        {'label': _('Использовать Макс.Токены', 'Use Max response tokens'), 'key': 'USE_MODEL_MAX_RESPONSE_TOKENS',
         'type': 'checkbutton', 'default_checkbutton': self.settings.get('USE_MODEL_MAX_RESPONSE_TOKENS', True),
         'tooltip': _('Включает/выключает параметр макс токены', 'Enables/disables max response tokens parameter')},
        {'label': _('Макс. токенов в ответе', 'Max response tokens'), 'key': 'MODEL_MAX_RESPONSE_TOKENS',
         'type': 'entry', 'default': 2500, 'validation': self.validate_positive_integer,
         'tooltip': _('Максимальное количество токенов в ответе модели',
                      'Maximum number of tokens in the model response')},

        {'label': _('Температура', 'Temperature'), 'key': 'MODEL_TEMPERATURE',
         'type': 'entry', 'default': 0.5, 'validation': self.validate_float_0_to_2,
         'tooltip': _('Креативность ответа (0.0 = строго, 2.0 = очень творчески)',
                      'Creativity of response (0.0 = strict, 2.0 = very creative)')},

        {'label': _('Использовать Top-K', 'Use Top-K'), 'key': 'USE_MODEL_TOP_K',
         'type': 'checkbutton', 'default_checkbutton': self.settings.get('USE_MODEL_TOP_K', True),
         'tooltip': _('Включает/выключает параметр Top-K', 'Enables/disables Top-K parameter')},
        {'label': _('Top-K', 'Top-K'), 'key': 'MODEL_TOP_K',
         'type': 'entry', 'default': 0, 'validation': self.validate_positive_integer_or_zero, 'width': 30,
         'tooltip': _('Ограничивает выбор токенов K наиболее вероятными (0 = отключено)',
                      'Limits token selection to K most likely (0 = disabled)')},

        {'label': _('Использовать Top-P', 'Use Top-P'), 'key': 'USE_MODEL_TOP_P',
         'type': 'checkbutton', 'default_checkbutton': self.settings.get('USE_MODEL_TOP_P', True),
         'tooltip': _('Включает/выключает параметр Top-P', 'Enables/disables Top-P parameter')},
        {'label': _('Top-P', 'Top-P'), 'key': 'MODEL_TOP_P',
         'type': 'entry', 'default': 1.0, 'validation': self.validate_float_0_to_1, 'width': 30,
         'tooltip': _('Ограничивает выбор токенов по кумулятивной вероятности (0.0-1.0)',
                      'Limits token selection by cumulative probability (0.0-1.0)')},

        {'label': _('Использовать бюджет размышлений', 'Use thinking budget'), 'key': 'USE_MODEL_THINKING_BUDGET',
         'type': 'checkbutton', 'default_checkbutton': self.settings.get('USE_MODEL_THINKING_BUDGET', False),
         'tooltip': _('Включает/выключает параметр размышлений', 'Enables/disables Thought parameter')},
        {'label': _('Бюджет размышлений', 'Thinking budget'), 'key': 'MODEL_THINKING_BUDGET',
         'type': 'entry', 'default': 0.0, 'validation': self.validate_float_minus2_to_2, 'width': 30,
         'tooltip': _('Параметр, влияющий на глубину "размышлений" модели (зависит от модели)',
                      'Parameter influencing the depth of model "thoughts" (model-dependent)')},

        {'label': _('Штраф присутствия', 'Use Presence penalty'),
         'key': 'USE_MODEL_PRESENCE_PENALTY',
         'type': 'checkbutton',
         'default_checkbutton': self.settings.get('USE_MODEL_PRESENCE_PENALTY', False),
         'tooltip': _('Использовать параметр Штраф присутствия', 'Use the Presence penalty parameter')},
        {'label': _('Штраф присутствия', 'Presence penalty'), 'key': 'MODEL_PRESENCE_PENALTY',
         'type': 'entry', 'default': 0.0, 'validation': self.validate_float_minus2_to_2,
         'tooltip': _('Штраф за использование новых токенов (-2.0 = поощрять новые, 2.0 = сильно штрафовать)',
                      'Penalty for using new tokens (-2.0 = encourage new, 2.0 = strongly penalize)')},

        {'label': _('Использовать Штраф частоты', 'Use Frequency penalty'),
         'key': 'USE_MODEL_FREQUENCY_PENALTY',
         'type': 'checkbutton',
         'default_checkbutton': self.settings.get('USE_MODEL_FREQUENCY_PENALTY', False),
         'tooltip': _('Использовать параметр Штраф частоты', 'Use the Frequency penalty parameter')},
        {'label': _('Штраф частоты', 'Frequency penalty'), 'key': 'MODEL_FREQUENCY_PENALTY',
         'type': 'entry', 'default': 0.0, 'validation': self.validate_float_minus2_to_2,
         'tooltip': _(
             'Штраф за частоту использования токенов (-2.0 = поощрять повторение, 2.0 = сильно штрафовать)',
             'Penalty for the frequency of token usage (-2.0 = encourage repetition, 2.0 = strongly penalize)')},

        {'label': _('Использовать Лог вероятности', 'Use Log probability'),
         'key': 'USE_MODEL_LOG_PROBABILITY',
         'type': 'checkbutton',
         'default_checkbutton': self.settings.get('USE_MODEL_LOG_PROBABILITY', False),
         'tooltip': _('Использовать параметр Лог вероятности', 'Use the Log probability parameter')},
        {'label': _('Лог вероятности', 'Log probability'), 'key': 'MODEL_LOG_PROBABILITY',
         'type': 'entry', 'default': 0.0, 'validation': self.validate_float_minus2_to_2,
         'tooltip': _(
             'Параметр, влияющий на логарифмическую вероятность выбора токенов (-2.0 = поощрять, 2.0 = штрафовать)',
             'Parameter influencing the logarithmic probability of token selection (-2.0 = encourage, 2.0 = penalize)')},

    ]

    self.create_settings_section(parent,
                                 _("Общие настройки моделей", "General settings for models"),
                                 general_config)
