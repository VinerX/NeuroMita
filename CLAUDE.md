# Claude Code — Project Notes (NeuroMita)

Карта проекта для агентов. Цель — быстро понять, где что лежит и как не сломать.
Комментарии в коде и общение — на русском (проект русскоязычный).

---

## Что это за проект

**NeuroMita** — десктоп-приложение (PyQt6), которое даёт персонажам игры *Miside* ("Миты")
живой разум на базе LLM: озвучка, эмоции, анимации, память, RAG. Состоит из двух частей:

1. **Python backend** (эта репа, `C:\Games\NeuroMita\NeuroMita\`) — GUI, LLM-пайплайн,
   голос (TTS/RVC/F5), ASR, RAG-память, сервер для связи с игрой.
2. **Unity C# мод** (`C:\Games\NeuroMita\NeuroMita-Unity\` — **отдельная репа!**) —
   ставится в игру, по TCP получает от Python структурированный ответ и применяет его
   (реплики, анимации, свет, движение). C# в `MitaAiC#/` и `extra/` этой репы **устарел
   на ~год — не использовать как источник правды.**

Связь: Python поднимает TCP-сервер `127.0.0.1:12345` (`src/game_connections/server.py`),
мод-клиент шлёт запросы (диалог, idle-события, музыка), Python отвечает JSON-ответом Миты.

---

## Окружение Python — ДВА разных интерпретатора

**Venv с torch/transformers/CUDA — для разработки и ML-тестов:**
```
C:\Games\NeuroMita\Venv\Scripts\python.exe
```
- torch 2.7.1+cu128 (CUDA), transformers 5.3.0
- Использовать для всех тестов RAG (embedding, cross-encoder, Optuna) и pytest.

**libs/python (встроенный Python игры) — только для запуска самой игры:**
```
C:\Games\NeuroMita\NeuroMita\libs\python\python.exe
```
- НЕ имеет torch/transformers — RAG работает только в FTS/keyword-режиме.
- Не использовать для ML-тестов.

`src/__main__.py` на старте патчит кучу библиотек в `libs/` (triton, fairseq, tts_with_rvc)
и делает ранний torch CUDA-bootstrap — это нормально, не пугаться.

---

## Промпты — extra/Prompts (git) vs Prompts (runtime)

**Правило: править только `extra/Prompts/`, НЕ `Prompts/`.**
- `extra/Prompts/` — идёт в git, шаблоны для промптеров. Пользователь сам копирует в `Prompts/`.
- `Prompts/` — то, что реально применяет игра; не в git; **не трогать напрямую.**

Структура `extra/Prompts/`:
- `Common/` — общие файлы (graph_extraction_prompt.txt и т.п.)
- `System/` — системные (compression_prompt.txt, participants_dialogue.system)
- `Structural/` — глобальные структурные (response_format_json.txt)
- `<CharName>/Default/` — основной формат, содержит JSON structured-output
  (`response_structure.txt` = схема, `VariablesEffects.txt` = маппинг тег→JSON)

Цепочка загрузки промпта (приоритет): персональный `Structural/<file>` → `Prompts/Common/<file>`
→ хардкод-дефолт в Python.

Эталон structured-формата: `extra/Prompts/Crazy/Default/Structural/response_structure.txt`.

---

## Карта кода (`src/`)

Точка входа: `src/__main__.py` → `MainController` (`controllers/main_controller.py`) +
`MainWindow` (`ui/windows/main_window.py`). Запуск разработческий — `launch.py`
(собирает fast-билд через `build.py`, ставит зависимости, запускает `.pyz`).

### Архитектура: типизированные сервисы + EventBus для уведомлений

**Главное правило: запрос/ответ — через сервис, событие — только уведомление.**

- **`core/services.py`** — `ServiceRegistry` (`services()`, `use(Contract)`). У каждого сервиса
  один владелец, который регистрирует его в композиционном корне (`MainController`).
  Отсутствующий сервис → `ServiceNotRegistered`, а не молчаливый дефолт.
- **`services/contracts.py`** — контракты (ABC) + типы запросов/результатов:
  `SettingsService`, `AppVarsService`, `CharacterRegistry`, `LoopService`, `GameLinkService`,
  `HistoryService`, `PromptBuilderService`, `GenerationService`.
- **`core/executors.py`** — именованные пулы: `GENERATION` (пользовательские генерации,
  с backpressure), `BACKGROUND_LLM` (сжатие истории + graph extraction, concurrency=1),
  `LLM_HTTP`, `IO`, `DB_WRITER`, `EVENT_BUS`, `EVENT_BUS_SYNC`.
  Новые `threading.Thread`/`ThreadPoolExecutor` по месту заводить нельзя.
- **`core/events.py`** — `EventBus` только для notification-событий (`ON_*`, `GUI.*`, `*_CHANGED`,
  `MESSAGE_COMPLETED`). **Новые `GET_*`-события заводить нельзя — заведите сервис.**
  `emit_and_wait` остался для «многие подписчики отвечают», не для вызова сервисов.

Путь одного сообщения (весь — синхронный, в пуле `GENERATION`, без asyncio и без шины):
`Chat.SEND_MESSAGE` → `ChatController._run_request` → `GenerationService.generate_chat`
→ RAG → `PromptBuilderService.build` → `HistoryService.prepare_for_prompt` → LLM →
запись истории → `History.MESSAGE_COMPLETED` (уведомление) → фон: сжатие/граф/эмбеддинги.

`HistoryService.prepare_for_prompt` — **чистое чтение**: LLM-вызовов там быть не должно,
сжатие живёт только в фоне. Окно контекста ограничено всегда.

- **`controllers/`** — оркестрация. `MainController` — композиционный корень: регистрирует
  инфраструктурные сервисы в порядке зависимостей, затем создаёт ~25 под-контроллеров:
  - `model_controller.py` — ядро LLM-пайплайна: маршрутизация structured vs legacy,
    сборка контекста, история, токен-статистика, извлечение reasoning.
  - `chat_controller.py` / `handlers/chat_handler.py` (`ChatModel`) — собственно генерация
    ответа, сборка `LLMRequest`, очистка ответа, хук сбора finetune-данных.
  - `prompt_controller.py` — подстановка промптов (в т.ч. условный JSON-промпт).
  - `character_controller.py`, `history_controller.py`, `settings_controller.py`,
    `graph_controller.py` (RAG-граф), `embedding_controller.py`, `voice_model_controller.py`,
    `speech_controller.py` (ASR), `audio_controller.py`, `telegram_controller.py`,
    `server_controller.py` (TCP-сервер игры), `installable_controller.py` (AI Hub компоненты).
- **`managers/`** — бизнес-логика/состояние: `character_manager.py`, `history_manager.py`,
  `database_manager.py` (SQLite), `memory_manager.py`, `dsl_manager.py`,
  `finetune_collector.py`, `provider_manager.py`, `model_pricing_manager.py`,
  `rag/` (RAG-подсистема, см. ниже).
- **`handlers/`** — внешние интеграции:
  - `llm_providers/` — провайдеры LLM: `openai_compatible.py`/`openai_http_base.py`,
    `gemini_provider.py`, `g4f_provider.py`, `common_provider.py` + `param_mapper.py`,
    `message_transforms.py`. Тут response_format/responseSchema для structured output.
  - `embedding_providers/` — провайдеры эмбеддингов (local HF, Gemini, OpenAI-compat) —
    аналог LLM-провайдеров.
  - `asr_handler.py` (распознавание речи), `audio_handler.py`, `local_voice_handler.py`
    (TTS/RVC), `image_description_handler.py`, `telegram_handler.py`, `ai_engine/`
    (отдельный engine-процесс + RAG-runtime).
- **`characters/`** — `character.py` (базовый `Character`: `process_response_nlp_commands`,
  `process_structured_response`, загрузка промптов, переменные attitude/boredom/stress) и
  `__init__.py` (конкретные: CrazyMita, KindMita, ShortHairMita, GhostMita, Cappie, MilaMita,
  CreepyMita, SleepyMita, GameMaster). Секрет-механика (`secret_exposed`) — у Crazy/Creepy.
- **`schemas/structured_response.py`** — Pydantic-модели JSON-ответа Миты
  (`StructuredResponse`, `ResponseSegment`). `utils/structured_response_parser.py` — парсер/конвертер.
- **`game_connections/`** — связь с Unity-модом: `server.py` (`ChatServerNew`, TCP/JSON),
  `handlers/actions/` (create_task, get_music_beats, get_settings, get_task_status),
  `services/beat_*` (анализ битов музыки).
- **`ui/`** — PyQt6: `windows/` (main_window, ai_hub), `chat/` (chat_widget, message_widget,
  message_renderer, structured_panel), `settings/`, `widgets/`, `dialogs/`, `pages/`.
- **`DSL/`** — `dsl_engine.py` / `post_dsl_engine.py` / `path_resolver.py`: мини-DSL для
  динамической логики в промптах персонажей (условия, переменные).
- **`installables/` + `core/installables/`** — компоненты AI Hub, скачиваемые «аля ffmpeg»
  (ffmpeg, голоса Мит). Паттерн: `status()` + `build_install_plan()` → `InstallAction`.
- **`presets/`** — встроенные пресеты API (`api_presets.py`, `api_protocols.py`,
  `api_templates.py`) и эмбеддингов (`embedding_provider_presets.py`).
- **`modules/`** — мини-игры с Митой (Chess, SeaBattle). **`connetors/hoi4/`** — интеграция с HOI4.
- **`updater.py`** — автообновление (Python + Unity-мод). Exit code 42 = «применено обновление,
  нужен рестарт» (см. `launch.py`).

### RAG-подсистема (`managers/rag/`)
- `rag_manager.py` — оркестратор: эмбеддинги (через провайдер), FTS/keyword, cross-encoder реранк.
- `graph/` — граф-память (извлечение сущностей/связей из диалога).
- `pipeline/`, `rag_utils.py`, `stopwords/`.
- `db_model_key` = `provider:model` (для не-local) или голый `hf_name` (local) — ключ
  совместимости старых векторов в БД. Настройка пресета: `RAG_EMBED_PRESET_ID`.

### Сбор данных для дообучения
- `managers/finetune_collector.py` (синглтон) — `FineTuneData/samples_YYYYMM.jsonl`,
  один запрос-ответ на строку. Экспорт ShareGPT/ChatML для Unsloth.
- Хук в `handlers/chat_handler.py::_generate_chat_response()`; 👍/👎 в `ui/chat/message_widget.py`.
- При добавлении полей в `LLMRequest` — проверить, не нужно ли захватить их в `save_sample()`.

---

## Структурированный ответ (structured output)

Текущий формат ответа Миты — сегментный JSON (миграция с legacy тег-формата, issue #58):
```json
{
  "reasoning": "...",            // optional, не видно игроку
  "attitude_change": 0, "boredom_change": 0, "stress_change": 0,
  "secret_exposed": true,        // optional, только Crazy/Creepy
  "memory_add": [], "memory_update": [], "memory_delete": [],
  "segments": [
    { "text": "...", "emotions": [], "animations": [], "idle_animations": [],
      "face_params": [], "commands": [] }   // commands: префиксы light:* music:* eye:*
  ]
}
```
Поток: provider → `model_controller` (маршрутизация) → `character.process_structured_response()`
→ TCP → Unity мод применяет посегментно. Persistent-прогресс/нюансы — в auto-memory
`structured_output_progress.md`.

---

## RAG Tester

```
src/utils/Testing/rag_tester/
```
Запуск (только Venv-python):
```bash
cd src/utils/Testing/rag_tester
"C:/Games/NeuroMita/Venv/Scripts/python.exe" rag_tester_cli.py run ...
```
Прогресс Optuna: `src/utils/Testing/rag_tester/results/optuna_progress.json`.

---

## Git / процесс

- Активная ветка обычно `releases` или `main`. **Не пушить и не мержить в `main` напрямую —
  только через PR с явного согласия пользователя.** На GitHub вообще не пушить без явной просьбы
  (пользователь предпочитает локальный мерж).
- Билд: `build.py` (+ `build.env`, пример `build.env.example`); CI: `.github/workflows/release.yml`;
  релизные скрипты в `scripts/` (`validate_release_contract.py`, `bootstrap_release_runtime.py`).
- Версия: `src/_version.py`.

## Прочие заметки

- Логи: `NeuroMitaLogs.log` (бывает огромным), логгер — `src/main_logger.py` (`logger`).
- Голоса Мит (~3.4 ГБ) вынесены из поставки — качаются через AI Hub (GitHub prerelease
  `voice-assets`). Папка `Models/`, путь через `NEUROMITA_MODELS_DIR`.
- Документация для людей — `docs/` в корне (RAG_Guide.md, LocalVoiceInstallation*.md и др.).
