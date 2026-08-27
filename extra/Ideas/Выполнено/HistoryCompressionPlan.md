# План реализации функции сжатия истории чата

## Цель

Внедрить функцию сжатия старых сообщений истории чата с использованием LLM для сохранения контекста и оптимизации использования токенов.

## Оценка эффективности

Добавление функции сжатия истории будет **очень эффектным** по следующим причинам:

1.  **Экономия токенов и снижение стоимости:** Текущая система просто отбрасывает старые сообщения. Сжатие позволит сохранить суть этих сообщений в компактном виде, значительно уменьшая количество токенов, отправляемых в LLM, и снижая затраты на API.
2.  **Увеличение "длины памяти" LLM:** Даже с большими контекстными окнами, история может быстро заполнять контекст. Сжатие позволит LLM "помнить" гораздо более длительный период времени, не превышая лимиты токенов, что улучшит связность диалога и позволит персонажу учитывать более ранние события.
3.  **Улучшение релевантности контекста:** Вместо обрезки старых сообщений, сжатие позволит выделить наиболее важную информацию и представить её LLM в виде краткой сводки, помогая LLM лучше понять общий контекст и избежать повторений.
4.  **Гибкость:** Можно настроить частоту сжатия, объем истории для сжатия и даже использовать разные модели для этой задачи.

## Основные компоненты, которые будут затронуты

*   [`chat_model.py`](chat_model.py): Основная логика определения, когда и что сжимать, вызов LLM для сжатия, интеграция с `HistoryManager` и `MemorySystem`.
*   [`HistoryManager.py`](HistoryManager.py): Возможно, потребуется новый метод для получения "сжимаемой" части истории и добавления сводки обратно в историю.
*   [`MemorySystem.py`](MemorySystem.py): Добавление нового типа памяти для хранения сжатых сводок.
*   `SettingsManager.py` (не был предоставлен, но подразумевается): Добавление новых настроек для управления функцией сжатия.
*   `character.py`: Обновление `get_full_system_setup_for_llm` для включения сжатой истории в системный промпт.

## Подробный план

1.  **Добавление настроек в `SettingsManager` (предполагается):**
    *   `ENABLE_HISTORY_COMPRESSION_ON_LIMIT`: Булево, включает сжатие, когда история превышает `memory_limit`. (По умолчанию `False`)
    *   `ENABLE_HISTORY_COMPRESSION_PERIODIC`: Булево, включает периодическое сжатие. (По умолчанию `False`)
    *   `HISTORY_COMPRESSION_PERIODIC_INTERVAL`: Целое число, количество сообщений между периодическими сжатиями. (По умолчанию `20`)
    *   `HISTORY_COMPRESSION_PROMPT_TEMPLATE`: Строка, путь к файлу промпта для сжатия. (По умолчанию `Prompts/System/compression_prompt.txt`)
    *   `HISTORY_COMPRESSION_MIN_MESSAGES_TO_COMPRESS`: Целое число, минимальное количество сообщений, которое должно быть для сжатия. (По умолчанию `10`)
    *   `HISTORY_COMPRESSION_OUTPUT_TARGET`: Строка, определяет куда помещать сводку ("memory" или "reduced_history"). (По умолчанию "memory")

2.  **Создание файла промпта для сжатия:**
    *   Создать файл `Prompts/System/compression_prompt.txt` с инструкциями для LLM по сжатию истории. Пример содержания:
        ```
        Ты - помощник, который сжимает историю диалога. Твоя задача - прочитать предоставленную историю сообщений и создать краткую, связную сводку, которая сохраняет ключевые события, факты, решения и изменения в отношениях или состоянии персонажей. Сводка должна быть максимально лаконичной, но при этом содержательной. Избегай излишних деталей и повторений.

        История для сжатия:
        <HISTORY>
        {history_messages}
        </HISTORY>

        Сводка:
        ```

3.  **Модификация [`HistoryManager.py`](HistoryManager.py):**
    *   Добавить метод `get_messages_for_compression(self, num_messages: int) -> List[Dict]`, который будет возвращать `num_messages` самых старых сообщений из истории, предназначенных для сжатия, и удалять их из основной истории.
    *   Добавить метод `add_summarized_history_to_messages(self, summary_message: Dict)` для добавления сжатой сводки обратно в список сообщений истории (если `HISTORY_COMPRESSION_OUTPUT_TARGET` = "reduced_history").

4.  **Модификация [`MemorySystem.py`](MemorySystem.py):**
    *   В `add_memory` добавить возможность указывать тип памяти (например, "fact", "summary").
    *   В `get_memories_formatted` добавить логику для форматирования сжатых сводок, чтобы они были представлены LLM как часть долгосрочной памяти.

