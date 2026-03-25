# RAG Pipeline Improvement Log

**Purpose:** Context document for AI assistants in future sessions. Summarizes the full history of RAG pipeline development, bugs found, fixes applied, and current state.

**Last updated:** 2026-03-25

**Branch:** `RAG-embedding-providers`

---

## 1. System Overview

### Pipeline Flow

```
Query
  └─► Embed (Qwen3-Embedding-0.6B)
        └─► Retrieval (parallel)
              ├─► Vector search (cosine similarity on embeddings)
              ├─► FTS search (SQLite full-text search)
              └─► Keyword search
        └─► Combiner (two_stage mode)
              └─► LinearReranker (weighted score: sim + time + priority + entity + keywords + lexical)
                    └─► CrossEncoder (Qwen3-Reranker-0.6B, alpha-mix CE score + normalized linear score)
                          └─► Threshold filter (RAG_SIM_THRESHOLD)
                                └─► Top-K results → LLM context
```

### Tech Stack

- **Storage:** SQLite with WAL mode (Write-Ahead Logging for concurrent reads)
- **Language:** Python
- **ML:** PyTorch, HuggingFace transformers
- **Numerics:** NumPy (matmul-based in-memory index), optional FAISS for ANN search
- **Hyperparameter optimization:** Optuna

### Python Environments

There are two distinct Python environments. Using the wrong one causes silent failures.

| Environment | Path | Has torch/transformers | Use for |
|---|---|---|---|
| **Venv** (ML) | `C:/Games/NeuroMita/Venv/Scripts/python.exe` | Yes (CUDA, torch 2.7.1+cu128, transformers 5.3.0) | All RAG tests, embedding, cross-encoder, Optuna |
| **libs/python** (game) | `C:/Games/NeuroMita/NeuroMita/libs/python/python.exe` | No | Running the game only |

**Critical rule:** Never use `libs/python` for RAG tests. It has no torch — embeddings silently fail, falling back to FTS-only.

### Database Paths

- **Live game DB:** `Histories/world.db` relative to game root (`C:/Games/NeuroMita/NeuroMita/`)
- **Main test DB:** `src/utils/Testing/rag_tester/Histories/test_qwen3_gpu.db`
- Test DB contains: 33 memories, ~25k history messages for character "Crazy", ~49 graph entities, ~38 relations

### RAG Tester Working Directory

```
C:/Games/NeuroMita/NeuroMita/src/utils/Testing/rag_tester/
```

---

## 2. Problems Identified & Fixes Applied

### 2.1 Silent Embedding Failure (CRITICAL BUG)

**Problem:** When `libs/python` (no torch) was used to run RAG tests, embeddings silently failed. The pipeline fell back to FTS-only retrieval. All embedding model tests returned identical results:

```
P=0.238  R=0.467  MRR=0.372
```

This made every model look the same — the embedding model was completely ignored.

**Root cause:** No error was raised when `query_vec` was `None`. The vector retriever silently returned nothing, and FTS filled all slots.

**Fixes applied:**
- `VectorRetriever` now logs a `WARNING` when `query_vec is None`
- `BatchResult` tracks `vector_doc_count` (number of docs that have stored embeddings)
- CLI performs a pre-flight check: exits with a fatal error if 0 embeddings are stored in the DB
- Documentation updated: always use `C:/Games/NeuroMita/Venv/Scripts/python.exe` for RAG tests

**Detection:** If you see all models scoring identically, check which Python is being used and whether `vector_doc_count > 0`.

---

### 2.2 Score Normalization Before CE Alpha-Mixing

**Problem:** The cross-encoder final score was computed as:

```python
score = alpha * CE_score + (1 - alpha) * linear_score
```

But `CE_score` is in roughly [0, 1] while `linear_score` can be any positive float (sum of weighted components). The mixing was meaningless — the linear term dominated or was negligible depending on scale.

**Fix:** MinMax-normalize linear scores to [0, 1] before mixing, in `cross_encoder.py`:

```python
min_s, max_s = min(linear_scores), max(linear_scores)
if max_s > min_s:
    linear_scores = [(s - min_s) / (max_s - min_s) for s in linear_scores]
```

