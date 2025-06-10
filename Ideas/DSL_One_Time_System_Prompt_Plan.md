# Подробный план реализации: Добавление разового системного промпта в DSL

**Цель:** Расширить DSL возможностью указывать разовый системный промпт, который будет отправляться в ChatModel при выполнении определенного условия, с максимальным разделением ответственности и упрощением логики в ChatModel.

**Изменение подхода:**
`DslInterpreter` будет накапливать временные системные сообщения. `Character` будет отвечать за сбор всех системных сообщений (основной промпт, временные сообщения из DSL, сообщения из системы памяти) и предоставление их `ChatModel` через единый метод.

**Предлагаемая новая команда DSL:**
`ADD_SYSTEM_INFO <выражение>`

Эта команда будет принимать выражение (строку или переменную), вычислять его и добавлять результат во внутренний список временных системных сообщений `DslInterpreter`.

**Пример использования в DSL:**
```dsl
IF some_condition THEN
    ADD_SYSTEM_INFO "Это разовое системное сообщение, отправленное при выполнении условия."
ENDIF

SET my_variable = "Динамическое значение"
ADD_SYSTEM_INFO f"Динамическое сообщение: {my_variable}"
```

**Шаги реализации:**

1.  **Модификация класса `DslInterpreter` (файл `DSL/dsl_engine.py`)**
    *   **Добавление атрибута для временных сообщений:**
        *   В конструкторе `__init__` добавить `self._temporary_system_messages: List[Dict] = []`.
    *   **Изменение обработки команды `ADD_SYSTEM_INFO` в `execute_dsl_script`:**
        *   В методе `execute_dsl_script`, добавить блок `elif` для `ADD_SYSTEM_INFO`.
        *   Логика будет следующей:
            *   Извлечь аргументы команды (`args`).
            *   Вычислить выражение, используя `_eval_expr` (с учетом `_expand_inline_loads`).
            *   Преобразовать результат в строку.
            *   Добавить сообщение в `self._temporary_system_messages`: `self._temporary_system_messages.append({"role": "system", "content": content_to_add})`.
            *   Добавить логирование для отладки.
    *   **Изменение возвращаемого значения `execute_dsl_script`:**
        *   Метод должен возвращать кортеж: `(сгенерированный_текст, список_временных_сообщений)`.
        *   В начале метода `execute_dsl_script` очищать `self._temporary_system_messages`.
        *   В конце метода, перед `return returned or ""`, добавить `return (returned or "", self._temporary_system_messages.copy())`.
    *   **Изменение возвращаемого значения `process_main_template_file`:**
        *   Этот метод также должен возвращать кортеж `(сгенерированный_текст, список_временных_сообщений)`.
        *   В начале метода `process_main_template_file` очищать `self._temporary_system_messages`.
        *   В конце метода, перед `return final_prompt`, добавить `return (final_prompt, self._temporary_system_messages.copy())`.
    *   **Изменение возвращаемого значения `process_file`:**
        *   Аналогично, этот метод должен возвращать кортеж `(сгенерированный_текст, список_временных_сообщений)`.
        *   В начале метода `process_file` очищать `self._temporary_system_messages`.
        *   В конце метода, перед `return content`, добавить `return (content, self._temporary_system_messages.copy())`.

2.  **Модификация класса `Character` (файл `character.py`)**
    *   **Удаление `get_llm_system_prompt_string`:** Этот метод больше не нужен, его логика будет интегрирована.
    *   **Модификация `get_full_system_setup_for_llm`:**
        *   Переименовать `get_full_system_setup_for_llm` в `get_all_system_messages_for_llm` (или аналогичное, более точное название).
        *   Этот метод будет отвечать за сбор всех системных сообщений.
        *   Внутри этого метода:
            *   Установить `SYSTEM_DATETIME`.
            *   Вызвать `main_prompt_content, dsl_temp_messages = self.dsl_interpreter.process_main_template_file(self.main_template_path_relative)`.
            *   Создать список `messages`.
            *   Если `main_prompt_content` не пуст, добавить его как системное сообщение.
            *   Если `dsl_temp_messages` не пуст, добавить их в список `messages`.
            *   Получить сообщения из `self.memory_system.get_memories_formatted()` и добавить их.
            *   Вернуть полный список `messages`.

3.  **Модификация класса `ChatModel` (файл `chat_model.py`)**
    *   **Упрощение `generate_response`:**
        *   В разделе "4. Системные промпты / память", полностью заменить логику загрузки системных промптов на вызов нового метода `Character`.
        *   Удалить `self.infos_to_add_to_history.clear()` после добавления, так как теперь `Character` будет отвечать за это.
        *   `self.infos_to_add_to_history` в `ChatModel` будет использоваться только для сообщений, которые добавляются *вне* DSL (например, из GUI или других модулей).

**Диаграмма потока данных (финальная):**

```mermaid
graph TD
    A[ChatModel.generate_response] --> B{Character.get_all_system_messages_for_llm};
    B --> C[Character.dsl_interpreter.process_main_template_file];
    C -- Returns (main_text, temp_messages) --> B;
    B -- Combines main_text, temp_messages, memory_messages --> A;
    A -- Adds ChatModel.infos_to_add_to_history (if any) --> H[Combined messages for LLM];
    H --> I[LLM API Call];

    subgraph DslInterpreter
        D_init[DslInterpreter.__init__] --> D_temp_list[self._temporary_system_messages];
        D_exec[DslInterpreter.execute_dsl_script] --> D_temp_list;
        D_proc_main[DslInterpreter.process_main_template_file] --> D_temp_list;
        D_proc_file[DslInterpreter.process_file] --> D_temp_list;
        D_exec -- ADD_SYSTEM_INFO --> D_temp_list;
    end