# План по улучшению сжатия истории диалога

## 1. Цель
Улучшить функцию `process_history_compression` в файле [`chat_model.py`](chat_model.py), чтобы она учитывала время сообщений и отправителя (персонажа или игрока) при сжатии истории. Также улучшить и перевести на английский язык промт сжатия, который находится в файле [`Prompts/System/compression_prompt.txt`](Prompts/System/compression_prompt.txt).

## 2. Текущая ситуация
*   Функция `process_history_compression` в [`chat_model.py`](chat_model.py) использует `_compress_history` для сжатия.
*   `_compress_history` загружает промт из [`Prompts/System/compression_prompt.txt`](Prompts/System/compression_prompt.txt).
*   Сообщения для сжатия форматируются как `"{role}: {content}"`.
*   В истории сообщений уже есть поле `"time"`, а роль (`"user"`, `"assistant"`, `"system"`) указывает на отправителя.

## 3. Предложения по улучшению промта сжатия (на английском)

### 3.1. Общие улучшения:
*   **Четкое указание формата ввода:** Явно указать, что каждое сообщение в истории будет иметь префикс с отметкой времени (если доступно) и ролью/именем отправителя.
*   **Краткость и ключевая информация:** Подчеркнуть необходимость создания краткой сводки, которая улавливает основную сюжетную линию, значимые события, принятые решения и любые заметные изменения в отношениях или состоянии персонажей.
*   **Фокус на персонажах:** Проинструктировать модель идентифицировать персонажей и ссылаться на них по именам, выделяя их действия и развивающиеся роли.
*   **Отсутствие вымысла:** Четко указать, что сводка должна содержать только информацию, присутствующую в предоставленной истории, избегая любого нового или спекулятивного контента.
*   **Структура вывода:** Предложить предпочтительный формат вывода для сводки (например, связный абзац или маркированный список ключевых моментов).
*   **Язык:** Полностью перевести промт на английский язык.

### 3.2. Пример нового формата сообщения для промта:
Вместо:
```
user: Привет, как дела?
assistant: Отлично, а у тебя?
```
Будет:
```
[13:00] [Player]: Hello, how are you?
[13:01] [Mita]: I'm great, how about you?
```

## 4. Детальный план по изменению кода

### 4.1. Модификация `_compress_history` в [`chat_model.py`](chat_model.py):
*   Изменить строку 1115, чтобы она включала время и отправителя в форматированные сообщения.
    *   Если у сообщения есть поле `"time"`, использовать его.
    *   Определить отправителя:
        *   Если `role` - `"user"`, отправитель будет "Player".
        *   Если `role` - `"assistant"`, отправитель будет `self.current_character.name`.
        *   Если `role` - `"system"`, отправитель будет "System".
    *   Формат будет `"[HH:MM] [Sender]: Content"` или `"[Sender]: Content"` если время отсутствует.
*   В промт сжатия будет передаваться имя текущего персонажа, чтобы модель могла его использовать.

### 4.2. Обновление [`Prompts/System/compression_prompt.txt`](Prompts/System/compression_prompt.txt):
*   Перевести весь промт на английский язык.
*   Включить инструкции, отражающие предложенные улучшения, особенно касающиеся нового формата ввода сообщений.
*   Добавить плейсхолдер для имени текущего персонажа, например, `{current_character_name}`, и проинструктировать модель использовать его для идентификации своих собственных сообщений.

### 4.3. Визуализация изменений в `_compress_history` (обновленная):

```mermaid
graph TD
    A[Начало _compress_history] --> B{Для каждого сообщения в messages_to_compress};
    B --> C{Проверить наличие 'time' и 'role'};
    C --> D{Определить отправителя (Sender) на основе role:};
    D -- role == "user" --> D1[Sender = "Player"];
    D -- role == "assistant" --> D2[Sender = self.current_character.name];
    D -- role == "system" --> D3[Sender = "System"];
    D1 --> E;
    D2 --> E;
    D3 --> E;
    E[Сформировать строку сообщения: "[HH:MM] [Sender]: Content" или "[Sender]: Content"];
    E --> F[Добавить сформированную строку в список formatted_messages];
    F --> B;
    B -- Все сообщения обработаны --> G[Объединить formatted_messages в одну строку];
    G --> H[Загрузить prompt_template];
    H --> I[Заменить {history_messages} и {current_character_name} на соответствующие значения];
    I --> J[Вызвать LLM];
    J --> K[Возврат сжатой сводки];
```

### 4.4. Пример нового промта (после перевода и доработки с учетом имени персонажа):

```
You are an assistant tasked with summarizing dialogue history. Your goal is to read the provided message history and create a concise, coherent summary that captures key events, facts, decisions, and changes in character relationships or states. Refer to characters by their names. The summary should be as brief as possible while remaining informative. Avoid unnecessary details and repetitions.

Your own messages in the history will be attributed to "{current_character_name}". Messages from the user will be attributed to "Player". System messages will be attributed to "System".

Each message in the history will be formatted as follows: "[HH:MM] [Sender]: Message Content" or "[Sender]: Message Content" if the timestamp is not available. Focus on extracting the most critical information that would be essential for understanding the ongoing narrative and character development. Do not invent any information not present in the original history.

History to compress:
<HISTORY>
{history_messages}
</HISTORY>