**File:** `src/managers/rag/pipeline/cross_encoder.py`

---

### 2.3 Actor Pre-Filter

**New feature:** `RAG_PREFILTER_ACTORS` (bool, default `False`) in `pipeline/config.py`.

When enabled, a SQL pre-pass fetches documents where the speaker or target matches the current dialogue participants, using `threshold=0`. This biases retrieval toward messages involving the current participants before general vector/FTS search runs.

**File:** `src/managers/rag/pipeline/config.py`

---

### 2.4 Sentence-Level Retrieval

**New feature:** Two config keys added:
- `RAG_SENTENCE_LEVEL` (bool)
- `RAG_SENTENCE_MIN_LEN` (int, default 20)

**How it works:**
- New DB table `sentence_embeddings` with columns: `source_table`, `source_id`, `sentence_idx`, `embedding`
- Messages are split on punctuation + newlines; each sentence is embedded individually
- At query time, max-similarity sentence per message is retrieved; the whole message is returned

**Result:** Sentence-level retrieval **without** cross-encoder performed **worse** than whole-document retrieval. The finer granularity helps only when CE re-ranks candidates — the CE can identify which sentence actually matches the query. Without CE, sentence-level adds noise.

**Files:**
- `src/managers/rag/pipeline/retrievers/vector.py` — `_histories_sentence()`, `_memories_sentence()`
- `src/managers/database_manager.py` — `sentence_embeddings` table in `_upgrade_schema()`
- `src/managers/rag/rag_manager.py` — `_split_sentences()`, `_index_sentences()`, `_index_sentences_missing()`

---

### 2.5 Threshold Discovery (CRITICAL INSIGHT)

**Problem:** Optuna v4 was configured with threshold range `(0.05, 0.5)`. It found `threshold=0.355` as optimal.

At `threshold=0.355`, many relevant candidates were being cut **before** the cross-encoder could see them. The CE was never given a chance to rescue low-linear-score but semantically relevant documents.

**Discovery:** Manual test with `threshold=0` and `CE top_k=100`:

```
Recall: 0.467 → 0.750   (+60% improvement)
```

This was the single largest metric jump in the entire optimization process.

**Fix:** Optuna v5 changed threshold range to `(0.0, 0.4)`. The threshold's job is now to cut obvious garbage after CE has done its work, not to pre-filter before CE.

**Key insight:** With a strong cross-encoder, the threshold should be near 0. The CE itself is the filter.

**File:** `src/utils/Testing/rag_tester/optuna_sweep.py`

---

### 2.6 CE top_k Not Swept in Optuna

**Problem:** `RAG_CROSS_ENCODER_TOP_K` was fixed at the default value of 30 in all Optuna trials. This meant the optimization never explored how many candidates to pass to the CE.

**Fix:** Added `int_params` support to the Optuna sweep config:

```json
"int_params": {
  "RAG_CROSS_ENCODER_TOP_K": [30, 150]
}
```

Optuna now treats CE top_k as an integer hyperparameter to optimize.

**File:** `src/utils/Testing/rag_tester/optuna_sweep.py`

---

### 2.7 CE OOM When top_k Too High

**Problem:** The cross-encoder processed all `top_k` pairs in a single batch. With `top_k=200` on a GPU with only ~2.5GB free VRAM (15.93GB total, 13.38GB used by models), this caused Out-of-Memory errors.

**Fix:** Added mini-batch inference in `cross_encoder.py` with a configurable `batch_size`. Pairs are split into chunks and processed sequentially, accumulating scores.

**File:** `src/managers/rag/pipeline/cross_encoder.py`

---

### 2.8 Flat Candidate Scores When K2(time) ≈ 0

**Problem:** With `RAG_WEIGHT_TIME=0.001` (near-zero), the time component contributes almost nothing. All memories with the same priority cluster at approximately:

```
score ≈ K1 * similarity + K3 * 0.25
```

The scores are nearly identical for large numbers of candidates. CE top_k=75 out of 400+ candidates means 82% of candidates are never re-ranked. For abstract queries ("what do I hate?"), the relevant docs may not appear in the top 75 by linear score.

**Partial fix:** Increase CE top_k (currently set to 75). A proper fix requires better differentiation in linear scoring — either time matters again, or a different pre-ranking signal is needed.

