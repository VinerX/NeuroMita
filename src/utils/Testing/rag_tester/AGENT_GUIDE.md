# RAG Testing & Optimization — Agent Playbook

Step-by-step guide for LLM agents (Claude Code) to test, evaluate, and optimize the RAG search pipeline.

## Quick Start

```
1. Export scenario → 2. Validate suite → 3. Baseline → 4. Optimize → 5. Apply → 6. Regression check
```

All commands run from `src/utils/Testing/rag_tester/`.

---

## Step 1: Export Full Scenario

Export character data from the live database into a portable JSON scenario:

```bash
python rag_tester_cli.py export \
  --db "C:\Games\NeuroMita\NeuroMita\Histories\world.db" \
  --character Crazy \
  --hist-limit 0 --mem-limit 0 \
  --output fixtures/crazy_scenario_full.json
```

- `--hist-limit 0` = all history messages (no limit)
- `--mem-limit 0` = all memories
- Graph entities/relations are exported automatically if present

---

## Step 2: Generate or Validate Test Suite

### Option A: Auto-generate via LLM (requires OpenAI-compatible API)

```bash
python rag_tester_cli.py generate-suite \
  --scenario fixtures/crazy_scenario_full.json \
  --output fixtures/crazy_suite_auto.json \
  --num-cases 40 \
  --api-base http://localhost:11434/v1 \
  --model gemma2:9b \
  --api-key dummy
```

Compatible APIs:
- **Ollama**: `--api-base http://localhost:11434/v1 --api-key dummy`
- **OpenRouter**: `--api-base https://openrouter.ai/api/v1 --api-key sk-...`
- **Google AI**: `--api-base https://generativelanguage.googleapis.com/v1beta/openai/ --api-key ...`

### Option B: Manual suite creation

Read the scenario file, identify interesting messages by their `message_id`, write queries:

```json
{
  "name": "My Suite",
  "character_id": "Crazy",
  "cases": [
    {
      "query": "Что игрок говорил про Warcraft?",
      "expected_ids": ["in:29719d9a..."],
      "relevance_grades": {"in:29719d9a...": 3},
      "description": "Direct mention of Warcraft"
    },
    {
      "query": "Что сегодня за погода?",
      "expected_ids": [],
      "description": "Negative: no weather discussion"
    }
  ]
}
```

### Validate suite against scenario

```bash
python rag_tester_cli.py validate \
  --scenario fixtures/crazy_scenario_full.json \
  --suite fixtures/crazy_suite_auto.json \
  --format json
```

**Result must show `"valid": true` and `"orphaned_count": 0`**. If not — some expected_ids reference messages not in the scenario.

---

## Step 3: Baseline Measurement

```bash
python rag_tester_cli.py run \
  --scenario fixtures/crazy_scenario_full.json \
  --suite fixtures/crazy_suite_auto.json \
  --format json \
  --output results/baseline.json
```

