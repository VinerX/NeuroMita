"""
GraphController — background entity extraction from dialogue messages.

Subscribes to MESSAGE_COMPLETED, extracts entities/relations via a
configurable LLM provider (GRAPH_PROVIDER setting), stores them in GraphStore.

Pattern mirrors HistoryController._compress_history() but runs asynchronously
in a background thread to never block the conversation.
"""
from __future__ import annotations

import json
import os
from concurrent.futures import ThreadPoolExecutor
from typing import Any, ClassVar, Dict, List, Optional

from core.events import get_event_bus, Events, Event
from main_logger import logger

# Default extraction prompt (can be overridden via GRAPH_EXTRACTION_PROMPT setting
# or via Structural/graph_extraction_prompt.txt in the prompt set).
_DEFAULT_EXTRACTION_PROMPT = """\
Extract named entities and their relationships from this conversation snippet.
Output ONLY valid JSON, no commentary or markdown:
{"entities":[{"name":"alice","type":"person"},{"name":"chess","type":"concept"}],
 "relations":[{"s":"alice","p":"likes","o":"chess"}]}

Rules:
- Entity names: 1-3 words, lowercase, real nouns only (people, places, objects, topics).
- Predicates: short verb phrases — "likes", "lives in", "is afraid of", "owns".
- The AI character is referred to as "mita" (or their actual name if stated).
- The human player is referred to as "player" (or their real name if stated).
- DO NOT extract grammar roles: do not use "subject", "verb", "object", "predicate", "action" as names or predicates.
- DO NOT extract emotion/animation tags: angry, sad, smile, smileteeth, magiceye, trytoque, discontent, etc.
- DO NOT extract pronouns or generic words: it, they, he, she, we, you, i, thing, person, character.
- DO NOT extract interjections or filler words.
- Only extract clearly stated facts, not speculation or hypotheticals.
- If nothing meaningful to extract, return {{"entities":[],"relations":[]}}

Conversation:
{text}"""


