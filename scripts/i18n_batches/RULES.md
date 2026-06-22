# Translation rules (shared)

You translate UI strings for **NeuroMita**, a PyQt6 desktop launcher that gives game characters (the "Mitas" from the game Miside) an LLM-based mind: voice, emotions, memory, RAG.

Input file: a JSON object `{ "russian_key": "english_value", ... }`.
Output file: a JSON object `{ "russian_key": "<translation>", ... }`.

## Hard rules
1. **KEYS stay byte-identical** to the input (never modify the Russian keys).
2. Translate the **English value** into the TARGET LANGUAGE (do not translate from the Russian).
3. **Preserve every placeholder exactly**, same count, same spelling, no reordering:
   `{}`, `{0}`, `{ver}`, `{path}`, `{symbol}`, `{name}`, `{used}`, `{max}`, `{pct}`, `{cost:.4f}`, `%s`, `%d`, etc.
4. **Preserve leading/trailing spaces** exactly (e.g. `"Conversation with "` keeps its trailing space).
5. **Preserve `\n`, HTML tags** (`<b>`, `<br>`, `<i>`, …), **markdown, and emojis** (🔒 ✅ ⚠ 🎤 …) exactly as-is.
6. Keep product / standard tech tokens **untranslated**: `API`, `RAG`, `ASR`, `TTS`, `RVC`, `CUDA`, `HuggingFace`, `Gemini`, `OpenAI`, `Telegram`, `NeuroMita`, `Mita`, `FTS`, `JSON`, `GPU`, `URL`, `Optuna`, `Triton`, `ffmpeg`. (You MAY transliterate the proper noun "Mita" if that is the norm for the target language, but stay consistent.)
7. Tone: concise, standard **software-UI** register for the target language (infinitive/imperative for buttons, nouns for labels). Match capitalization conventions of the target language.

## Output
- Write the result JSON to the specified output path. UTF-8, real native characters (not escaped), 2-space indent.
- After writing, reply with ONE line: the output path + number of keys. No other commentary.
