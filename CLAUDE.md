# Claude Code — Project Notes

## Python Environment

**Venv с torch/transformers/CUDA:**
```
C:\Games\NeuroMita\Venv\Scripts\python.exe
```
- torch 2.7.1+cu128 (CUDA)
- transformers 5.3.0
- Использовать для всех тестов RAG (embedding, cross-encoder, Optuna)

**libs/python (встроенный Python игры):**
```
C:\Games\NeuroMita\NeuroMita\libs\python\python.exe
```
- НЕ имеет torch/transformers — только FTS/keyword работает
- Использовать только для запуска игры, НЕ для ML-тестов

## RAG Tester

Рабочая директория:
```
C:\Games\NeuroMita\NeuroMita\src\utils\Testing\rag_tester\
```

Запуск тестов:
```bash
cd src/utils/Testing/rag_tester
"C:/Games/NeuroMita/Venv/Scripts/python.exe" rag_tester_cli.py run ...
```

Прогресс Optuna:
```
src/utils/Testing/rag_tester/results/optuna_progress.json
```
