"""Prompt contract rendered from the exact sparse wire DTO."""
from __future__ import annotations

import json

from schemas.sparse_structured_response import build_sparse_response_model
from schemas.structured_response import StructuredResponse


def render_sparse_response_contract(profile, model_cls=StructuredResponse, *, reply_limits=None) -> str:
    wire = build_sparse_response_model(model_cls or StructuredResponse, profile)
    schema = wire.json_schema_dict()
    base_example = {"segments": [{"text": "Hello."}], "changes": []}
    lines = [
        "[Structured Response Contract: sparse_changes_v1]",
        "This contract defines the JSON wire format for this request and supersedes field layouts in older examples or history.",
        'Return one JSON object with required "segments" and "changes" arrays. No text outside JSON.',
        "Segment text contains spoken words, never XML tags or action descriptions. Keep commands, intents, animations and other segment fields inside the corresponding segment.",
        "Put only operations needed this turn in changes. Do not emit null, zero or empty-list changes for unused operations.",
        "Only top-level response operations use changes. Segment fields never belong in changes and changes never contain a segment index.",
        "Each top-level list item is its own change; preserve their order. A scalar change may appear only once per type. Never repeat actions from previous turns.",
        "Segment actions trigger with their segment; target means the exact active character identifier for its spoken text.",
    ]
    segment_schema = schema["properties"]["segments"]["items"]
    segment_variants = segment_schema.get("anyOf", [segment_schema])
    lines.append("Choose the smallest segment variant containing every field needed for that segment. Each segment may choose a different variant.")
    lines.append("All fields in the chosen variant are required; use [] or null for unused fields in that variant. Do not emit fields belonging only to larger variants.")
    for variant in segment_variants:
        lines.append("Allowed segment fields: " + ", ".join(variant["properties"]) + ".")
    lines.append("Segment field definitions: " + json.dumps(segment_variants[-1]["properties"], ensure_ascii=False))
    lines.append("Only the following change shapes are allowed for this request:")
    variants = schema["properties"]["changes"]["items"].get("anyOf", [schema["properties"]["changes"]["items"]])
    change_names = {variant["properties"]["type"]["enum"][0] for variant in variants}
    for variant in variants:
        properties = variant["properties"]
        shape = {}
        for name, value in properties.items():
            if name == "type":
                shape[name] = value["enum"][0]
            elif "enum" in value:
                shape[name] = "one of: " + ", ".join(value["enum"])
            else:
                shape[name] = "<" + str(value.get("type", "object")) + ">"
        description = properties.get("value", {}).get("description", "")
        lines.append(json.dumps(shape, ensure_ascii=False) + (" — " + description if description else ""))
        if properties.get("value", {}).get("type") == "object":
            lines.append("Value object schema: " + json.dumps(properties["value"], ensure_ascii=False))

    root_fields = set(schema["properties"]) - {"segments", "changes"}
    if root_fields:
        lines.append("Additional required ROOT fields for this request: " + ", ".join(sorted(root_fields)) + ".")
    if "reasoning" in root_fields:
        lines.append("Write reasoning before segments. Keep it brief; it is never shown to the player.")
    if "secret_exposed" in root_fields:
        lines.append('"secret_exposed" is required by the active schema: decide true/false, or null when no reveal decision is needed. Do not put it in changes.')
    if "custom_fields" in root_fields:
        lines.append('"custom_fields" is a required root object: fill all declared custom parameters using their specified types and limits, never invent keys.')
        lines.append("Custom parameter schema: " + json.dumps(schema["properties"]["custom_fields"], ensure_ascii=False))
    lines.extend([
        "Do not put undeclared fields at the root or inside segments. Top-level operations use the change shapes above.",
        "Base example (include any additional required root fields listed above): " + json.dumps(base_example, ensure_ascii=False),
        'Memory example change: {"type":"memory_add","value":"island:language|Русский. Отвечай Игроку по-русски."}',
        "Create memory only for stable preferences, promises, relationship shifts or important story facts; update near-duplicates. Do not memorize greetings or temporary world state.",
        "Memory islands: island:<type>|content updates the existing island. Types: relationship, opinion, preferences, commitments_conflicts, language.",
        "The language island stores the Player's primary conversation language. If absent, infer it from the first clear natural-language Player message and create the language island. Change it only on an explicit request to switch; quotes, code and isolated foreign words do not change it. Reply in the stored language.",
        "Stat deltas are normally absent (internally 0). Use small changes, usually -2..2, only for actual feeling changes; retain the current scale.",
        "Speak concisely, usually 1-3 segments. Length limits apply to total spoken text across segments. Split only when emotion, action, target or a significant beat changes.",
        "Use only commands and intent identifiers explicitly exposed by the current runtime. Intent types are not command strings; do not guess Cat or other identifiers: use exact runtime payload keys and values.",
        "Physical events from [Unity Runtime Events] should get a bodily reaction or gaze first, then words, when those actions are available.",
        "[SYSTEM INFO] is system information, not Player speech; [SPEAKER] identifies multi-speaker dialogue.",
    ])
    if reply_limits:
        lines.append(
            f"Ordinary reply: {reply_limits['REPLY_TARGET_MIN_WORDS']}-{reply_limits['REPLY_TARGET_MAX_WORDS']} words total. "
            f"Hard maximum: {reply_limits['REPLY_HARD_MAX_WORDS']} words, {reply_limits['REPLY_MAX_SEGMENTS']} segments. "
            f"Usually at most {reply_limits['REPLY_SEGMENT_MAX_WORDS']} words per segment. Reply style: {reply_limits['REPLY_STYLE']}."
        )
    if "tool_call" in change_names:
        lines.extend([
            'tool_call change: choose only a tool from [Available Tools]. args is a JSON object ENCODED AS A STRING, e.g. "{\\\"expression\\\":\\\"2+2\\\"}". Fill actual required arguments.',
            "Use a short acknowledgement segment (2-5 words). Tool names never belong in commands. The tool result arrives in the next turn; then answer fully.",
        ])
    if "intents" in segment_variants[-1]["properties"]:
        lines.append("Segment intents: type is the verified Unity intent identifier; payload is a JSON object encoded as a string. Use dialogue.continue only when immediate continuation is intended.")
    return "\n".join(lines)
