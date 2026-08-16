# RAG and knowledge graph — user guide

## What is RAG?

**RAG (Retrieval-Augmented Generation)** automatically searches relevant information from previous conversations and character memories before each LLM response, then adds it to the model context. This lets the model recall facts that have already moved outside its context window.

**Simple analogy:** imagine an assistant opening a notebook before every response and rereading the notes that matter. RAG is that automatic notebook.

---

## How it works, step by step

### 1. You write a message

When you send a message to a character, the system first runs a RAG search using your text.

### 2. Relevant information is searched

Several methods run in parallel:

| Method | What it does | Analogy |
| --- | --- | --- |
| **Vector search** | Searches by meaning (semantic similarity) | “Find notes on a similar topic” |
| **Full-text search (FTS)** | Searches exact words (BM25) | “Find notes containing these words” |
| **Keywords** | Matches keywords | A fallback for records without embeddings |
| **Knowledge graph** | Searches related entities | “Who is connected to whom, and how?” |

### 3. Results are scored and ranked

Results are evaluated using several criteria:

- **Semantic similarity** (K1 = 1.0) — how close the context is in meaning;
- **Keywords** (K5 = 0.6) — matching concrete words;
- **Priority** (K3 = 0.5) — memory priority (critical/high/normal/low);
- **Participants** (K4 = 0.5) — matching speakers or conversation targets;
- **Recency** (K2 = 0.3) — newer records are slightly preferred;
- **Lexical score** (K6 = 0.3) — full-text BM25 score.

The final score is approximately `K1×sim + K2×time + K3×prio + K4×entity + K5×kw + K6×lex + noise`.

### 4. Results are added to the prompt

The best results (up to 8 by default) are added to the system prompt before the request is sent to the model:

```xml
<relevant_memories>
- [0.89] (memory, prio=High, date=2025-03-20) Alice likes cats
- [0.76] (memory, prio=Normal, date=2025-03-19) We discussed books with Boris
</relevant_memories>

<past_context>
- [0.85] (2025-03-21 14:30) (Alice→Boris) Have you seen that film?
- [0.71] (2025-03-21 14:15) (Boris) Yes, I really liked it
</past_context>
```

### 5. The LLM generates a response

The model sees these blocks and can use them to produce a more informed response.

---

## Knowledge graph memory

### What is it?

Knowledge graph memory automatically extracts **entities** (people, places, objects, and concepts) and **relationships** between them from each conversation.

### How does it work?

After each message, in the background:

1. The dialogue text (player message and character response) is collected.
2. It is sent to the LLM provider with an entity-extraction prompt.
3. The LLM returns JSON containing entities and relationships.
4. The result is stored in the database (`graph_entities` and `graph_relations` tables).

### How is the graph used in search?

When **Search the knowledge graph during RAG** is enabled:

1. Keywords are extracted from your query.
2. Keywords are matched against entity names in the graph.
3. Relationships for matching entities are loaded (one hop).
4. Relationships are formatted as triples such as `Alice --gave--> Boris`.
5. They are added to RAG results alongside memories and history.

---

## Settings

### Main RAG settings

| Setting | Default | Description |
| --- | --- | --- |
| **RAG enabled** | Off | Main switch. When off, the embedding model is not loaded. |
| **Maximum results** | 8 | Number of best results inserted into the prompt. |
| **Similarity threshold** | 0.3 | Minimum score for a result to be included. |

### Knowledge graph settings

| Setting | Default | Description |
| --- | --- | --- |
| **Entity extraction** | Off | Enable automatic extraction of entities from conversations. |
| **Graph provider** | Current | LLM preset used for extraction; a lightweight model is recommended. |
| **Search the graph** | Off | Include graph results in the RAG search. |

### Ranking weights

Weights determine which factors matter more when results are ranked. They can be changed in the interface:

- **Similarity (1.0)** — semantic closeness, the main factor;
- **Keywords (0.6)** — keyword matches;
- **Priority (0.5)** — memory priority;
- **Entity (0.5)** — matching conversation participants;
- **Time (0.3)** — record recency;
- **Lexical (0.3)** — full-text score.

### Combination modes

| Mode | Description |
| --- | --- |
| **Union** (default) | Combines all results with deduplication. |
| **Vector only** | Semantic search only (fast). |
| **Intersect** | Only results found by at least N methods (higher precision). |
| **Two-stage** | Vector search provides recall, while other methods add ranking signals. |

---

## Recommendations

### Quick start

1. Enable RAG in settings.
2. Wait about a minute for the embedding model to load.
3. Continue the conversation for a few messages — RAG will start adding relevant context.

### For knowledge graph memory

1. Enable **Entity extraction**.
2. Use a separate lightweight preset, such as GPT-4o-mini or Gemini Flash, so the main model is not overloaded.
3. Enable **Search the knowledge graph during RAG**.
4. The graph will fill automatically as you continue chatting.

### Optimisation

- If results are too noisy, raise the similarity threshold (0.4–0.5).
- If the context is too long, reduce the maximum number of results (4–6).
- For short dialogues, `weighted` query embeddings usually work better than `concat`.
- If precision is more important, try `intersect` mode.

---

## Embedding model

RAG uses **Snowflake Arctic Embed M v2.0** to create vector representations of text. The model:

- runs locally and does not require an API;
- runs on the CPU and does not require a GPU;
- downloads automatically on first use;
- is approximately 110 MB.

Embeddings are created for each history message and memory, then stored in the SQLite database.

---

## Customising templates

RAG result formatting templates can be overridden for each prompt set. Put the files in the set's `Structural/` folder:

- `rag_memory_item.txt` — one memory line;
- `rag_history_item.txt` — one history line;
- `rag_wrapper.txt` — wrapper for the complete RAG block;
- `graph_extraction_prompt.txt` — entity-extraction prompt.

### Available template variables

**Memory:** `{score}`, `{type}`, `{priority}`, `{date}`, `{content}`

**History:** `{score}`, `{date}`, `{meta}`, `{content}`, `{speaker}`, `{target}`, `{role}`

**Wrapper:** `{memory_block}`, `{history_block}`, `{graph_block}`

**Entity extraction:** `{text}` — the dialogue text to analyse.
