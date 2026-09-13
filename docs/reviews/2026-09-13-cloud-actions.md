# Review: cloud providers, speech, prompts and Unity actions

Reviewed branch: `feature/fish-audio-and-custom-provider`, original head `d30b762`.
Baseline: `VinerX/NeuroMita main`, `9f76d0e73f8ddaa71f68c867c2011736eb7e9584` (remote head verified).
Original scope: 42 changed files, 3293 additions / 246 deletions, plus the installed Linux overlay.

## Confirmed findings and fixes

| Severity | Finding and consequence | Fix / code |
|---|---|---|
| High | `secret_exposed: 0.3` or `-0.5` failed validation of an otherwise usable response; legacy fallback lost the action arrays. Seen in saved Crazy and Kind responses. | Ambiguous flags become unspecified during coercion, preserving segments. `src/utils/structured_response_parser.py`. Coercion still marks control-plane metadata untrusted. |
| High | A required custom delta missing from the response received `PydanticUndefined` as its default; validation failed again and lost actions. | Recognize Pydantic's undefined sentinel and use neutral typed defaults. |
| High | `image_description` containing segment-shaped objects replaced already valid segments, potentially replacing their actions. | Recovery uses that source only when real segments are missing/invalid; otherwise discard the invalid image description. |
| High | Misplaced `love_change` in `memory_update` was not handled, dropping the response. | Recover declared custom deltas from both memory fields; do not turn arbitrary objects into memory operations. |
| High | Character instructions taught legacy commands and did not distinguish refusal from agreeing without execution. The runtime specifically prefers typed movement intents. | Add action/utterance consistency to the gated runtime contract, prioritize typed movement, distinguish player sleep permission from actor sleep, respect occupancy/arrival, remove obsolete commands from the rewritten Crazy prompt. No keyword-driven forced obedience, invented coordinates, or stat reset. |
| High | ASR key lookup trusted a preset number/base/name even when its destination was another provider. | Reuse a key only for the NanoGPT destination (or its unmodified inherited template URL); explicit ASR key/environment remain supported. Stop searching unrelated working-directory profiles; disable redirects on audio upload. |
| Medium | ASR preview used `/api/transcribe` with a `file` upload, while that API expects `audio`; actual recognition used another contract. | Preview and recognition now share `request_nanogpt_transcription`, using `/api/v1/audio/transcriptions`, Bearer auth and `file`. Omit language for auto-detection. |
| Medium | ASR save called nonexistent `set_engine_settings`, swallowed the exception, and left cached runtime settings stale. Persistence failures also looked successful. | Call `apply_settings`; propagate persistence errors and show save failure in UI. |
| Medium | ASR tests persisted real settings and depended on an ambient API key. | Temporary settings service and explicit fake credentials; runtime mutation mocked. |
| Medium | A second streamed HTTP 400 was not read before JSON parsing; `json_schema → json_object → text` fallback stopped prematurely. | Read the second error body. Regression uses actual unread httpx streaming responses. |
| Medium | Enabling native tools for every custom endpoint assumed a capability not implied by OpenAI Chat Completions compatibility. | Conservative native-tools default; JSON response mode and its compatibility fallback remain enabled. |
| Medium | Speech/subtitle cleanup removed ordinary bracketed words, mentions of schema field names, and valid Fish tags `love` / `long-break`; an unfinished bracket could leak filter state into the next segment. | Narrow technical marker recognition, preserve ordinary contents, remove broad word deletion, reset stream bracket state. |
| Medium | Microphone enumeration assumed host API index 0 meant ALSA and hid other input devices. VAD failure instantiated a fresh adaptive detector for each chunk. | Keep available input devices visible and retain the fallback detector across chunks. |
| High, local only | Bulk source copying had reverted the earlier Linux game controller fixes. Proton wrapper remained, but process-tree stopping, environment cleanup and timer isolation were gone. | Restore owned process-object capture, exact executable/create-time matching, cancellable stop timer, clean Python environment and expected-stop handling in local overlay only. |

## Checks

- 60 branch tests pass, including 11 new regression tests. The same 60 pass importing the installed `NeuroMita.pyz` in a temporary profile.
- 102 selected upstream tests run: 100 pass, 1 skipped, 1 pre-existing failure. The failure is `ContextBudgetTests.test_every_active_mita_template_includes_common_dialogue_contract`: `Crazy/By_mactep_kot_new_mini/main_template.txt` lacks `Common/Dialogue.txt`. Both the test and that template are byte-identical to upstream. This is outside the changed Default prompt set.
- Replay of 27 saved nonempty responses: all 26 JSON responses parse; 11 retain physical-action fields. The remaining response is a plain-text history summary, not structured JSON.
- Three real NanoGPT requests with the configured GLM model and captured runtime contract return: following (`actor.set_movement_mode`, with interaction exit), a free sofa seat (`Sofa left_1`), and actor sleep (`actor.sleep`). These requests test model output; they were not dispatched to the running game.
- Six local process tests pass, including three real fake-wrapper launches and PID-reuse isolation.
- Installed GUI/backend smoke passes on an isolated profile and port. Archive CRC and all 39 patched module hashes verified.
- `git diff --check` passes.

## Limits and rollout

The confirmed backend defect is loss of valid actions during response validation, not merely low relationship stats. Some earlier replies also contained no physical commands; the prompt change improves that case, but model compliance remains probabilistic.

The installed client is an IL2CPP Unity binary; the current Unity source project is not in this repository. Its runtime contract was inspected from saved requests. The claimed universal 1.5–2 m interaction threshold was not independently verified. Queueing navigation and sitting in consecutive speech segments does not prove arrival. No synthetic coordinates or binary patches were introduced.

The Unity log also contains duplicate interaction-key warnings (e.g. Sofa variants); whether a warning caused a particular failed interaction requires client-side reproduction. This report does not claim an observed physical game movement after the fix.

Portable fixes belong to this PR. Linux controller/wrapper and installed archive remain local. Restart the launcher and game to load the updated code; validate following, seating, and sleep in the active scene. Backend logs now include `StructuredActions` counts without dialogue or credentials, making missing model commands distinguishable from client execution failures.

API references: [NanoGPT transcription contract](https://docs.nano-gpt.com/api-reference/endpoint/audio-transcriptions), [legacy transcription contract](https://docs.nano-gpt.com/api-reference/endpoint/transcribe).
