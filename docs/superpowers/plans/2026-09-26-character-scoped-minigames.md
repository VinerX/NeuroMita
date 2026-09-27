# Character Scoped Mini Games Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make Chess and Sea Battle launch against an explicitly selected launcher or current Unity character, while preventing private Unity runtime context from leaking between characters.

**Architecture:** Extend `GameLinkService` to expose the most recently addressed Unity character. The settings UI resolves a launch target and passes that character's own `GameManager`. Store persistent Unity snapshots by character and expose only whitelisted passive world facts to other characters; keep runtime events request scoped.

**Tech Stack:** Python, PyQt6, existing service registry, event bus, unittest.

**Spec:** User approved the detailed in-chat specification in the preceding task turn.

## Global Constraints

- Chess and Sea Battle use the same launch-target and session-owner policy.
- Do not switch the launcher's current character as a side effect of Unity requests.
- Runtime events, runtime rules, capabilities, intent rules, commands, and private game state are never shared across characters.
- Unity project changes, if needed, must go through Unity MCP; this implementation should use the existing request `character` field.
- Preserve unrelated user changes; commit and push only this task's allowlisted files as explicitly requested.

## Review Focus

- Unity connected but has not addressed a character yet: offer only valid launch targets.
- Unity target id is unknown to the current `CharacterRegistry`: don't route to an unloaded or missing character.
- Unity disconnects while a target is cached: clear the target.
- Concurrent Unity requests for different characters: each request prompt receives its own snapshot.
- Non-Unity desktop generation for another character: shared context contains only whitelisted informational facts.

---

### Task 1: Unity target state and explicit mini-game launch target

**Files:**
- Modify: `src/services/contracts.py`
- Modify: `src/services/game_link_service.py`
- Modify: `src/game_connections/handlers/actions/create_task.py`
- Modify: `src/ui/settings/game_settings.py`
- Test: `src/utils/Testing/test_game_link_target.py`

**Interfaces:**
- `GameLinkService.unity_target_character_id() -> str` returns last valid addressed target or empty string.
- `GameLinkService.set_unity_target_character_id(character_id: str) -> None` updates/reset the target.
- `_resolve_manual_game_target(gui, launcher_character)` prompts only when a distinct loaded Unity target exists and returns a loaded `Character` or `None` on cancel.

- [x] Add failing tests for Unity target storage/reset and manual launch using either selected character, Unity character, or cancellation.
- [x] Run the focused tests and confirm they fail for missing service/UI behavior.
- [x] Implement the service and update it from each incoming Unity `character`; clear it when server connection is lost.
- [x] Add a translated target-selection dialog; launch through the selected character's `game_manager` and preserve current settings checks.
- [x] Run the focused tests and verify both Chess and Sea Battle share this path.

### Task 2: Character scoped persistent Unity context

**Files:**
- Modify: `src/controllers/model_controller.py`
- Modify: `src/game_connections/handlers/actions/create_task.py`
- Reuse: `src/managers/game_state_manager.py`
- Test: add focused state isolation tests under `src/utils/Testing/`

**Interfaces:**
- `ModelController._get_game_state_for_character(character_id: str) -> dict` returns a copy of that character's snapshot, or an empty snapshot.
- `extract_shared_world_info(snapshot: dict) -> dict` returns only explicitly whitelisted informational fields.
- Request `game_state` takes precedence; desktop requests use their character snapshot plus shared informational facts.

- [x] Add failing tests proving snapshots remain isolated and shared context excludes runtime/command fields.
- [x] Run tests and confirm they fail for the current global state.
- [x] Replace the global snapshot with a locked per-character mapping and update `SET_GAME_DATA` to carry `character_id`.
- [x] Maintain shared context through a positive whitelist of passive fields; never construct it by subtracting known unsafe keys.
- [x] Preserve request-local `runtime_events`; never add them to persistent state.
- [x] Run focused state tests and existing game context tests.

### Task 3: Owner stability and regression coverage for both games

**Files:**
- Read only: `src/managers/game_manager.py`, `src/modules/Chess/game_instance.py`, `src/modules/SeaBattle/seabattle_instance.py`
- Test: use existing `src/utils/Testing/test_manual_game_launch.py`, `test_chess_move_reactions.py`, and `test_seabattle_lifecycle_reactions.py`

- [x] Confirm the existing ownership behavior passes for both games; avoid introducing session machinery if owner is already stable.
- [x] Existing Chess and Sea Battle lifecycle reaction tests confirm moves/close stay routed through the owning `GameManager`; no additional session wrapper is required.
- [x] Run the relevant Python test subset and `git diff --check`.