5.  **Модификация [`chat_model.py`](chat_model.py):**
    *   **Инициализация:** Загрузить новые настройки из `self.gui.settings`.
    *   **Метод `_compress_history(self, messages_to_compress: List[Dict]) -> Optional[str]`:**
        *   Принимает список сообщений для сжатия.
        *   Загружает промпт из `HISTORY_COMPRESSION_PROMPT_TEMPLATE`.
        *   Форматирует сообщения для промпта.
        *   Вызывает `self._generate_chat_response` (или аналогичный метод) для получения сжатой сводки.
        *   Возвращает сжатый текст или `None` в случае ошибки.
    *   **Изменение в `generate_response` (или новый метод `_manage_history_compression`):**
        *   **Логика сжатия по лимиту:**
            *   После загрузки `llm_messages_history` (строка 252) и перед применением `memory_limit` (строка 415).
            *   Если `ENABLE_HISTORY_COMPRESSION_ON_LIMIT` включен и `len(llm_messages_history)` значительно больше `self.memory_limit` + `HISTORY_COMPRESSION_MIN_MESSAGES_TO_COMPRESS`:
                *   Определить `messages_to_compress` (например, `llm_messages_history[:-self.memory_limit]`).
                *   Вызвать `_compress_history` для этих сообщений.
                *   Если сжатие успешно:
                    *   Если `HISTORY_COMPRESSION_OUTPUT_TARGET` == "memory", добавить результат в `MemorySystem` через `self.current_character.memory_system.add_memory` с соответствующим типом/приоритетом.
                    *   Если `HISTORY_COMPRESSION_OUTPUT_TARGET` == "reduced_history", создать новое сообщение с ролью "system" или "user" (обсудить роль) и содержимым сводки, и добавить его в начало `llm_messages_history_limited` или использовать новый метод в `HistoryManager` для добавления в файл истории.
                *   Удалить сжатые сообщения из `llm_messages_history` (или получить новую ограниченную историю из `HistoryManager`).
        *   **Логика периодического сжатия:**
            *   Добавить счетчик сообщений с момента последнего сжатия.
            *   Если `ENABLE_HISTORY_COMPRESSION_PERIODIC` включен и счетчик достиг `HISTORY_COMPRESSION_PERIODIC_INTERVAL`:
                *   Определить `messages_to_compress` (например, последние `HISTORY_COMPRESSION_PERIODIC_INTERVAL` сообщений, или более сложная логика).
                *   Вызвать `_compress_history`.
                *   Если сжатие успешно, добавить результат в `MemorySystem` или `reduced_history` в зависимости от `HISTORY_COMPRESSION_OUTPUT_TARGET`.
                *   Сбросить счетчик.
    *   **Обновление `get_current_context_token_count`:** Убедиться, что токены сжатой истории, добавленные в `MemorySystem` или `reduced_history`, корректно учитываются.

6.  **Модификация [`character.py`](character.py):**
    *   В `get_full_system_setup_for_llm` (строки 164-176): Убедиться, что `self.memory_system.get_memories_formatted()` включает в себя сжатые сводки, если `HISTORY_COMPRESSION_OUTPUT_TARGET` == "memory". Если `HISTORY_COMPRESSION_OUTPUT_TARGET` == "reduced_history", сжатая сводка будет частью обычной истории сообщений.

## Диаграмма потока данных

```mermaid
graph TD
    A[Пользовательский ввод] --> B(ChatModel.generate_response)
    B --> C{Загрузка истории из HistoryManager}
    C --> D{Проверка настроек сжатия}
    D -- ENABLE_HISTORY_COMPRESSION_ON_LIMIT --> E{История > Лимит + Мин. сообщений для сжатия?}
    E -- Да --> F[Выделение старых сообщений для сжатия]
    F --> G(ChatModel._compress_history)
    G --> H{Вызов LLM для сжатия}
    H -- Сжатая сводка --> I{Куда сохранить сводку? (HISTORY_COMPRESSION_OUTPUT_TARGET)}
    I -- "memory" --> J(MemorySystem.add_memory)
    I -- "reduced_history" --> K(HistoryManager.add_summarized_history_to_messages)
    J --> L{Удаление сжатых сообщений из истории}
    K --> L
    L --> M{Формирование combined_messages}
    D -- ENABLE_HISTORY_COMPRESSION_PERIODIC --> N{Счетчик сообщений достиг интервала?}
    N -- Да --> O[Выделение сообщений для периодического сжатия]
    O --> G
    M --> P{Добавление MemorySystem.get_memories_formatted() в combined_messages (если target="memory")}
    P --> Q(Отправка combined_messages в LLM)
    Q --> R[Получение ответа LLM]
    R --> S[Сохранение новой истории в HistoryManager]
    S --> T[Возврат ответа пользователю]