**Status:** Ongoing. See Section 7 (Known Issues).

---

### 2.9 Graph Entity Quality

**Problem:** Gemma 1 (1B) extracts poor-quality entities:
- Punctuation in names: `kepochka?`
- Structural artifacts: `is bored`, `subject`, `predicate`
- Mixed Russian/English for the same concept: `chess` and `шахматы` as separate entities
- Abstract non-entities: `topic`, `conversation`

**Fixes applied:**

**Prompt:** Updated to say "Prefer Russian, no punctuation in names, avoid abstract entities."

**Code fixes:**
- `normalize_name()` in `graph_store.py`: strips punctuation, lowercases before insert
- New table `graph_entity_aliases`: tracks surface forms (all the ways a name has appeared)
- New table `graph_entity_embeddings`: stores entity name embeddings for vector deduplication

**Remaining issue:** Cross-lingual deduplication (chess vs шахматы) requires embedding similarity matching at insert time. `find_by_embedding()` method exists but dedup logic is not fully automatic.

**Recommended upgrade:** Gemma3-4B or Qwen3.5-0.6B for entity extraction, instead of Gemma 1 (1B).

**Files:**
- `src/managers/rag/graph/graph_store.py` — `normalize_name()`, `add_alias()`, `find_by_alias()`, `store_entity_embedding()`, `get_entities_without_embeddings()`, `find_by_embedding()`
- `src/managers/rag/rag_manager.py` — `index_graph_entity_embeddings()`

---

## 3. Architecture Changes (Key Files)

### `src/managers/rag/pipeline/cross_encoder.py`
- MinMax normalization of linear scores to [0, 1] before alpha-mixing with CE scores
- Mini-batch inference loop to prevent VRAM OOM on large `top_k`

### `src/managers/rag/pipeline/config.py`
- Added config keys:
  - `RAG_PREFILTER_ACTORS` → `prefilter_actors` (bool, default False)
  - `RAG_SENTENCE_LEVEL` → `sentence_level` (bool)
  - `RAG_SENTENCE_MIN_LEN` → `sentence_min_len` (int, default 20)
  - `RAG_GRAPH_VECTOR_SEARCH` → `graph_vector_search` (bool)

### `src/managers/rag/pipeline/retrievers/vector.py`
- Logs WARNING when `query_vec is None` (embedding failure detection)
- `_histories_actor_boost()`: SQL filtered by speaker/target for actor pre-filter
- `_histories_sentence()`, `_memories_sentence()`: sentence-level retrieval via JOIN on `sentence_embeddings`

### `src/managers/rag/pipeline/retrievers/graph.py`
- Vector search path: when `cfg.graph_vector_search=True` and `qs.query_vec is not None`, calls `gs.find_by_embedding(query_vec, threshold=0.55)`
- Additive with keyword match — both always run, results merged

### `src/managers/rag/graph/graph_store.py`
- `normalize_name()`: strips punctuation, lowercases — applied on every entity insert
- New tables: `graph_entity_aliases`, `graph_entity_embeddings`
- New methods: `add_alias()`, `find_by_alias()`, `store_entity_embedding()`, `get_entities_without_embeddings()`, `find_by_embedding()`

### `src/managers/rag/rag_manager.py`
- `_split_sentences()`: splits message text on punctuation + newlines
- `_index_sentences()`, `_index_sentences_missing()`: embeds sentences, stores in `sentence_embeddings`
- `index_graph_entity_embeddings()`: embeds entity names, stores in `graph_entity_embeddings`
- `index_all_missing()`: calls sentence indexing when `RAG_SENTENCE_LEVEL=True`; calls graph entity embedding when `RAG_GRAPH_VECTOR_SEARCH=True`

### `src/managers/database_manager.py`
- Added `sentence_embeddings` table in `_upgrade_schema()` (schema migration, safe to run on existing DBs)

### `src/utils/Testing/rag_tester/rag_tester_core.py`
- `BatchResult` extended with: `vector_doc_count`, `embed_model_name`, `warnings`
- Pre-flight check: exits with fatal error if `vector_doc_count == 0`

