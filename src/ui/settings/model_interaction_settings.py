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
            'label': _('Поведение запросов и работа инструментов. Параметры генерации настраиваются у API-пресета.',
                       'Request behavior and tool usage. Generation parameters are configured in the API preset.'),
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
         'description': _('Добавляет явное поле reasoning в схему вывода перед остальными полями. В основном полезно для локальных моделей без нативного reasoning. Отключите при нативном thinking/reasoning, чтобы избежать дублирования и лишних токенов.',
                          'Adds an explicit reasoning field to the output schema before other fields. Useful mainly for local or non-reasoning models. Disable with native thinking/reasoning to avoid duplicate reasoning and extra token usage.'),
         'tooltip': _('Когда включать: используйте для моделей без нативного reasoning, если они иногда выбирают неправильные действия, эмоции, вызовы инструментов или другие структурированные поля. '
                      'Модель сначала пишет короткий шаг рассуждения, а затем заполняет финальные поля ответа, используя этот контекст.\n\n'
                      'Когда отключать: отключите для моделей, которые уже используют нативный thinking/reasoning, блоки <think> или отдельный канал reasoning. '
                      'В таких случаях настройка обычно дублирует внутренние рассуждения модели и расходует токены впустую.',
                      'When to enable: Use this for models without native reasoning when they sometimes choose incorrect actions, emotions, tool calls, or other structured fields. '
                      'The model first writes a short reasoning step and then fills the final response fields using that context.\n\n'
                      'When to disable: Disable it for models that already use native thinking/reasoning, <think> blocks, or a separate reasoning channel. '
                      'In those cases it usually duplicates the model\'s internal reasoning and wastes tokens.')},

        {'type': 'end'},

        {'label': _('Настройки ожидания', 'Waiting settings'), 'type': 'subsection'},
        {'label': _('Время ожидания текста (сек)', 'Text waiting time (sec)'),
         'key': 'TEXT_WAIT_TIME', 'type': 'entry', 'default': 40,
         'tooltip': _('время ожидания ответа', 'response waiting time')},
        {'label': _('Время ожидания звука (сек)', 'Voice waiting time (sec)'),
         'key': 'VOICE_WAIT_TIME', 'type': 'entry', 'default': 40,
         'tooltip': _('время ожидания озвучки', 'voice generation waiting time')},

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

        {'label': _('GOOGLE API KEY', 'GOOGLE API KEY'), 'key': 'GOOGLE_API_KEY', 'type': 'entry',
         'default': "", 'hide': bool(self.settings.get("HIDE_PRIVATE"))},
        {'label': _('GOOGLE CSE ID', 'GOOGLE CSE ID'), 'key': 'GOOGLE_CSE_ID', 'type': 'entry',
         'default': "", 'hide': bool(self.settings.get("HIDE_PRIVATE"))},

        {'type': 'end'},
    ]

    create_settings_section(
        self, parent,
        _("Поведение запросов", "Request behavior"),
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
                'L2 — полноценный ответ мощной моделью.',
                'Reactions are triggered by events, not direct user input.\n'
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
        # Реакции L1 (тихие) временно убраны из интерфейса и выключены по
        # умолчанию (см. REACT_L1_ENABLED в create_task.py). Ключи в коде
        # сохранены — фичу можно вернуть, добавив контролы обратно.
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
        react_settings_config,
        icon_name='fa5s.bolt'
    )

    build_memory_section(self, parent, provider_options)
    build_rag_section(self, parent, provider_options)
    register_provider_options(
        self,
        ("REACT_PROVIDER_L2", "HC_PROVIDER", "GRAPH_PROVIDER"),
    )

    # Token pricing/context limits now come from the selected provider/preset,
    # so the old manual "Token Settings" subsection is intentionally removed.

