# Generation Tester

Headless tester for the real NeuroMita generation pipeline.

What it does:
- runs real `Events.Model.GENERATE_RESPONSE` without UI
- preserves prompt building, history, RAG, tools, usage, cache stats
- stores per-turn artifacts, including `last_request_context.json`

Important:
- default mode is sandboxed: it copies `Settings/` and `Histories/` into an isolated runtime directory
- `--live` runs against live data and will mutate history/memory/reminders
- run it with the same Python/venv as the app, not a random system Python
- logs are quiet by default; use `--verbose` when you need bootstrap details
- by default sandboxes and run artifacts are written into the current working directory:
  - `.generation_tester_sandboxes/`
  - `.generation_tester_runs/`

## Quick start

Print scenario template:

```bash
C:\Games\NeuroMita\Venv\Scripts\python.exe generation_tester_cli.py --base-dir "C:\Games\NeuroMita\NeuroMitaBuildForPrompters7" template
```

Run one turn:

```bash
C:\Games\NeuroMita\Venv\Scripts\python.exe generation_tester_cli.py \
  --base-dir "C:\Games\NeuroMita\NeuroMitaBuildForPrompters7" \
  chat \
  --character Crazy \
  --message "Привет. Ответь коротко."
```

Repeat the same turn several times for cache debugging:

```bash
C:\Games\NeuroMita\Venv\Scripts\python.exe generation_tester_cli.py \
  --base-dir "C:\Games\NeuroMita\NeuroMitaBuildForPrompters7" \
  chat \
  --character Crazy \
  --preset "Current" \
  --message "Повтори мысль одной фразой." \
  --repeat 3
```

Replay last saved request context:

```bash
C:\Games\NeuroMita\Venv\Scripts\python.exe generation_tester_cli.py \
  --base-dir "C:\Games\NeuroMita\NeuroMitaBuildForPrompters7" \
  replay-last
```

Inspect latest saved request/response context:

```bash
C:\Games\NeuroMita\Venv\Scripts\python.exe generation_tester_cli.py \
  --base-dir "C:\Games\NeuroMita\NeuroMitaBuildForPrompters7" \
  inspect-last
```

Run scenario JSON:

```bash
C:\Games\NeuroMita\Venv\Scripts\python.exe generation_tester_cli.py \
  --base-dir "C:\Games\NeuroMita\NeuroMitaBuildForPrompters7" \
  scenario \
  --scenario my_generation_case.json
```

## Artifacts

By default each run writes:

- `summary.json`
- `turn_001.json`, `turn_002.json`, ...

These contain:
- input turn payload
- final result
- token stats
- saved `last_request_context`

## Notes

- `chat` and `scenario` mutate runtime history because they exercise the real pipeline.
- `replay-last` reuses prepared messages directly and does not append a new dialog turn to history.
- For cache debugging, compare `cached_prompt_tokens` and `cache_write_tokens` across repeated runs.
