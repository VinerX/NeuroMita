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
Extract entities and relations from this dialogue message.
Output ONLY valid JSON (no commentary):
{"entities":[{"name":"...","type":"person|place|thing|concept"}],
 "relations":[{"s":"subject","p":"predicate","o":"object"}]}

Rules:
- Keep entity names short (1-3 words).
- Use lowercase for names and predicates.
- Only extract clearly stated facts, not speculation.
- If nothing meaningful, return {"entities":[],"relations":[]}

Message:
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
        if not user_input and not assistant_output:
            return

        text = ""
        if user_input:
            text += f"Player: {user_input}\n"
        if assistant_output:
            text += f"Character: {assistant_output}\n"

        # Schedule extraction in background.
        logger.info(f"[GraphController] Scheduling extraction for '{char_id}' ({len(text)} chars)")
        try:
            self._get_executor().submit(
                self._extract_and_store, character, char_id, text.strip(),
                user_input, assistant_output,
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

        except Exception as e:
            logger.warning(f"[GraphController] Extraction failed (ignored): {e}", exc_info=True)

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
        """Load extraction prompt template, format with message text."""
        # Try custom template from settings.
        custom = self._get_setting("GRAPH_EXTRACTION_PROMPT", None)
        if custom and str(custom).strip():
            template = str(custom).strip()
        else:
            # Try character's prompt set Structural directory.
            base_path = getattr(character, "base_data_path", None)
            if base_path:
                template_file = os.path.join(base_path, "Structural", "graph_extraction_prompt.txt")
                if os.path.isfile(template_file):
                    try:
                        with open(template_file, "r", encoding="utf-8") as f:
                            template = f.read().strip()
                    except Exception:
                        template = _DEFAULT_EXTRACTION_PROMPT
                else:
                    template = _DEFAULT_EXTRACTION_PROMPT
            else:
                template = _DEFAULT_EXTRACTION_PROMPT

        return template.replace("{text}", text)

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
