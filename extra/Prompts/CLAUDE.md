# extra/Prompts — CLAUDE.md

## Важно
- `extra/Prompts/` — шаблоны, идут в **git**. Менять нужно здесь.
- `Prompts/` (в корне проекта) — применяется игрой, в **`.gitignore`**, не трогать.
  Пользователь сам копирует из `extra/Prompts/` в `Prompts/`.

---

## Персонажи

| Папка        | Варианты промптов                        |
|--------------|------------------------------------------|
| `Crazy/`     | `Default/`, `Lite/`, `By_mactep_kot_new_mini/` |
| `Creepy/`    | `Default/`, ...                      |
| `Kind/`      | `Default/`, `Lite/`              |
| `Cappie/`    | `Default/`                           |
| `Ghost/`     | `Default/`                           |
| `Mila/`      | `Default/`                           |
| `ShortHair/` | `Default/`                           |
| `Sleepy/`    | `Default/`                           |
| `GameMaster/`| `Default/`      |

Общие ресурсы: `Common/`, `System/`, `Structural/`

---

## Форматы промптов

- `Default/` — JSON structured output (актуальный формат)
- `Lite/` — облегчённая версия Default
- `By_mactep_kot_new_mini/` — кастомный вариант (Crazy)

---

## Структура внутри `<Character>/<Variant>/`

```
Main/           — основные текстовые блоки (main.txt, common.txt, ...)
Scripts/        — .script файлы (Init_variables, event_handler, ...)
Context/        — примеры диалогов, история (examples.script, mita_history.txt)
States/         — состояния персонажа (hello.txt, ...)
Events/         — особые события (SecretExposed.txt у Crazy/Creepy)
PostScripts/    — постскрипты (main_rules.postscript)
System/         — system-промпты (participants_dialogue.system)
Structural/     — схема JSON-ответа и маппинг тегов:
  response_structure.txt   — JSON Schema для LLM (эталон: Crazy/Default/Structural/)
  VariablesEffects.txt     — маппинг тегов → JSON поля (FORMAT NOTE в начале)
config.json     — конфиг персонажа/варианта
```

---

## Расширения файлов

| Расширение    | Назначение                              |
|---------------|-----------------------------------------|
| `.txt`        | Текстовый блок промпта                  |
| `.script`     | Скрипт (подстановка переменных и т.п.)  |
| `.system`     | System-промпт                           |
| `.postscript` | Постскрипт (добавляется в конец)        |

---

## Глобальные ресурсы

- `Structural/response_format_json.txt` — глобальная инструкция формата JSON (для всех персонажей)
- `Common/` — общие файлы (Dialogue.txt, Security.txt, chess/seabattle хэндлеры)
- `System/compression_prompt.txt` — промпт сжатия памяти