**Target metrics:**
- `mean_recall` >= 0.7 (must find relevant docs)
- `mean_precision` >= 0.3 (don't return too much noise)
- `mrr` >= 0.5 (relevant docs ranked high)
- `mean_ndcg` >= 0.4 (good ranking quality)

---

## Step 4: Optimize

### Option A: Bayesian optimization (recommended for >= 5 parameters)

```bash
python rag_tester_cli.py optimize \
  --scenario fixtures/crazy_scenario_full.json \
  --suite fixtures/crazy_suite_auto.json \
  --metric mean_recall \
  --n-trials 200 \
  --format json \
  --output results/optimize_result.json
```

Requires `pip install optuna`. Automatically samples from 10+ parameter ranges using TPE sampler.

### Option B: Grid sweep (for <= 3 parameters)

```bash
python rag_tester_cli.py sweep \
  --scenario fixtures/crazy_scenario_full.json \
  --suite fixtures/crazy_suite_auto.json \
  --sweep-config fixtures/crazy_sweep.json \
  --metric mean_recall \
  --format json \
  --output results/sweep_result.json
```

---

## Step 5: Apply Best Parameters

Take the best params from optimization output and update defaults:

**File**: `src/managers/rag/pipeline/config.py` → `RAG_DEFAULTS` dict

Or apply at runtime:

```bash
python rag_tester_cli.py run \
  --scenario ... --suite ... \
  --overrides '{"RAG_WEIGHT_SIMILARITY": 1.5, "RAG_WEIGHT_KEYWORDS": 0.8}' \
  --format json
```

---

## Step 6: Regression Check

```bash
python rag_tester_cli.py compare \
  --baseline results/baseline.json \
  --current results/optimized.json \
  --format json
```

Verdicts: `IMPROVED` (recall delta > +0.01), `REGRESSED` (< -0.01), `NEUTRAL`.

---

## Diagnostic: Common Failure Patterns

| Symptom | Root Cause | Fix |
|---------|-----------|-----|
| All recalls ~ 0 | Embeddings missing | Run `index_missing()` or re-export with `embed_now=True` |
| expected_ids orphaned | Scenario too small | Re-export with `--hist-limit 0` |
| High recall, low precision | Threshold too low | Raise `RAG_SIM_THRESHOLD` (try 0.3-0.5) |
| Good similarity but bad ranking | Weight imbalance | Sweep/optimize K1-K7 |
| Graph queries fail | `RAG_SEARCH_GRAPH=false` | Add `"RAG_SEARCH_GRAPH": true` to overrides |
| FTS finds nothing | FTS index not built | Check `history_fts` / `memories_fts` tables exist |
| Keyword search misses Russian | Lemmatization off | Set `RAG_LEMMATIZATION=true` |

## When to Change Code vs Parameters

- **Parameters**: retriever finds the document but ranks it too low → adjust K1-K7 weights
- **Code**: retriever doesn't find a relevant document at all → embeddings/FTS/keyword bug
- **Data**: test suite is incorrect → orphaned IDs, bad queries, wrong relevance grades

---

## Key RAG Parameters

| Parameter | Key | Default | Range |
|-----------|-----|---------|-------|
| Vector similarity weight | `RAG_WEIGHT_SIMILARITY` (K1) | 1.0 | 0.0 - 3.0 |
| Time decay weight | `RAG_WEIGHT_TIME` (K2) | 0.3 | 0.0 - 1.0 |
| Priority weight | `RAG_WEIGHT_PRIORITY` (K3) | 0.5 | 0.0 - 1.0 |
| Entity tag weight | `RAG_WEIGHT_ENTITY` (K4) | 0.5 | 0.0 - 1.0 |
| Keyword match weight | `RAG_WEIGHT_KEYWORDS` (K5) | 0.6 | 0.0 - 2.0 |
| FTS/lexical weight | `RAG_WEIGHT_LEXICAL` (K6) | 0.3 | 0.0 - 1.0 |
| Graph boost weight | `RAG_WEIGHT_GRAPH` (K7) | 1.5 | 0.0 - 3.0 |
| Similarity threshold | `RAG_SIM_THRESHOLD` | 0.3 | 0.05 - 0.5 |
| Combine mode | `RAG_COMBINE_MODE` | union | union/two_stage/intersect |
| Graph search | `RAG_SEARCH_GRAPH` | false | true/false |

---

## Files Reference

| File | Purpose |
|------|---------|
| `rag_tester_cli.py` | CLI entry point (run, sweep, optimize, validate, generate-suite, compare, export, template) |
| `rag_tester_core.py` | Core: Scenario, TestSuite, TestCase, RagTesterService, metrics |
| `sweep.py` | Grid sweep engine |
| `optuna_sweep.py` | Bayesian optimization via Optuna |
| `suite_generator.py` | LLM-powered test suite generation |
| `fixtures/` | Scenario, suite, sweep config JSON files |
| `../../managers/rag/pipeline/config.py` | RAGConfig with all parameter defaults |
