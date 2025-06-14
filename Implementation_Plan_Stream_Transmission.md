# План реализации стриминговой передачи

1.  **Добавить настройку в GUI:**
    *   Определить, в каком файле GUI находятся общие настройки моделей. Скорее всего, это `ui/settings/chat_settings.py` или `ui/settings/api_settings.py`.
    *   Добавить в этот файл чекбокс с названием "Включить стриминговую передачу".
    *   Сохранить значение этого чекбокса в `SettingsManager.py`.
2.  **Изменить `chat_model.py`:**
    *   В конструкторе `ChatModel` получить значение настройки "Включить стриминговую передачу" из `SettingsManager.py`.
    *   В методе `generate_response` в зависимости от значения этой настройки вызывать либо обычный, либо стриминговый режим генерации ответа.
3.  **Реализовать стриминг в `_generate_openapi_response`:**
    *   Добавить параметр `stream=True` при вызове `target_client.chat.completions.create()`.
    *   Итерироваться по ответу API, используя `response.iter_content()` или `response.iter_lines()`.
    *   Для каждого полученного фрагмента текста вызывать метод GUI для добавления текста в чат.
4.  **Вызывать метод GUI для добавления текста:**
    *   Определить, какой метод в GUI отвечает за добавление текста в чат. Скорее всего, это метод в `ChatGUI` или в каком-то элементе управления чатом.
    *   В стриминговом режиме `chat_model.py` вызывать этот метод для каждого полученного фрагмента текста.