class GraphController:
    """Coordinates background graph extraction."""

    _executor: ClassVar[Optional[ThreadPoolExecutor]] = None

    def __init__(self):
        self.event_bus = get_event_bus()
        self._subscribe()

    @classmethod
    def _get_executor(cls) -> ThreadPoolExecutor:
        if cls._executor is None:
            cls._executor = ThreadPoolExecutor(
                max_workers=1, thread_name_prefix="graph-extract"
            )
        return cls._executor

    def _subscribe(self):
        self.event_bus.subscribe(
            Events.History.MESSAGE_COMPLETED,
            self._on_message_completed,
            weak=False,
        )

    # ------------------------------------------------------------------
    # Settings helpers
    # ------------------------------------------------------------------
    def _get_setting(self, key: str, default: Any = None) -> Any:
        try:
            res = self.event_bus.emit_and_wait(
                Events.Settings.GET_SETTING,
                {"key": key, "default": default},
                timeout=1.0,
            )
            return res[0] if res else default
        except Exception:
            return default

    def _is_enabled(self) -> bool:
        return bool(self._get_setting("GRAPH_EXTRACTION_ENABLED", False))

    def _is_inline_mode(self) -> bool:
        return bool(self._get_setting("GRAPH_EXTRACTION_INLINE", False))

    def _get_preset_description(self, preset_id: Optional[int]) -> str:
        """Return a human-readable 'Name (model)' string for logging."""
        try:
            effective_id = preset_id
            if effective_id is None:
                res = self.event_bus.emit_and_wait(
                    Events.ApiPresets.GET_CURRENT_PRESET_ID, {}, timeout=1.0
                )
                effective_id = res[0] if res else None

            if effective_id is None:
                return "Current"

            res = self.event_bus.emit_and_wait(
                Events.ApiPresets.GET_PRESET_FULL, {"id": effective_id}, timeout=1.0
            )
            info = res[0] if res else None
            if not info:
                return f"preset#{effective_id}"

            name = info.get("name") or f"preset#{effective_id}"
            model = info.get("default_model") or ""
            return f"{name} ({model})" if model else name
        except Exception:
            return f"preset#{preset_id}"

    # ------------------------------------------------------------------
    # Event handler
    # ------------------------------------------------------------------
    def _on_message_completed(self, event: Event) -> None:
        """Called after every assistant response is saved."""
        if not self._is_enabled():
            logger.debug("[GraphController] Skipped: GRAPH_EXTRACTION_ENABLED is False")
            return

        data = event.data or {}
        char_id = data.get("character_id")
        if not char_id:
            return

        character = data.get("character_ref")
        if character is None:
            return

        # Gather the messages that were just saved (user + assistant).
        user_input = str(data.get("user_input") or "").strip()
        assistant_output = str(data.get("assistant_output") or data.get("response_text") or "").strip()
        created_memory_ids: List[int] = data.get("created_memory_ids") or []
        inline_graph_json: Optional[str] = data.get("inline_graph_json")
        if not user_input and not assistant_output:
            return

        text = ""
        if user_input:
            text += f"Player: {user_input}\n"
        if assistant_output:
            text += f"Character: {assistant_output}\n"

        # Inline mode: model already embedded the graph JSON in its response.
        if inline_graph_json and self._is_inline_mode():
            logger.info(f"[GraphController] Inline graph JSON received for '{char_id}', storing directly")
            try:
                self._get_executor().submit(
                    self._store_inline, character, char_id, inline_graph_json,
                    user_input, assistant_output, created_memory_ids,
                )
            except Exception as e:
                logger.warning(f"[GraphController] Failed to schedule inline store: {e}")
            return

        # Schedule extraction via separate provider call.
        logger.info(f"[GraphController] Scheduling extraction for '{char_id}' ({len(text)} chars)")
        try:
            self._get_executor().submit(
                self._extract_and_store, character, char_id, text.strip(),
                user_input, assistant_output, created_memory_ids,
            )
        except Exception as e:
            logger.warning(f"[GraphController] Failed to schedule extraction: {e}")

    # ------------------------------------------------------------------
    # Background extraction
    # ------------------------------------------------------------------
    def _extract_and_store(
        self,
        character,
        char_id: str,
        text: str,
        user_input: str = "",
        assistant_output: str = "",
        created_memory_ids: Optional[List[int]] = None,
    ) -> None:
        """Run in background thread: call LLM provider, parse JSON, store graph."""
        try:
            # Build prompt.
            prompt = self._build_extraction_prompt(character, text)
            if not prompt:
                logger.warning("[GraphController] Empty extraction prompt, skipping.")
                return

            # Resolve provider preset.
            provider_label = str(self._get_setting("GRAPH_PROVIDER", "Current"))
            preset_id = self._resolve_preset(provider_label)
            preset_desc = self._get_preset_description(preset_id)
            logger.info(
                f"[GraphController] Extracting graph for '{char_id}' "
                f"via {preset_desc}"
            )

            # Call provider.
            res = self.event_bus.emit_and_wait(
                Events.Model.GENERATE_RESPONSE,
                {
                    "user_input": "",
                    "system_input": prompt,
                    "image_data": [],
                    "stream_callback": None,
                    "message_id": None,
                    "event_type": "graph_extract",
                    "preset_id": preset_id,
                },
                timeout=30.0,
            )

            if not res:
                logger.warning(
                    "[GraphController] emit_and_wait returned empty list — "
                    "either no subscriber for GENERATE_RESPONSE or subscriber returned None "
                    "(generation failed). Check model_controller logs above."
                )
                return
            if not res[0]:
                logger.warning(f"[GraphController] Provider returned falsy result: {res[0]!r}")
                return

            raw_response = str(res[0])
            # Truncate for logging to avoid flooding.
            preview = raw_response[:500] + ("..." if len(raw_response) > 500 else "")
            logger.info(f"[GraphController] Raw LLM response: {preview}")

            # Parse and store.
            from managers.rag.graph.entity_extractor import (
                parse_extraction_response,
                store_extraction,
            )
            from managers.rag.graph.graph_store import GraphStore
            from managers.database_manager import DatabaseManager

            extraction = parse_extraction_response(raw_response)
            if extraction is None:
                logger.warning(
                    f"[GraphController] Could not parse extraction JSON from response: {preview}"
                )
                return

            entities = extraction.get("entities", [])
            relations = extraction.get("relations", [])
            # Normalise: some local models return bare strings instead of dicts.
            entities = [
                e if isinstance(e, dict) else {"name": str(e), "type": "thing"}
                for e in entities if e
            ]
            logger.info(
                f"[GraphController] Parsed: {len(entities)} entities, "
                f"{len(relations)} relations"
            )
            if entities:
                ent_names = [e.get("name", "?") for e in entities[:10]]
                logger.info(f"[GraphController] Entities: {ent_names}")
            if relations:
                rel_strs = [
                    f"{r.get('s','?')} --{r.get('p','?')}--> {r.get('o','?')}"
                    for r in relations[:10]
                ]
                logger.info(f"[GraphController] Relations: {rel_strs}")

            db = DatabaseManager()
            gs = GraphStore(db, char_id)
            n_ent, n_rel = store_extraction(gs, extraction)

            logger.info(
                f"[GraphController] Stored {n_ent} entities, {n_rel} relations "
                f"for '{char_id}' (total in DB: {gs.get_stats()})"
            )

            # Tag source history messages with extracted entity names.
            if entities:
                entity_names = [e.get("name", "") for e in entities if e.get("name")]
                self._tag_history_messages(
                    db, char_id, entity_names,
                    user_input, assistant_output,
                )
                if created_memory_ids and hasattr(character, "memory_system"):
                    tagged_mem = 0
                    for eid in created_memory_ids:
                        if character.memory_system.tag_with_entities(eid, entity_names):
                            tagged_mem += 1
                    if tagged_mem:
                        logger.info(
                            f"[GraphController] Tagged {tagged_mem} memory(ies) "
                            f"with {len(entity_names)} entities"
                        )

        except Exception as e:
            logger.warning(f"[GraphController] Extraction failed (ignored): {e}", exc_info=True)

    def _store_inline(
        self,
        character,
        char_id: str,
        json_str: str,
        user_input: str = "",
        assistant_output: str = "",
        created_memory_ids: Optional[List[int]] = None,
    ) -> None:
        """Store graph JSON that was already extracted inline by the main model."""
        try:
            from managers.rag.graph.entity_extractor import (
                parse_extraction_response,
                store_extraction,
            )
            from managers.rag.graph.graph_store import GraphStore
            from managers.database_manager import DatabaseManager

            extraction = parse_extraction_response(json_str)
            if extraction is None:
                logger.warning(f"[GraphController] Inline graph JSON unparseable: {json_str[:200]}")
                return

            entities = extraction.get("entities", [])
            entities = [
                e if isinstance(e, dict) else {"name": str(e), "type": "thing"}
                for e in entities if e
            ]
            logger.info(
                f"[GraphController] Inline: {len(entities)} entities, "
                f"{len(extraction.get('relations', []))} relations for '{char_id}'"
            )

            db = DatabaseManager()
            gs = GraphStore(db, char_id)
            n_ent, n_rel = store_extraction(gs, extraction)
            logger.info(f"[GraphController] Inline stored {n_ent} entities, {n_rel} relations")

            if entities:
                entity_names = [e.get("name", "") for e in entities if e.get("name")]
                self._tag_history_messages(db, char_id, entity_names, user_input, assistant_output)
                if created_memory_ids and hasattr(character, "memory_system"):
                    for eid in created_memory_ids:
                        character.memory_system.tag_with_entities(eid, entity_names)

        except Exception as e:
            logger.warning(f"[GraphController] Inline store failed (ignored): {e}", exc_info=True)

    @staticmethod
    def _tag_history_messages(
        db,
        char_id: str,
        entity_names: List[str],
        user_input: str,
        assistant_output: str,
    ) -> None:
        """Tag recent history rows (matched by content) with extracted entity names.

        Uses a merge strategy: existing entity tags are preserved, new ones added.
        """
        if not entity_names:
            return

        # Find the most recent history entries that match the texts we extracted from.
        # We match by content substring + character_id to avoid tagging wrong rows.
        texts_to_match = []
        if user_input and user_input.strip():
            texts_to_match.append(user_input.strip())
        if assistant_output and assistant_output.strip():
            texts_to_match.append(assistant_output.strip())

        if not texts_to_match:
            return

        try:
            with db.connection() as conn:
                cur = conn.cursor()

                # Check if 'entities' column exists (migration may not have run yet).
                cur.execute("PRAGMA table_info(history)")
                cols = {row[1] for row in cur.fetchall()}
                if "entities" not in cols:
                    logger.debug("[GraphController] 'entities' column not in history table, skip tagging")
                    return

                new_names_set = {n.lower().strip() for n in entity_names if n.strip()}
                entities_json = json.dumps(sorted(new_names_set), ensure_ascii=False)

                for txt in texts_to_match:
                    # Match by exact content and character_id, most recent first.
                    cur.execute(
                        """
                        SELECT id, entities FROM history
                        WHERE character_id = ? AND content = ?
                        ORDER BY id DESC LIMIT 1
                        """,
                        (char_id, txt),
                    )
                    row = cur.fetchone()
                    if not row:
                        continue

                    row_id = row[0]
                    existing_raw = row[1]

                    # Merge with existing entities.
                    try:
                        existing = set(json.loads(existing_raw or "[]"))
                    except (json.JSONDecodeError, TypeError):
                        existing = set()

                    merged = existing | new_names_set
                    merged_json = json.dumps(sorted(merged), ensure_ascii=False)

                    cur.execute(
                        "UPDATE history SET entities = ? WHERE id = ?",
                        (merged_json, row_id),
                    )

                conn.commit()

                tagged_count = len(texts_to_match)
                logger.info(
                    f"[GraphController] Tagged {tagged_count} history message(s) "
                    f"with {len(new_names_set)} entities: {sorted(new_names_set)[:5]}"
                )

        except Exception as e:
            logger.warning(f"[GraphController] Failed to tag history messages (ignored): {e}", exc_info=True)

    def _build_extraction_prompt(self, character, text: str) -> Optional[str]:
        """Load extraction prompt template, format with message text.

        Resolution order:
        1. GRAPH_EXTRACTION_PROMPT setting (custom override).
        2. Character's prompt-set Structural/graph_extraction_prompt.txt.
        3. Prompts/Common/graph_extraction_prompt.txt (shared base for prompters).
        4. Hardcoded _DEFAULT_EXTRACTION_PROMPT.
        """
        # 1. Custom setting override.
        custom = self._get_setting("GRAPH_EXTRACTION_PROMPT", None)
        if custom and str(custom).strip():
            return str(custom).strip().replace("{text}", text)

        def _try_load(path: str) -> Optional[str]:
            if os.path.isfile(path):
                try:
                    with open(path, "r", encoding="utf-8") as f:
                        return f.read().strip()
                except Exception:
                    pass
            return None

        # 2. Character's own Structural folder.
        base_path = getattr(character, "base_data_path", None)
        if base_path:
            tmpl = _try_load(os.path.join(base_path, "Structural", "graph_extraction_prompt.txt"))
            if tmpl:
                return tmpl.replace("{text}", text)

        # 3. Shared Common folder (resolved relative to Prompts root).
        prompts_root = None
        if base_path:
            # base_data_path is like  .../Prompts/Kind/Default  → go up 2 levels
            prompts_root = os.path.normpath(os.path.join(base_path, "..", ".."))
        if prompts_root:
            tmpl = _try_load(os.path.join(prompts_root, "Common", "graph_extraction_prompt.txt"))
            if tmpl:
                return tmpl.replace("{text}", text)

        # 4. Hardcoded default.
        return _DEFAULT_EXTRACTION_PROMPT.replace("{text}", text)

    def _resolve_preset(self, label: str) -> Optional[int]:
        """Resolve provider label (preset name or numeric ID) to preset_id."""
        if not label or label in ("Current", "Текущий"):
            return None
        # Try numeric ID first (legacy / direct ID usage).
        try:
            return int(label)
        except ValueError:
            pass
        # Look up by display name via ApiPresets event.
        try:
            meta_res = self.event_bus.emit_and_wait(
                Events.ApiPresets.GET_PRESET_LIST, timeout=1.0
            )
            meta = meta_res[0] if meta_res else None
            if meta:
                for bucket in ("custom", "builtin"):
                    for pm in (meta.get(bucket) or []):
                        if getattr(pm, "name", None) == label:
                            pid = getattr(pm, "id", None)
                            if isinstance(pid, int):
                                return pid
            logger.warning(
                f"[GraphController] Could not resolve preset name '{label}' to ID, "
                f"falling back to current preset."
            )
        except Exception as e:
            logger.warning(f"[GraphController] Preset name lookup failed: {e}")
        return None