### `src/utils/Testing/rag_tester/optuna_sweep.py`
- Fixed threshold range: `(0.05, 0.5)` → `(0.0, 0.4)`
- Added `int_params` support for sweeping integer hyperparameters
- `RAG_CROSS_ENCODER_TOP_K` now swept in `[30, 150]`

### `src/utils/Testing/rag_tester/rag_tester_cli.py`
- Pre-flight embedding check before running test suite
- Auto-indexes graph entity embeddings when `RAG_GRAPH_VECTOR_SEARCH=true`

---

## 4. Metrics Reference

| Metric | Description | Notes |
|---|---|---|
| **Precision** | Fraction of returned docs that are relevant | Penalizes noise/irrelevant results |
| **Recall** | Fraction of relevant docs that were found | **Primary metric** — better to return extra than miss relevant |
| **MRR** | Mean Reciprocal Rank (1/rank of first relevant doc) | Critical when LLM only uses top-1 or top-3 results |
| **nDCG** | Normalized Discounted Cumulative Gain | Considers both rank position and multiple relevant docs |

**Why recall is primary:** The LLM can ignore irrelevant context, but it cannot use information that was never retrieved. Missing relevant memories causes the LLM to give worse answers.

### Metric Progression

```
Baseline (FTS only, wrong Python):                P=0.238  R=0.467  MRR=0.372
After fixing Python environment:                  embeddings actually work
After threshold=0 + CE top_k=100:                R=0.750   (+60% on recall)
Qwen3x2 + graph + vector search (100 cases):     R=0.757  MRR=0.556  nDCG=0.564
```

---

## 5. Test Infrastructure

### Test Databases

| DB | Path | Contents |
|---|---|---|
| Main test DB | `src/utils/Testing/rag_tester/Histories/test_qwen3_gpu.db` | Qwen3 embeddings, 33 memories, ~25k messages, character "Crazy" |
| Live game DB | `Histories/world.db` (relative to game root) | Production data |

Graph tables in test DB: ~49 entities, ~38 relations.

### Test Suite Files

| File | Description |
|---|---|
| `fixtures/crazy_suite_v4.json` | 100 test cases: positive retrieval, negative (absent topics), graph queries |
| `fixtures/crazy_suite_v4_split.json` | Split into train/val sets (59/19) for Optuna |
| `fixtures/crazy_scenario_full.json` | Scenario definition (character, dialogue state, available context) |
| `fixtures/crazy_optimize_v5.json` | Optuna config: 200 trials, metric=mean_recall, threshold range (0.0, 0.4) |

### Message ID Format

Test cases reference messages by MD5-based IDs:
- User messages: `in:md5hash`
- Assistant messages: `out:md5hash`

### Optuna Progress

- Progress file: `results/optuna_progress.json`
- **Warning:** With only 78 test cases (59 train / 19 val), overfitting is easy. Observed gap: train MRR=0.563 vs val MRR=0.421 (gap=0.142). Need 200+ cases for reliable optimization.

---

## 6. Current Best Settings (Applied to Game)

```json
{
  "RAG_EMBED_MODEL": "Qwen3-Embedding-0.6B (600M, 2025)",
  "RAG_CROSS_ENCODER_MODEL": "Qwen3-Reranker-0.6B (600M, 2025)",
  "RAG_CROSS_ENCODER_ENABLED": true,
  "RAG_CROSS_ENCODER_TOP_K": 75,
  "RAG_CROSS_ENCODER_ALPHA": 0.68,
  "RAG_SIM_THRESHOLD": 0.13,
  "RAG_WEIGHT_SIMILARITY": 1.27,
  "RAG_WEIGHT_TIME": 0.001,
  "RAG_WEIGHT_PRIORITY": 0.92,
  "RAG_WEIGHT_ENTITY": 0.52,
  "RAG_WEIGHT_KEYWORDS": 1.01,
  "RAG_WEIGHT_LEXICAL": 0.3,
  "RAG_COMBINE_MODE": "two_stage",
  "RAG_SEARCH_GRAPH": true
}
```

### Notes on Key Settings

