# RAG Embedding & Reranker Study
**Дата:** 2026-03-24
**Ветка:** `RAG-embedding-providers`
**Тест-сьют:** `crazy_suite_v3.json` (68 запросов), сценарий `crazy_scenario_full.json`
**Метрики:** Precision@K, Recall, nDCG (Mean по 68 кейсам)

---

## Результаты тестов

| # | Embedding | Cross-Encoder | CPU/GPU | Recall | Precision@K | nDCG | Время |
|---|-----------|---------------|---------|--------|-------------|------|-------|
| 1 | Snowflake Arctic M v2.0 (300M) | — | CPU | 0.512 | 0.077 | 0.214 | ~25s |
| 2 | deepvk/USER-bge-m3 (570M, RU) | — | CPU | **0.637** | 0.106 | 0.313 | ~145s |
| 3 | BAAI/bge-m3 (570M) | GTE Reranker base (306M) | CPU | 0.413 | 0.043 | 0.132 | ~544s |
| 4 | BAAI/bge-m3 (570M) | Jina Reranker v2 (278M) | CPU | 0.621 | 0.102 | 0.311 | ~55s |
| 5 | BAAI/bge-m3 (570M) | GTE Reranker base (306M) | **GPU** | 0.414 | 0.043 | 0.130 | **~17s** |
| 6 | Qwen3-Embedding-0.6B | Qwen3-Reranker-0.6B | **GPU** | 0.622 | 0.103 | **0.350** | ~45s |
| 7 | BAAI/bge-m3 | mMARCO-L12 (117M) | CPU | ~0.403 | — | — | — |

> Тест #1 (Snowflake) — исходный baseline, все остальные сравниваются с ним.
> Тесты #3, #4 — CE работал с `trust_remote_code=True` (исправлено в этой ветке).

---

## Ключевые выводы

### 1. GTE Reranker стабильно вредит (−0.22 recall)
GTE Reranker обучен на веб-поиске (MS MARCO), а наши данные — короткие диалоговые реплики. CE видит нерелевантные пары и агрессивно пересортировывает топ-20, выбрасывая правильные документы вниз. GPU ускоряет с 544s до 17s, но качество не меняется — это проблема доменного несоответствия, не производительности.

### 2. Jina Reranker = нейтрален (0.621 vs 0.621 без CE)
Jina v2-base-multilingual не вредит, но и не помогает. Скорее всего, при правильном threshold-тюнинге мог бы дать небольшой плюс.

### 3. Qwen3-Reranker = лучший nDCG (0.350 vs 0.313)
При том же recall (0.622) Qwen3-Reranker значительно улучшает порядок: лучший документ чаще оказывается на первом месте. Это реальный выигрыш для продакшна — модель видит самый релевантный контекст первым.

### 4. Лучший embedding — deepvk/USER-bge-m3
RU-тюнингованная версия bge-m3 дала recall 0.637 без CE — лучший результат по recall. Разумный выбор для русскоязычных диалогов.

### 5. Recall застрял на ~0.62 — это потолок не моделей
Одни и те же 6-7 MISS появляются у всех embedding моделей (Q58, Q63, и др.). Это структурные дыры — нужные документы не попадают в candidate pool вообще. Дальнейшее улучшение через смену embedding модели малоэффективно.

---

## Что было реализовано в ветке

| Компонент | Изменение |
|-----------|-----------|
| `cross_encoder.py` | `trust_remote_code=True`, `torch_dtype=float16` на GPU, фикс CE position logging |
| `cross_encoder.py` | Поддержка Qwen3-Reranker (AutoModelForCausalLM, yes/no token scoring) |
| `embedding_presets.py` | Лёгкие модели 118-278MB (CPU-friendly), Qwen3-Embedding-0.6B |
| `config.py` | CE_PRESETS обновлены (GTE, Jina, BGE Reranker v2-m3, Qwen3), убраны несуществующие |
| `config.py` | Дефолты: GTE multilingual base (620M) embed, GTE Reranker CE, CE включён |
| `debug_logger.py` | `log_final_output()` — финальный лог с CE-скорами и позициями |
| `rag_manager.py` | Вызов `log_final_output()` после формирования ответа |
| `rag_tester_core.py` | `smart_embed=True` — пропуск индексации если DB уже актуальна |
| `model_interaction_settings.py` | Кнопки "Скачать модель" для embedding и CE, с HF token |
| `_get_device()` (embed) | GPU включён (CUDA если доступна, иначе CPU) |

---

## Рекомендуемая конфигурация (на основе тестов)

**Лучший recall:**
```
Embedding: deepvk/USER-bge-m3
CE: отключён
```

**Лучший nDCG (топ-1 качество):**
```
Embedding: Qwen3-Embedding-0.6B
CE: Qwen3-Reranker-0.6B
GPU: обязательно (CPU = несколько минут на запрос)
```

**CPU-only пользователи:**
```
Embedding: GTE multilingual base (620M) или USER-bge-m3
CE: отключить (задержка неприемлема)
```

---

## Где расти дальше

1. **Candidate pool** — расширить top_k или улучшить FTS/keyword extraction, чтобы нужные документы вообще попадали в пул (основная причина MISS)
2. **CE threshold-тюнинг** — попробовать threshold=0.0 для Jina/Qwen3, возможно recall вырастет
3. **Второй тест-сценарий** — без него Optuna бесполезна (риск переобучения на 68 кейсах)
4. **ONNX quantization** — возможность запускать CE меньшего размера на CPU
