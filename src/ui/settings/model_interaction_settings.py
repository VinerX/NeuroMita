from ui.gui_templates import create_settings_section, create_section_header
from utils import getTranslationVariant as _
from core.events import get_event_bus, Events

def setup_model_interaction_controls(self, parent):
    create_section_header(parent, _("Настройки взаимодействия с моделью", "Model Interaction Settings"))
    
    general_config = [
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
         'type': 'entry', 'default': 1.0, 'validation': self.validate_float_0_to_2,
         'tooltip': _('Креативность ответа (0.0 = строго, 2.0 = очень творчески)',
                      'Creativity of response (0.0 = strict, 2.0 = very creative)')},

        {'label': _('Top-K', 'Top-K'),
        'key': 'MODEL_TOP_K',
        'type': 'entry',
        'toggle_key': 'USE_MODEL_TOP_K',
        'toggle_default': self.settings.get('USE_MODEL_TOP_K', True),
        'default': 0,
        'validation': self.validate_positive_integer_or_zero,
        'tooltip': _('Ограничивает выбор токенов K наиболее вероятными (0 = отключено)',
                    'Limits token selection to K most likely (0 = disabled)')},

        {'label': _('Top-P', 'Top-P'),
        'key': 'MODEL_TOP_P',
        'type': 'entry',
        'toggle_key': 'USE_MODEL_TOP_P',
        'toggle_default': self.settings.get('USE_MODEL_TOP_P', True),
        'default': 1.0,
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

        {'label': _('Вызов инструментов', 'Tools use'),
         'key': 'TOOLS_ON',
         'type': 'checkbutton',
         'default_checkbutton': False,
         'tooltip': _(
             'Позволяет использовать инструменты такие как поиск в сети',
             'Allow using tools like seacrh')},
        {'label': _("Режим инструментов","Tools mode"), 'key': 'TOOLS_MODE', 'type': 'combobox',
         'options': ["native", "legacy"], 'default': "native", "depends_on": "TOOLS_ON",
         'tooltip': _('Native - использует вшитые возможности модели, legacy - добавляет промпт и ловит вызов вручную',
                    'Native - using buit-in tools, legacy - using own prompts and handler')},

        {'type': 'end'},
    ]

    create_settings_section(
        self,
        parent,
        _("Параметры генерации", "Generation Parameters"),
        general_config,
        icon_name='fa5s.cogs'
    )

    event_bus = get_event_bus()
    presets_meta = event_bus.emit_and_wait(Events.ApiPresets.GET_PRESET_LIST, timeout=1.0)
    hc_provider_names = [_('Текущий', 'Current')]
    if presets_meta and presets_meta[0]:
        all_presets = presets_meta[0].get('custom', [])
        for preset in all_presets:
            hc_provider_names.append(preset.name)
    react_provider_names = [_('Текущий', 'Current')]
    if presets_meta and presets_meta[0]:
        all_presets = presets_meta[0].get('custom', [])
        for preset in all_presets:
            react_provider_names.append(preset.name)


    
    react_settings_config = [
        {
            'label': _('Использовать реакции (react)', 'Use react events'),
            'key': 'REACT_ENABLED',
            'type': 'checkbutton',
            'default_checkbutton': False,
            'tooltip': _(
                'Включить генерацию реакций на действия игрока (react-задачи). '
                'Отключение полностью блокирует вызовы модели для react.',
                'Enable generation of reactions to player actions (react tasks). '
                'Disabling completely blocks model calls for react.'
            )
        },
        {
            'label': _('Провайдер для реакций', 'Provider for react events'),
            'key': 'REACT_PROVIDER',
            'type': 'combobox',
            'options': react_provider_names,
            'default': _('Текущий', 'Current'),
            'depends_on': 'REACT_ENABLED',
            'tooltip': _(
                'Какой API-пресет использовать для react-сообщений. '
                '«Текущий» — использовать тот же пресет, что и основной чат.',
                'Which API preset to use for react messages. '
                '"Current" — use the same preset as the main chat.'
            )
        },
    ]

    create_settings_section(
        self,
        parent,
        _("Настройки реакций", "React settings"),
        react_settings_config
    )

    # ------------------------------------------------------------------
    # RAG & Memory settings (NEW)
    # ------------------------------------------------------------------
    rag_memory_config = [
        {'label': _('Лимит сообщений', 'Message limit'), 'key': 'MODEL_MESSAGE_LIMIT',
         'type': 'entry', 'default': 40,
         'tooltip': _('Сколько сообщений будет помнить мита', 'How much messages Mita will remember')},
        {'label': _('Лимит воспоминаний', 'Active memory limit (MEMORY_CAPACITY)'),
         'key': 'MEMORY_CAPACITY', 'type': 'entry', 'default': 75,
         'validation': self.validate_positive_integer,
         'tooltip': _(
             'Максимум активных воспоминаний (не удалённых и не забытых). При превышении система помечает одно как is_forgotten=1.',
             'Maximum number of active memories (not deleted and not forgotten). When exceeded, the system marks one as is_forgotten=1.')},

        {'type': 'end'},

        {'label': _('Сжатие истории', 'History compression'), 'type': 'subsection',
         'depends_on': 'RAG_ENABLED'},

        {'label': _('Сжимать историю при достижении лимита', 'Compress history on limit'),
         'key': 'ENABLE_HISTORY_COMPRESSION_ON_LIMIT', 'type': 'checkbutton',
         'default_checkbutton': False,
         'tooltip': _('Включить автоматическое сжатие истории чата, когда количество сообщений превышает лимит.',
                      'Enable automatic chat history compression when message count exceeds a limit.')},
        {'label': _('Периодическое сжатие истории', 'Periodic history compression'),
         'key': 'ENABLE_HISTORY_COMPRESSION_PERIODIC', 'type': 'checkbutton',
         'default_checkbutton': False,
         'tooltip': _('Включить автоматическое сжатие истории чата через заданные интервалы.',
                      'Enable automatic chat history compression at specified intervals.')},
        {'label': _('Интервал периодического сжатия (сообщения)', 'Periodic compression interval (messages)'),
         'key': 'HISTORY_COMPRESSION_PERIODIC_INTERVAL', 'type': 'entry',
         'default': 20, 'validation': self.validate_positive_integer,
         'tooltip': _('Количество сообщений, после которых будет произведено периодическое сжатие истории.',
                      'Number of messages after which periodic history compression will occur.')},
        {'label': _('Шаблон промпта для сжатия', 'Compression prompt template'),
         'key': 'HISTORY_COMPRESSION_PROMPT_TEMPLATE', 'type': 'entry',
         'default': "Prompts/System/compression_prompt.txt",
         'tooltip': _('Путь к файлу шаблона промпта, используемого для сжатия истории.',
                      'Path to the prompt template file used for history compression.')},
        {'label': _('Процент для сжатия', 'Percent to compress'),
         'key': 'HISTORY_COMPRESSION_MIN_PERCENT_TO_COMPRESS', 'type': 'entry',
         'default': 0.85, 'validation': self.validate_float_0_1,
         'tooltip': _('Минимальное количество сообщений в истории, необходимое для запуска процесса сжатия.',
                      'Minimum number of messages in history required to trigger compression.')},
        {'label': _('Цель вывода сжатой истории', 'Compressed history output target'),
         'key': 'HISTORY_COMPRESSION_OUTPUT_TARGET', 'type': 'combobox',
         'options': ['history', 'memory'],
         'default': "history",
         'tooltip': _('Куда помещать результат сжатия истории (например, "memory", "summary_message").',
                      'Where to place the compressed history output (e.g., "memory", "summary_message").')},
        {'label': _('Провайдер для сжатия', 'Provider for compression'),
         'key': 'HC_PROVIDER',
         'type': 'combobox',
         'options': hc_provider_names,
         'default': _('Текущий', 'Current')},


        {'label': _('RAG и память', 'RAG & Memory'), 'type': 'subsection'},

        {'label': _('Включить RAG (требует перезагрузки)', 'Enable RAG (requires restart)'),
           'key': 'RAG_ENABLED', 'type': 'checkbutton', 'default_checkbutton': False,
           'tooltip': _('Включает систему RAG. Если выключено, модель эмбеддингов не загружается.',
                         'Enables the RAG system. If disabled, the embedding model is not loaded.')},

        {'label': _('Искать в памяти', 'Search in memory'),
               'key': 'RAG_SEARCH_MEMORY', 'type': 'checkbutton', 'default_checkbutton': True,
               'depends_on': 'RAG_ENABLED'},

        {'label': _('Искать в истории', 'Search in history'),
         'key': 'RAG_SEARCH_HISTORY', 'type': 'checkbutton', 'default_checkbutton': False,
         'depends_on': 'RAG_ENABLED'},


        {'label': _('Макс. результатов RAG', 'RAG max results'),
         'key': 'RAG_MAX_RESULTS', 'type': 'entry', 'default': 8,
         'validation': self.validate_positive_integer,
         'tooltip': _('Сколько фрагментов RAG добавлять в system prompt.',
                      'How many RAG chunks to inject into the system prompt.'),
         'depends_on': 'RAG_ENABLED'},

        {'label': _('Порог схожести (Sim threshold)', 'Similarity threshold (Sim threshold)'),
         'key': 'RAG_SIM_THRESHOLD', 'type': 'entry', 'default': 0.40,
         'validation': self.validate_float_0_to_1,
         'tooltip': _('Минимальная косинусная схожесть для кандидата (0..1).',
                      'Minimum cosine similarity for a candidate (0..1).'),
         'depends_on': 'RAG_ENABLED'},

        {'label': _('Хвост сообщений для query (1-3)', 'Query tail messages (1-3)'),
         'key': 'RAG_QUERY_TAIL_MESSAGES', 'type': 'entry', 'default': 2,
         'validation': self.validate_positive_integer,
         'tooltip': _('Сколько последних активных сообщений (user/assistant) использовать для построения query-строки.',
                      'How many last active messages (user/assistant) to use when building the query string.'),
         'depends_on': 'RAG_ENABLED'},

        {'type': 'end'},

        {'label': _('Веса и затухание', 'Weights & decay'), 'type': 'subsection',
         'depends_on': 'RAG_ENABLED'},

        {'label': _('Вес схожести K1', 'Similarity weight K1'),
         'key': 'RAG_WEIGHT_SIMILARITY', 'type': 'entry', 'default': 1.0,
         'validation': self.validate_float_positive_or_zero,
         'depends_on': 'RAG_ENABLED'},

        {'label': _('Вес времени K2 (history)', 'Time weight K2 (history)'),
         'key': 'RAG_WEIGHT_TIME', 'type': 'entry', 'default': 1.0,
         'validation': self.validate_float_positive_or_zero,
         'depends_on': 'RAG_ENABLED'},

        {'label': _('Вес приоритета K3 (memories)', 'Priority weight K3 (memories)'),
         'key': 'RAG_WEIGHT_PRIORITY', 'type': 'entry', 'default': 1.0,
         'validation': self.validate_float_positive_or_zero,
         'depends_on': 'RAG_ENABLED'},

        {'label': _('Вес сущностей K4', 'Entity weight K4'),
         'key': 'RAG_WEIGHT_ENTITY', 'type': 'entry', 'default': 0.5,
         'validation': self.validate_float_positive_or_zero,
         'depends_on': 'RAG_ENABLED'},

        {'label': _('Скорость затухания (decay_rate)', 'Decay rate (decay_rate)'),
         'key': 'RAG_TIME_DECAY_RATE', 'type': 'entry', 'default': 0.15,
         'validation': self.validate_float_positive_or_zero,
         'tooltip': _('TimeFactor = 1/(1+decay_rate*days). Чем больше decay_rate, тем сильнее штраф старым сообщениям.',
                      'TimeFactor = 1/(1+decay_rate*days). Higher decay_rate penalizes older messages more.'),
         'depends_on': 'RAG_ENABLED'},

        {'label': _('Шум (serendipity) максимум', 'Noise (serendipity) max'),
         'key': 'RAG_NOISE_MAX', 'type': 'entry', 'default': 0.05,
         'validation': self.validate_float_0_to_1,
         'tooltip': _('Случайная добавка 0..NoiseMax для редких неожиданных совпадений.',
                      'Random bonus 0..NoiseMax for occasional unexpected matches.'),
         'depends_on': 'RAG_ENABLED'},

        {'type': 'end'},



        {'label': _("Поиск по ключевым словам", "Keyword Search"), 'type': 'subsection',
         'depends_on': 'RAG_ENABLED'},

        {'label': _('Включить поиск по ключевым словам', 'Enable keyword search'),
         'key': 'RAG_KEYWORD_SEARCH', 'type': 'checkbutton', 'default_checkbutton': False,
         'tooltip': _('Включает дополнительный поиск по ключевым словам в истории/памяти.',
                      'Enables additional keyword search in history/memory.')},

        {'label': _('Вес ключевых слов K5', 'Keyword weight K5'),
         'key': 'RAG_WEIGHT_KEYWORDS', 'type': 'entry', 'default': 0.6,
         'validation': self.validate_float_positive_or_zero,
         'depends_on': 'RAG_KEYWORD_SEARCH',
         'tooltip': _('Вес, с которым результат поиска по ключевым словам K5 будет влиять на финальный скоринг.',
                      'The weight (K5) with which the keyword search result will influence the final scoring.')},

        {'label': _('Макс. ключевых слов', 'Max keywords'),
         'key': 'RAG_KEYWORDS_MAX_TERMS', 'type': 'entry', 'default': 8,
         'validation': self.validate_positive_integer,
         'depends_on': 'RAG_KEYWORD_SEARCH',
         'tooltip': _('Максимальное количество ключевых слов, извлекаемых из запроса для поиска.',
                      'Maximum number of keywords extracted from the query for search.')},

        {'label': _('Мин. длина ключевого слова', 'Min keyword length'),
         'key': 'RAG_KEYWORDS_MIN_LEN', 'type': 'entry', 'default': 3,
         'validation': self.validate_positive_integer,
         'depends_on': 'RAG_KEYWORD_SEARCH',
         'tooltip': _('Минимальная длина ключевого слова для его включения в поиск.',
                      'Minimum length for a keyword to be included in the search.')},

        {'label': _('Мин. оценка совпадения', 'Min match score'),
         'key': 'RAG_KEYWORD_MIN_SCORE', 'type': 'entry', 'default': 0.34,
         'validation': self.validate_float_0_to_1,
         'depends_on': 'RAG_KEYWORD_SEARCH',
         'tooltip': _('Минимальная оценка (доля совпадений), необходимая для включения результата.',
                      'Minimum score (fraction of matches) required to include a result.')},

        {'label': _('SQL лимит поиска', 'SQL search limit'),
         'key': 'RAG_KEYWORD_SQL_LIMIT', 'type': 'entry', 'default': 250,
         'validation': self.validate_positive_integer,
         'depends_on': 'RAG_KEYWORD_SEARCH',
         'tooltip': _('Максимальное количество записей, которое запрашивается из базы данных по ключевым словам.',
                      'Maximum number of records requested from the database by keywords.')},





    ]


    create_settings_section(self, parent,
                           _("Настройки Памяти и RAG", "Memory & RAG Settings"),
                           rag_memory_config)


    token_settings_config = [
        {'label': _('Показывать информацию о токенах', 'Show Token Info'), 'key': 'SHOW_TOKEN_INFO',
         'type': 'checkbutton', 'default_checkbutton': True,
         'tooltip': _('Отображать количество токенов и ориентировочную стоимость в интерфейсе чата.',
                      'Display token count and approximate cost in the chat interface.')},
        {'label': _('Стоимость токена (вход, ₽)', 'Token Cost (input, ₽)'), 'key': 'TOKEN_COST_INPUT', 'depends_on': 'SHOW_TOKEN_INFO',
         'type': 'entry', 'default': 0.000001, 'validation': self.validate_float_positive_or_zero,
         'tooltip': _('Стоимость одного токена для входных данных (например, 0.000001 ₽ за токен).',
                      'Cost of one token for input data (e.g., 0.000001 ₽ per token).')},
        {'label': _('Стоимость токена (выход, ₽)', 'Token Cost (output, ₽)'), 'key': 'TOKEN_COST_OUTPUT', 'depends_on': 'SHOW_TOKEN_INFO',
         'type': 'entry', 'default': 0.000002, 'validation': self.validate_float_positive_or_zero,
         'tooltip': _('Стоимость одного токена для выходных данных (например, 0.000002 ₽ за токен).',
                      'Cost of one token for output data (e.g., 0.000002 ₽ per token).')},
        {'label': _('Максимальное количество токенов модели', 'Max Model Tokens'), 'key': 'MAX_MODEL_TOKENS', 'depends_on': 'SHOW_TOKEN_INFO',
         'type': 'entry', 'default': 32000, 'validation': self.validate_positive_integer,
         'tooltip': _('Максимальное количество токенов, которое может обработать модель.',
                      'Maximum number of tokens the model can process.')},
    ]

    create_settings_section(self, parent,
                           _("Настройки токенов", "Token Settings"),
                           token_settings_config)

    command_processing_config = [
        {'label': _('Использовать обработку команд', 'Use command processing'), 'key': 'USE_COMMAND_REPLACER',
         'type': 'checkbutton',
         'default_checkbutton': False, 'tooltip': _('Включает замену команд в ответе модели на основе схожести.',
                                                    'Enables replacing commands in the model response based on similarity.')},
        {'label': _('Мин. порог схожести', 'Min similarity threshold'), 'key': 'MIN_SIMILARITY_THRESHOLD',
         'type': 'entry', 
         'depends_on': 'USE_COMMAND_REPLACER', 'hide_when_disabled': True,
         'default': 0.40, 
         'validation': self.validate_float_0_to_1, 
         'tooltip': _('Минимальный порог схожести для замены команды (0.0-1.0).',
                      'Minimum similarity threshold for command replacement (0.0-1.0).')},
        {'label': _('Порог смены категории', 'Category switch threshold'), 'key': 'CATEGORY_SWITCH_THRESHOLD',
         'type': 'entry',
         'depends_on': 'USE_COMMAND_REPLACER', 'hide_when_disabled': True,
         'default': 0.18,
         'validation': self.validate_float_0_to_1, 
         'tooltip': _('Дополнительный порог для переключения на другую категорию команд (0.0-1.0).',
                      'Additional threshold for switching to a different command category (0.0-1.0).')},
        {'label': _('Пропускать параметры с запятой', 'Skip comma parameters'), 'key': 'SKIP_COMMA_PARAMETERS',
         'type': 'checkbutton', 
         'depends_on': 'USE_COMMAND_REPLACER', 'hide_when_disabled': True,
         'default_checkbutton': True, 
         'tooltip': _('Пропускать параметры, содержащие запятую, при замене.',
                                                   'Skip parameters containing commas during replacement.')},
    ]

    create_settings_section(self, parent,
                           _("Обработка команд", "Command Processing"),
                           command_processing_config)