- **`RAG_WEIGHT_TIME=0.001`** (near-zero): Time weight was penalizing old but highly relevant memories. Optuna found 0.54 on recent data, but that was overfitting to recency — old important memories were being buried.
- **`RAG_SIM_THRESHOLD=0.13`** (low): Keeps more candidates alive for the CE to re-rank. The CE is the real filter. Pre-CE threshold should be a loose gate, not a strict one.
- **`RAG_CROSS_ENCODER_TOP_K=75`**: May be too low. With 400+ candidates, CE only sees 18%. Consider 150-200. Limited by VRAM.
- **`RAG_CROSS_ENCODER_ALPHA=0.68`**: 68% CE score + 32% normalized linear score. Pure CE (alpha=1.0) not tested in A/B.

---

## 7. Known Issues & Limitations

### 7.1 Flat Candidate Pool Problem

**Symptom:** For abstract queries ("what do I hate?", "what am I afraid of?"), recall is lower than for specific queries.

**Cause:** With `K2(time)=0.001` and uniform priority, all linear scores cluster tightly. CE top_k=75 out of 400+ means 82% of candidates are never re-ranked. Relevant docs for abstract queries tend to have lower similarity scores (the query is indirect) and fall outside the CE window.

**Impact:** High — affects all abstract/indirect queries.

**Proposed fixes:**
1. Dynamic CE top_k: `min(150, n_candidates * 0.4)`
2. Query rewriting to make abstract queries more concrete before embedding
3. Predicate-based graph search for relation-type queries

### 7.2 Graph Entity Quality

**Symptom:** Entities like `is bored`, `kepochka?`, `subject`, `predicate` appear in the graph. Chess appears as both `chess` and `шахматы`.

**Cause:** Gemma 1 (1B) is too small for reliable structured extraction. The model produces structural artifacts (field names instead of values) and code-switches between languages.

**Current mitigations:** `normalize_name()` strips punctuation; `graph_entity_aliases` tracks all surface forms; `graph_entity_embeddings` enables vector-based dedup.

**Recommended fix:** Upgrade extraction model to Gemma3-4B or Qwen3.5-0.6B.

### 7.3 Duplicate Memories

**Symptom:** The same memory appears 5+ times with slight wording variation (e.g., "The basement holds secrets" extracted repeatedly).

**Cause:** No write-time deduplication. Each extraction pass re-inserts without checking for near-duplicates.

**Proposed fix:** At insert time, compute cosine similarity against existing memories. If `similarity > 0.92`, update the existing record instead of inserting a new one.

**Impact:** Wastes CE slots, artificially boosts some topics in retrieval.

### 7.4 Optuna Overfitting

**Symptom:** Train MRR=0.563, val MRR=0.421 (gap=0.142 with 78 total cases).

**Cause:** 78 test cases is too few for 7+ continuous hyperparameters. Optuna finds settings that are specialized to the training cases.

**Fix:** Expand test suite to 200+ cases before running further optimization.

### 7.5 History Search Disabled

**Status:** History search appears to be disabled in memory-only mode. Needs investigation of when/why it's turned off.

---

## 8. FAISS Integration

- **Status:** Implemented as optional backend in the vectorized in-memory index
- **Default:** NumPy matmul (`O(N)`) — fast enough for current scale (~25k messages)
- **FAISS:** Would give approximate nearest-neighbor (`O(log N)`), needed for production scale (>10k messages)
- **Config key:** `RAG_USE_FAISS` (implemented but not yet exposed in game UI)
- **When to enable:** When history grows beyond 5-10k messages and query latency becomes noticeable

---

## 9. Future Roadmap (Priority Order)

### High Priority

1. **Duplicate memory deduplication**
   - Write-time cosine similarity check against existing memories
   - If `similarity > 0.92` with any existing memory → update, not insert
   - Prevents CE slot waste and retrieval bias

2. **Dynamic CE top_k**
   - Replace fixed `top_k=75` with `min(150, n_candidates * 0.4)`
   - Adapts to actual candidate pool size
   - Ensures CE sees at least 40% of candidates

3. **More test cases**
   - Need 200+ total cases (currently 78) for Optuna to produce reliable results
   - Add cases for: abstract queries, graph-only information, multi-turn references, negative examples

4. **Graph entity extraction upgrade**
   - Replace Gemma 1 (1B) with Gemma3-4B or Qwen3.5-0.6B
   - Better language consistency, fewer structural artifacts, more accurate entity boundaries

