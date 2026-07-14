from ui.gui_templates import create_settings_section, create_section_header
from utils import getTranslationVariant as _


def setup_model_interaction_controls(
    self,
    parent,
    *,
    runtime_options_view_model,
    build_memory_section,
    build_rag_section,
):
    from ui.settings.runtime_options import attach_runtime_options_view_model

    attach_runtime_options_view_model(self, runtime_options_view_model)
    create_section_header(parent, _("Настройки взаимодействия с моделью", "Model Interaction Settings"))

    general_config = [
        {
            'label': _('Параметры генерации ответов моделью и работы инструментов (tools).',
                       'Parameters for response generation and tool usage.'),
            'type': 'text',
        },
        {'label': _('Настройки сообщений', 'Message settings'), 'type': 'subsection'},
        {'label': _('Промты раздельно', 'Separated prompts'), 'key': 'SEPARATE_PROMPTS',
         'type': 'checkbutton', 'default_checkbutton': True},
        {'label': _('Кол-во попыток', 'Attempt count'), 'key': 'MODEL_MESSAGE_ATTEMPTS_COUNT',
         'type': 'entry', 'default': 3},
        {'label': _('Время между попытками', 'time between attempts'),
         'key': 'MODEL_MESSAGE_ATTEMPTS_TIME', 'type': 'entry', 'default': 0.20},
        {'label': _('Включить стриминговую передачу', 'Enable Streaming'), 'key': 'ENABLE_STREAMING',
         'type': 'checkbutton',
         'default_checkbutton': False},
        {'label': _('Reasoning в схеме (schema CoT)', 'Schema reasoning (CoT)'), 'key': 'SCHEMA_REASONING',
         'type': 'checkbutton',
         'default_checkbutton': False,
         'tooltip': _('Включает поле reasoning в JSON-схему структурированного ответа. '
                      'Модель "думает вслух" перед заполнением полей — улучшает качество для локальных моделей. '
                      'Отключите если используете нативный thinking или хотите сэкономить токены.',
                      'Adds a reasoning field to the structured output JSON schema. '
                      'The model "thinks aloud" before filling other fields — improves quality for local models. '
                      'Disable if using native thinking or to save tokens.')},
        {'label': _('Режим размышлений (enable_thinking)', 'Enable thinking mode'), 'key': 'ENABLE_THINKING',
         'type': 'checkbutton',
         'default_checkbutton': False,
         'tooltip': _('Для моделей Qwen3 и аналогичных: включает thinking-режим. '
                      'Выключите если модель кладёт ответ в reasoning_content вместо content.',
                      'For Qwen3 and similar models: enables thinking mode. '
                      'Disable if the model puts the response into reasoning_content instead of content.')},
        {'label': _('Использовать gpt4free последней попыткой ', 'Use gpt4free as last attempt'),
         'key': 'GPT4FREE_LAST_ATTEMPT', 'type': 'checkbutton', 'default_checkbutton': False},

        {'type': 'end'},

        {'label': _('Настройки ожидания', 'Waiting settings'), 'type': 'subsection'},
        {'label': _('Время ожидания текста (сек)', 'Text waiting time (sec)'),
         'key': 'TEXT_WAIT_TIME', 'type': 'entry', 'default': 40,
         'tooltip': _('время ожидания ответа', 'response waiting time')},
        {'label': _('Время ожидания звука (сек)', 'Voice waiting time (sec)'),
         'key': 'VOICE_WAIT_TIME', 'type': 'entry', 'default': 40,
         'tooltip': _('время ожидания озвучки', 'voice generation waiting time')},

        {'type': 'end'},

        {'label': _('Настройки генерации текста', 'Text Generation Settings'), 'type': 'subsection'},

        {'label': _('Макс. токенов в ответе', 'Max response tokens'),
        'key': 'MODEL_MAX_RESPONSE_TOKENS',
        'type': 'entry',
        'toggle_key': 'USE_MODEL_MAX_RESPONSE_TOKENS',
        'toggle_default': self.settings.get('USE_MODEL_MAX_RESPONSE_TOKENS', True),
        'default': 2500,
        'validation': self.validate_positive_integer,
        'tooltip': _('Максимальное количество токенов в ответе модели',
                    'Maximum number of tokens in the model response')},

        {'label': _('Температура', 'Temperature'), 'key': 'MODEL_TEMPERATURE',
         'type': 'entry', 'default': '',
         'toggle_key': 'USE_MODEL_TEMPERATURE',
         'toggle_default': self.settings.get('USE_MODEL_TEMPERATURE', True),
         'validation': self.validate_float_0_to_2,
         'tooltip': _('Креативность ответа (0.0 = строго, 2.0 = очень творчески)',
                      'Creativity of response (0.0 = strict, 2.0 = very creative)')},

        {'label': _('Top-K', 'Top-K'),
        'key': 'MODEL_TOP_K',
        'type': 'entry',
        'toggle_key': 'USE_MODEL_TOP_K',
        'toggle_default': self.settings.get('USE_MODEL_TOP_K', True),
        'default': '',
        'validation': self.validate_positive_integer_or_zero,
        'tooltip': _('Ограничивает выбор токенов K наиболее вероятными (0 = отключено)',
                    'Limits token selection to K most likely (0 = disabled)')},

        {'label': _('Top-P', 'Top-P'),
        'key': 'MODEL_TOP_P',
        'type': 'entry',
        'toggle_key': 'USE_MODEL_TOP_P',
        'toggle_default': self.settings.get('USE_MODEL_TOP_P', True),
        'default': '',
        'validation': self.validate_float_0_to_1,
        'tooltip': _('Ограничивает выбор токенов по кумулятивной вероятности (0.0-1.0)',
                    'Limits token selection by cumulative probability (0.0-1.0)')},

        {'label': _('Бюджет размышлений', 'Thinking budget'),
        'key': 'MODEL_THINKING_BUDGET',
        'type': 'entry',
        'toggle_key': 'USE_MODEL_THINKING_BUDGET',
        'toggle_default': self.settings.get('USE_MODEL_THINKING_BUDGET', False),
        'default': 0.0,
        'validation': self.validate_float_minus2_to_2,
        'tooltip': _('Параметр, влияющий на глубину "размышлений" модели (зависит от модели)',
                    'Parameter influencing the depth of model "thoughts" (model-dependent)')},

        {'label': _('Бюджет размышлений Gemini (токены)', 'Gemini thinking budget (tokens)'),
        'key': 'GEMINI_THINKING_BUDGET',
        'type': 'entry',
        'toggle_key': 'USE_GEMINI_THINKING_BUDGET',
        'toggle_default': self.settings.get('USE_GEMINI_THINKING_BUDGET', False),
        'default': 8192,
        'validation': self.validate_positive_integer_or_zero,
        'tooltip': _('Бюджет токенов для размышлений Gemini 2.5+. 0 = отключить. '
                     'Если переключатель выключен — бюджет динамический (по умолчанию). '
                     'Работает только при включённом "Режиме размышлений".',
                     'Token budget for Gemini 2.5+ thinking. 0 = disable. '
                     'If toggle is off — budget is dynamic (default). '
                     'Requires "Enable thinking mode" to be enabled.')},

        {'label': _('Штраф присутствия', 'Presence penalty'),
        'key': 'MODEL_PRESENCE_PENALTY',
        'type': 'entry',
        'toggle_key': 'USE_MODEL_PRESENCE_PENALTY',
        'toggle_default': self.settings.get('USE_MODEL_PRESENCE_PENALTY', False),
        'default': 0.0,
        'validation': self.validate_float_minus2_to_2,
        'tooltip': _('Штраф за использование новых токенов (-2.0 = поощрять новые, 2.0 = сильно штрафовать)',
                    'Penalty for using new tokens (-2.0 = encourage new, 2.0 = strongly penalize)')},

        {'label': _('Штраф частоты', 'Frequency penalty'),
        'key': 'MODEL_FREQUENCY_PENALTY',
        'type': 'entry',
        'toggle_key': 'USE_MODEL_FREQUENCY_PENALTY',
        'toggle_default': self.settings.get('USE_MODEL_FREQUENCY_PENALTY', False),
        'default': 0.0,
        'validation': self.validate_float_minus2_to_2,
        'tooltip': _('Штраф за частоту использования токенов (-2.0 = поощрять повторение, 2.0 = сильно штрафовать)',
                    'Penalty for the frequency of token usage (-2.0 = encourage repetition, 2.0 = strongly penalize)')},

        {'label': _('Лог вероятности', 'Log probability'),
        'key': 'MODEL_LOG_PROBABILITY',
        'type': 'entry',
        'toggle_key': 'USE_MODEL_LOG_PROBABILITY',
        'toggle_default': self.settings.get('USE_MODEL_LOG_PROBABILITY', False),
        'default': 0.0,
        'validation': self.validate_float_minus2_to_2,
        'tooltip': _('Параметр, влияющий на логарифмическую вероятность выбора токенов (-2.0 = поощрять, 2.0 = штрафовать)',
                    'Parameter influencing the logarithmic probability of token selection (-2.0 = encourage, 2.0 = penalize)')},

        {'type': 'end'},

        {'label': _('Инструменты (Tools)', 'Tools'), 'type': 'subsection'},

        {'label': _('Вызов инструментов', 'Tools use'),
         'key': 'TOOLS_ON', 'type': 'checkbutton', 'default_checkbutton': True,
         'tooltip': _(
             'Позволяет использовать инструменты такие как поиск в сети',
             'Allow using tools like search')},

        {'label': _('Калькулятор', 'Calculator'), 'key': 'TOOL_ENABLED_calculator',
         'type': 'checkbutton', 'default_checkbutton': False, 'depends_on': 'TOOLS_ON',
         'tooltip': _('Включить инструмент "Калькулятор"', 'Enable the Calculator tool')},
        {'label': _('Поиск в интернете', 'Web Search'), 'key': 'TOOL_ENABLED_web_search',
         'type': 'checkbutton', 'default_checkbutton': False, 'depends_on': 'TOOLS_ON',
         'tooltip': _('Включить инструмент "Поиск в сети" (DuckDuckGo)', 'Enable the Web Search tool (DuckDuckGo)')},
        {'label': _('Google поиск', 'Google Search'), 'key': 'TOOL_ENABLED_google_search',
         'type': 'checkbutton', 'default_checkbutton': False, 'depends_on': 'TOOLS_ON',
         'tooltip': _('Включить инструмент "Google Search" (требует API ключ)', 'Enable the Google Search tool (requires API key)')},
        {'label': _('Чтение страниц', 'Web Reader'), 'key': 'TOOL_ENABLED_web_reader',
         'type': 'checkbutton', 'default_checkbutton': False, 'depends_on': 'TOOLS_ON',
         'tooltip': _('Включить инструмент "Чтение веб-страниц"', 'Enable the Web Reader tool')},
        {'label': _('Поиск воспоминаний', 'Memory Search'), 'key': 'TOOL_ENABLED_memory_search',
         'type': 'checkbutton', 'default_checkbutton': True, 'depends_on': 'TOOLS_ON',
         'tooltip': _(
             'Мита может сама искать по воспоминаниям и истории чата. '
             'Работает независимо от автоматического RAG. '
             'Поддерживает фильтр по дате и выбор типа поиска.',
             'Mita can search her memories and chat history on demand. '
             'Works independently of automatic RAG. '
             'Supports date filters and search type selection.')},
        {'label': _('Напоминания', 'Reminders'), 'key': 'TOOL_ENABLED_reminder',
         'type': 'checkbutton', 'default_checkbutton': True, 'depends_on': 'TOOLS_ON',
         'tooltip': _(
             'Мита может добавлять, просматривать и удалять напоминания через тулу. '
             'Поддерживает относительные даты: "через 2 часа", "завтра в 18:00".',
             'Mita can add, view and delete reminders via tool. '
             'Supports relative dates: "through 2 hours", "tomorrow at 18:00".')},

        {'label': _('Макс. глубина цепочки тулов', 'Max tool chain depth'),
         'key': 'TOOL_MAX_DEPTH', 'type': 'entry',
         'default': 2, 'depends_on': 'TOOLS_ON',
         'tooltip': _(
             'Максимальное количество тул-вызовов подряд в одном диалоге (1–5). '
             'Значение 2 позволяет цепочку: например, поиск → чтение страницы.',
             'Max number of consecutive tool calls per dialogue (1–5). '
             'Value 2 enables chains: e.g. web_search → web_reader.')},

        {'label': _('Режим инжекции результата тула', 'Tool result message mode'),
         'key': 'TOOL_RESULT_MSG_MODE', 'type': 'combobox',
         'options': ['both', 'system', 'user'], 'default': 'both',
         'depends_on': 'TOOLS_ON',
         'tooltip': _(
             'Как передавать результат тула в следующий запрос к LLM.\n'
             'both — оба сообщения (рекомендуется, работает со всеми провайдерами).\n'
             'system — только system-роль (может игнорироваться Gemini).\n'
             'user — только user-роль с тегом [SYSTEM INFO].',
             'How to inject the tool result into the next LLM request.\n'
             'both — both messages (recommended, works with all providers).\n'
             'system — system role only (may be ignored by Gemini).\n'
             'user — user role only with [SYSTEM INFO] tag.')},

        {'label': _('GOOGLE API KEY'), 'key': 'GOOGLE_API_KEY', 'type': 'entry',
         'default': "", 'hide': bool(self.settings.get("HIDE_PRIVATE"))},
        {'label': _('GOOGLE CSE ID'), 'key': 'GOOGLE_CSE_ID', 'type': 'entry',
         'default': "", 'hide': bool(self.settings.get("HIDE_PRIVATE"))},

        {'type': 'end'},
    ]

    create_settings_section(
        self, parent,
        _("Параметры генерации", "Generation Parameters"),
        general_config,
        icon_name='fa5s.cogs'
    )

    from ui.settings.runtime_options import register_provider_options

    provider_options = [_("Текущий", "Current")]

    react_settings_config = [
        {
            'type': 'text',
            'label': _(
                'Реакции — это когда триггером генерации служит событие, а не прямой запрос пользователя.\n'
                'L1 — очень короткий ответ с выбором анимации (для слабых но шустрых моделей, сокращённый контекст).\n'
                'L2 — полноценный ответ мощной моделью.',
                'Reactions are triggered by events, not direct user input.\n'
                'L1 — very short response with animation choice (lightweight fast models, trimmed context).\n'
                'L2 — full response by a powerful model.'
            ),
        },
        {
            'label': _('Использовать реакции (react)', 'Use react events'),
            'key': 'REACT_ENABLED', 'type': 'checkbutton', 'default_checkbutton': True,
            'tooltip': _(
                'Включить генерацию реакций на действия игрока (react-задачи). '
                'Отключение полностью блокирует вызовы модели для react.',
                'Enable generation of reactions to player actions (react tasks). '
                'Disabling completely blocks model calls for react.'
            )
        },
        {
            'label': _('Использовать реакции L1 (тихие)', 'Enable react L1 (silent)'),
            'key': 'REACT_L1_ENABLED', 'type': 'checkbutton', 'default_checkbutton': False,
            'depends_on': 'REACT_ENABLED',
            'tooltip': _(
                'Тихие реакции: мимика/поза/действия без ответа текстом.',
                'Silent reactions: face/pose/actions without text answer.'
            )
        },
        {
            'label': _('Провайдер для реакций L1', 'Provider for react L1'),
            'key': 'REACT_PROVIDER_L1', 'type': 'combobox',
            'options': provider_options, 'default': _('Текущий', 'Current'),
            'depends_on': 'REACT_L1_ENABLED',
            'tooltip': _(
                'Какой API-пресет использовать для тихих react-сообщений (L1).',
                'Which API preset to use for silent react messages (L1).'
            )
        },
        {
            'label': _('Использовать реакции L2 (с ответом)', 'Enable react L2 (with answer)'),
            'key': 'REACT_L2_ENABLED', 'type': 'checkbutton', 'default_checkbutton': True,
            'depends_on': 'REACT_ENABLED',
            'tooltip': _(
                'Реакции с полноценным ответом: текст + озвучка, запись в историю.',
                'Answer reactions: text + voiceover, saved to history.'
            )
        },
        {
            'label': _('Провайдер для реакций L2', 'Provider for react L2'),
            'key': 'REACT_PROVIDER_L2', 'type': 'combobox',
            'options': provider_options, 'default': _('Текущий', 'Current'),
            'depends_on': 'REACT_L2_ENABLED',
            'tooltip': _(
                'Какой API-пресет использовать для react-ответов (L2).',
                'Which API preset to use for answer-react messages (L2).'
            )
        },
    ]

    create_settings_section(
        self, parent,
        _("Настройки реакций", "React settings"),
        react_settings_config
    )

    build_memory_section(self, parent, provider_options)
    build_rag_section(self, parent, provider_options)
    register_provider_options(
        self,
        ("REACT_PROVIDER_L1", "REACT_PROVIDER_L2", "HC_PROVIDER", "GRAPH_PROVIDER"),
    )

    # Token pricing/context limits now come from the selected provider/preset,
    # so the old manual "Token Settings" subsection is intentionally removed.