### Medium Priority

5. **Predicate search in graph**
   - For queries like "what do I hate?" → search relations by predicate type (`dislikes`, `hates`, `ненавидит`)
   - Currently graph search only matches entity names, not relation types

6. **Graph coreference resolution**
   - When graph has `player --name_is--> Дима`, automatically add "Дима" as an alias for the "player" entity
   - Prevents same person being split into multiple disconnected nodes

7. **Sentence-level + CE A/B test**
   - Sentence retrieval was tested without CE and performed worse
   - Need explicit A/B test with CE enabled to determine if sentence-level + CE beats whole-doc + CE

8. **Query rewriting**
   - Small LLM rewrites abstract queries before embedding
   - Example: "что я ненавижу?" → "игрок ненавидит / отвращение игрока / игрок отказывается"
   - Improves recall for indirect/abstract queries

### Low Priority

9. **FAISS GPU index** for production scale (>10k messages)
10. **Score normalization A/B test:** compare `alpha=1.0` (pure CE) vs `alpha=0.68` (normalized mixing)
11. **Investigate history search** — determine why it's disabled in current mode and whether enabling it helps

---

## 10. Run Commands Reference

### Standard Test Run

```bash
cd src/utils/Testing/rag_tester

"C:/Games/NeuroMita/Venv/Scripts/python.exe" rag_tester_cli.py run \
  --db Histories/test_qwen3_gpu.db \
  --scenario fixtures/crazy_scenario_full.json \
  --suite fixtures/crazy_suite_v4.json \
  --limit 10 \
  --threshold 0.13 \
  --overrides '{"RAG_EMBED_MODEL":"Qwen3-Embedding-0.6B (600M, 2025)","RAG_CROSS_ENCODER_MODEL":"Qwen3-Reranker-0.6B (600M, 2025)","RAG_CROSS_ENCODER_ENABLED":true,"RAG_CROSS_ENCODER_TOP_K":75}' \
  --format text \
  --output results/result_name.txt
```

### Optuna Optimization

```bash
"C:/Games/NeuroMita/Venv/Scripts/python.exe" rag_tester_cli.py optimize \
  --scenario fixtures/crazy_scenario_full.json \
  --suite fixtures/crazy_suite_v4_split.json \
  --db Histories/test_qwen3_gpu.db \
  --optimize-config fixtures/crazy_optimize_v5.json \
  --overrides '{"RAG_EMBED_MODEL":"Qwen3-Embedding-0.6B (600M, 2025)","RAG_CROSS_ENCODER_MODEL":"Qwen3-Reranker-0.6B (600M, 2025)","RAG_CROSS_ENCODER_ENABLED":true}' \
  --metric mean_recall \
  --output results/optuna_result.txt
```

### Check Optuna Progress

```bash
cat src/utils/Testing/rag_tester/results/optuna_progress.json
```

### Quick Diagnostic (Check Embedding Is Working)

```bash
cd src/utils/Testing/rag_tester

# Should show vector_doc_count > 0; if 0, wrong Python is being used
"C:/Games/NeuroMita/Venv/Scripts/python.exe" rag_tester_cli.py run \
  --db Histories/test_qwen3_gpu.db \
  --scenario fixtures/crazy_scenario_full.json \
  --suite fixtures/crazy_suite_v4.json \
  --limit 1 \
  --format text
```

---

## 11. Checklist for Future Sessions

When picking up RAG work, verify:

- [ ] Using `C:/Games/NeuroMita/Venv/Scripts/python.exe` (not `libs/python`)
- [ ] Test DB is `test_qwen3_gpu.db` (has Qwen3 embeddings)
- [ ] `vector_doc_count > 0` in first test run output
- [ ] CE is enabled (`RAG_CROSS_ENCODER_ENABLED: true`)
- [ ] Threshold is low (`RAG_SIM_THRESHOLD ≤ 0.13`) to let CE see enough candidates
- [ ] Optuna suite is the split version (`crazy_suite_v4_split.json`) not the full suite
- [ ] Check `results/optuna_progress.json` before starting a new Optuna run (may have prior progress to resume)
